"""Opt-in, grant-scoped Inbox invalidations for SDK 2 subscriptions.

Only opaque URIs leave the observer. Snapshots are always read through Norman's
API with the requesting grant. In-memory leases intentionally require one MCP
process (or sticky routing), and must be recreated after reconnect/restart.
"""

import asyncio
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

import anyio
import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.subscriptions import ResourceUpdated, SubscriptionBus
from mcp.shared.exceptions import MCPError
from mcp.types import SubscriptionsListenRequestParams, SubscriptionsListenResult
from pydantic import Field

from norman_mcp.api.client import NormanAPI
from norman_mcp.apps.inbox import READ, load_inbox
from norman_mcp.context import Context
from norman_mcp.security.utils import validate_url

PREFIX = "norman://inbox/"
DENIED = "Inbox watch is unavailable. Reopen it for the selected company."
TTL = 300
INTERVAL = 30
MAX_WATCHES = 128
MAX_PER_GRANT = 4
MAX_LISTENERS = 128
logger = logging.getLogger(__name__)


def fingerprint(data: dict[str, Any]) -> str:
    semantic = {key: value for key, value in data.items() if key != "asOf"}
    return hashlib.sha256(
        json.dumps(semantic, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass
class Watch:
    uri: str
    token: str
    client_id: str
    company: str
    selection: str | None
    page: int
    expires: float
    digest: str
    listeners: int = 0


class PinnedAPI(NormanAPI):
    """Background reads never resolve a caller ContextVar or env credentials."""

    def __init__(self, provider: Any, watch: Watch):
        super().__init__(authenticate_on_init=False, token_source="oauth")
        self.provider = provider
        self.watch = watch

    @property
    def company_id(self) -> str:
        return self.watch.company

    def _resolve_norman_token(self) -> str | None:
        token: str | None = self.provider.get_norman_token(self.watch.token)
        return token

    async def arequest(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        # Native async HTTP lets cancellation close the socket, without leaving
        # requests threads running after a snapshot releases its concurrency slot.
        if method != "GET" or not validate_url(url):
            raise ValueError("Inbox observer only supports trusted API reads.")
        token = self._resolve_norman_token()
        if not token:
            return {"error": "Inbox connection is unavailable.", "status_code": 401}
        try:
            async with httpx.AsyncClient(
                timeout=10.0, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.get(
                    url,
                    params=kwargs.get("params"),
                    headers={
                        "Authorization": "Bearer " + token,
                        "X-Company-Id": self.watch.company,
                        "User-Agent": "NormanMCPServer/0.1.0",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                )
                if response.status_code != 200:
                    return {
                        "error": "Inbox source is unavailable.",
                        "status_code": response.status_code,
                    }
                data = response.json()
                return data if isinstance(data, dict) else {"error": "Inbox source is unavailable."}
        except (httpx.RequestError, ValueError):
            return {"error": "Inbox source is unavailable."}

    def _refresh_oauth_norman_token(self) -> None:
        # A failed grant ends the lease; no ambient credential fallback.
        return None


class ObservedAPI:
    """Keep authorization failures visible despite the Inbox's outage handling."""

    def __init__(self, api: Any):
        self.api = api
        self.denied = False

    @property
    def company_id(self) -> str | None:
        company: str | None = self.api.company_id
        return company

    async def arequest(self, *args: Any, **kwargs: Any) -> Any:
        result = await self.api.arequest(*args, **kwargs)
        if isinstance(result, dict) and result.get("status_code") in (401, 403):
            self.denied = True
        return result


class InboxLive:
    def __init__(self, provider: Any, bus: SubscriptionBus):
        self.provider = provider
        self.bus = bus
        self.watches: dict[str, Watch] = {}
        self.listeners = 0
        self.closed = False
        self._snapshot_slots = asyncio.Semaphore(4)

    def valid(self, watch: Watch) -> bool:
        access = self.provider.tokens.get(watch.token)
        return bool(
            not self.closed
            and self.watches.get(watch.uri) is watch
            and watch.expires > time.time()
            and access
            and access.client_id == watch.client_id
            and (access.expires_at is None or access.expires_at > time.time())
            and self.provider.get_norman_token(watch.token)
            and self.provider.get_company_for_token(watch.token) == watch.selection
        )

    def permitted(self, uri: str, api: Any) -> Watch:
        watch = self.watches.get(uri)
        access = get_access_token()
        if (
            not watch
            or not access
            or not secrets.compare_digest(access.token, watch.token)
            or access.client_id != watch.client_id
            or not self.valid(watch)
            or str(api.company_id) != watch.company
        ):
            raise MCPError(-32602, DENIED)
        return watch

    def prune(self) -> None:
        for uri, watch in list(self.watches.items()):
            if not self.valid(watch):
                self.watches.pop(uri, None)

    async def snapshot(self, api: Any, page: int) -> tuple[dict[str, Any], bool]:
        observed = ObservedAPI(api)
        with anyio.fail_after(15):
            async with self._snapshot_slots:
                data = await load_inbox(observed, page)
        return data, observed.denied

    async def open(self, api: Any, page: int) -> dict[str, Any]:
        access = get_access_token()
        if self.closed:
            raise ToolError(DENIED)
        if not access or not api.company_id:
            raise ToolError("Inbox watches require an authenticated Norman connection.")
        self.prune()
        # Idempotent within the lease; no extra watchers on tool retries.
        for watch in self.watches.values():
            if (
                watch.token == access.token
                and watch.company == str(api.company_id)
                and watch.page == page
            ):
                self.permitted(watch.uri, api)
                return self.description(watch)
        if (
            len(self.watches) >= MAX_WATCHES
            or sum(watch.token == access.token for watch in self.watches.values()) >= MAX_PER_GRANT
        ):
            raise ToolError("Inbox watch limit reached. Retry after the current lease expires.")
        selection = self.provider.get_company_for_token(access.token)
        company = str(api.company_id)
        provisional = Watch("", access.token, access.client_id, company, selection, page, 0, "")
        try:
            data, denied = await self.snapshot(PinnedAPI(self.provider, provisional), page)
        except TimeoutError:
            raise ToolError("Inbox is busy. Retry opening the watch shortly.") from None
        watch = Watch(
            uri=PREFIX + secrets.token_urlsafe(24),
            token=access.token,
            client_id=access.client_id,
            company=company,
            selection=selection,
            page=page,
            expires=min(time.time() + TTL, access.expires_at or float("inf")),
            digest=fingerprint(data),
        )
        # Re-check after awaited reads, and re-check quotas for concurrent opens.
        self.prune()
        if self.closed or denied or data.get("error") or len(data.get("unavailable", [])) == 3:
            raise ToolError(DENIED)
        if (
            len(self.watches) >= MAX_WATCHES
            or sum(w.token == access.token for w in self.watches.values()) >= MAX_PER_GRANT
        ):
            raise ToolError("Inbox watch limit reached. Retry after the current lease expires.")
        for existing in self.watches.values():
            if (
                existing.token == watch.token
                and existing.company == company
                and existing.page == page
            ):
                self.permitted(existing.uri, api)
                return self.description(existing)
        self.watches[watch.uri] = watch
        try:
            self.permitted(watch.uri, api)
        except MCPError:
            self.watches.pop(watch.uri, None)
            raise ToolError(DENIED) from None
        return self.description(watch)

    @staticmethod
    def description(watch: Watch) -> dict[str, Any]:
        return {
            "resourceUri": watch.uri,
            "expiresAt": watch.expires,
            "page": watch.page,
            "pollIntervalSeconds": INTERVAL,
            "instructions": (
                "Use SDK 2 subscriptions/listen for this URI, then resources/read. "
                "Each update is only an invalidation: refetch the resource. Reopen "
                "the watch after expiry, reconnect or company switch. This observes "
                "one approval page and bounded tax reviews, not all company changes. "
                "Legacy clients can use get_norman_inbox_data instead."
            ),
        }

    async def read(self, uri: str, api: Any) -> str:
        watch = self.permitted(uri, api)
        data, denied = await self.snapshot(PinnedAPI(self.provider, watch), watch.page)
        if denied:
            self.watches.pop(uri, None)
            raise MCPError(-32602, DENIED)
        self.permitted(uri, api)
        return json.dumps(data)

    async def gate(self, ctx: Any, call_next: Any) -> Any:
        if ctx.method == "tools/call" and (ctx.params or {}).get("name") == "switch_company":
            access = get_access_token()
            if access:
                # Invalidate before the switch awaits its access check, including
                # rapid A -> B -> A switches that a polling comparison can miss.
                for uri, watch in list(self.watches.items()):
                    if watch.token == access.token:
                        self.watches.pop(uri, None)
        if ctx.method != "subscriptions/listen":
            return await call_next(ctx)
        params = SubscriptionsListenRequestParams.model_validate(ctx.params or {}, by_name=False)
        watches = {
            uri: self.permitted(uri, ctx.lifespan_context["api"])
            for uri in params.notifications.resource_subscriptions or ()
            if uri.startswith(PREFIX)
        }
        if not watches:
            return await call_next(ctx)
        if self.listeners >= MAX_LISTENERS:
            raise MCPError(-32602, "Inbox stream limit reached.")
        self.listeners += 1
        for watch in watches.values():
            watch.listeners += 1
        try:
            # Cancel only this listen request. The SDK performs unsubscribe and
            # stream cleanup in its own finally; no private SDK stream access.
            with anyio.CancelScope() as scope:
                async with anyio.create_task_group() as group:

                    async def until_invalid() -> None:
                        while all(self.valid(w) for w in watches.values()):
                            delay = min(1.0, min(w.expires for w in watches.values()) - time.time())
                            await anyio.sleep(max(0, delay))
                        scope.cancel()

                    group.start_soon(until_invalid)
                    result = await call_next(ctx)
                    group.cancel_scope.cancel()
            if scope.cancel_called:
                return SubscriptionsListenResult(
                    _meta={"io.modelcontextprotocol/subscriptionId": ctx.request_id}
                )
            return result
        finally:
            self.listeners -= 1
            for watch in watches.values():
                watch.listeners -= 1

    async def observe(self, watch: Watch) -> None:
        if not self.valid(watch) or not watch.listeners:
            return
        try:
            data, denied = await self.snapshot(PinnedAPI(self.provider, watch), watch.page)
        except TimeoutError:
            return
        except Exception:
            logger.warning("Inbox observer read failed; retrying next cycle")
            return
        if denied:
            self.watches.pop(watch.uri, None)
            return
        if not self.valid(watch) or not watch.listeners:
            return
        digest = fingerprint(data)
        if digest != watch.digest:
            watch.digest = digest
            await self.bus.publish(ResourceUpdated(uri=watch.uri))

    async def tick(self) -> None:
        self.prune()
        # Bounded batches keep API concurrency at 4 watches / 12 source reads.
        active = [w for w in self.watches.values() if w.listeners]
        for start in range(0, len(active), 4):
            results = await asyncio.gather(
                *(self.observe(w) for w in active[start : start + 4]), return_exceptions=True
            )
            if any(isinstance(result, Exception) for result in results):
                logger.warning("Inbox observer failed; retrying next cycle")

    async def run(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(INTERVAL)

    def close(self) -> None:
        self.closed = True
        self.watches.clear()


def register_inbox_live(mcp: Any, service: InboxLive) -> None:
    mcp.middleware.append(service.gate)

    @mcp.tool(title="Watch Norman Inbox", annotations=READ)
    async def watch_norman_inbox(
        ctx: Context, page: int = Field(default=1, ge=1)
    ) -> dict[str, Any]:
        """Create a five-minute resource lease for read-only Inbox invalidations.
        Subscribe with SDK 2 subscriptions/listen and refetch with resources/read.
        Nothing is approved, sent, paid or filed. Unsupported clients use
        get_norman_inbox_data. Leases bind to this connection, company and page.
        """
        return await service.open(ctx.request_context.lifespan_context["api"], page)

    @mcp.resource(
        PREFIX + "{watch_id}",
        name="norman-inbox-watch",
        title="Selected company's Inbox snapshot",
        mime_type="application/json",
    )
    async def inbox_snapshot(watch_id: str, ctx: Context) -> str:
        return await service.read(PREFIX + watch_id, ctx.request_context.lifespan_context["api"])
