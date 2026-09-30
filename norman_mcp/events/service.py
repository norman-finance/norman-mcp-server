"""Draft MCP Events methods and a durable workflow-attention webhook worker.

Norman's existing API remains the source of truth. The worker reads only runs
explicitly subscribed to, then delivers signed webhooks to ChatGPT. This is
server-side observation, not the unsupported ChatGPT polling delivery mode.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.shared.exceptions import MCPError
from mcp.types import RequestParams
from pydantic import BaseModel, ConfigDict, Field

from norman_mcp.api.client import NormanAPI
from norman_mcp.apps.inbox import read
from norman_mcp.context import get_oauth_provider
from norman_mcp.events import webhooks
from norman_mcp.events.store import SubscriptionStore

logger = logging.getLogger(__name__)
EVENT = "workflow.attention_required"
MAX_LIFETIME = 3600
REASONS = {"user_input", "manual_step", "source_required", "ai_limit", "step_failed"}


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    run_id: UUID


class Delivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["webhook"]
    url: str = Field(max_length=2048)
    secret: str | None = None


class Subscribe(RequestParams):
    name: Literal["workflow.attention_required"]
    arguments: Arguments
    delivery: Delivery
    cursor: None = None
    ttl_ms: int | None = Field(default=3600000, alias="ttlMs", ge=60000)


class Unsubscribe(RequestParams):
    name: Literal["workflow.attention_required"]
    arguments: Arguments
    delivery: Delivery


def iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def principal(access: Any, provider: Any) -> str:
    # This token is already authenticated by the MCP OAuth middleware. Decode
    # only to establish a stable owner across MCP token refresh, never to grant access.
    try:
        claims = jwt.decode(
            provider.get_norman_token(access.token), options={"verify_signature": False}
        )
        user = claims.get("user_id") or claims.get("sub")
        if not user:
            raise ValueError
        return hashlib.sha256(f"{access.client_id}:{user}".encode()).hexdigest()
    except Exception:
        raise MCPError(-32602, "The connected account has no stable event identity.") from None


def identity(owner: str, params: Subscribe | Unsubscribe) -> str:
    payload = {
        "owner": owner,
        "name": params.name,
        "arguments": params.arguments.model_dump(mode="json"),
        "url": params.delivery.url,
    }
    return (
        "sub_"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


class EventService:
    def __init__(
        self,
        store: SubscriptionStore,
        provider: Any = None,
        *,
        post: Callable[..., tuple[int, dict[str, Any]]] = webhooks.post,
    ) -> None:
        self.store = store
        self.provider = provider
        self.post = post

    async def caller(self, ctx: Any, params: Subscribe) -> tuple[Any, Any, str, dict[str, Any]]:
        provider = self.provider or get_oauth_provider()
        access = get_access_token()
        if not provider or not access:
            raise MCPError(-32602, "Events require an authenticated Norman connection.")
        api = ctx.lifespan_context["api"]
        company = str(params.arguments.company_id)
        if str(api.company_id) != company:
            raise MCPError(-32602, "Select the subscribed company before managing its events.")
        run = await read(api, f"assistant/workflow-runs/{params.arguments.run_id}/")
        if run.get("error") or str(run.get("publicId")) != str(params.arguments.run_id):
            raise MCPError(-32602, "Workflow is unavailable to this account.")
        return provider, access, principal(access, provider), run

    async def list_events(self, ctx: Any, params: RequestParams) -> dict[str, Any]:
        return {
            "events": [
                {
                    "name": EVENT,
                    "description": "A selected Norman workflow stops and needs your attention.",
                    "delivery": ["webhook"],
                    "inputSchema": Arguments.model_json_schema(),
                    "payloadSchema": {
                        "type": "object",
                        "properties": {
                            "company_id": {"type": "string"},
                            "run_id": {"type": "string"},
                            "title": {"type": "string"},
                            "reason": {"type": "string"},
                            "detail": {"type": "string"},
                        },
                        "required": ["company_id", "run_id", "title", "reason", "detail"],
                        "additionalProperties": False,
                    },
                }
            ]
        }

    async def subscribe(self, ctx: Any, params: Subscribe) -> dict[str, Any]:
        provider, access, owner, _run = await self.caller(ctx, params)
        secret = params.delivery.secret
        try:
            webhooks.signing_key(secret or "")
        except ValueError:
            raise MCPError(-32602, "A valid whsec_ signing secret is required.") from None
        sid = identity(owner, params)
        now = time.time()
        records = self.store.records()
        if not self.store.get(sid) and (
            len(records) >= 1000 or sum(r["owner"] == owner for r in records) >= 100
        ):
            raise MCPError(
                -32602, "Event subscription limit reached; remove an existing subscription."
            )
        verified_until = max(
            (
                r.get("verifiedUntil", 0)
                for r in records
                if r["owner"] == owner and r["url"] == params.delivery.url and r["secret"] == secret
            ),
            default=0,
        )
        if verified_until <= now:
            challenge = secrets.token_urlsafe(32)
            try:
                code, response = await asyncio.to_thread(
                    self.post,
                    params.delivery.url,
                    secret,
                    sid,
                    "msg_verification_" + secrets.token_hex(16),
                    {"type": "verification", "challenge": challenge},
                )
            except Exception:
                raise MCPError(
                    -32015,
                    "Callback verification failed.",
                    {"reason": "timeout_or_invalid_destination"},
                ) from None
            if not 200 <= code < 300 or not hmac.compare_digest(
                str(response.get("challenge", "")), challenge
            ):
                raise MCPError(
                    -32015, "Callback verification failed.", {"reason": "challenge_failed"}
                )
            verified_until = time.time() + 300
        now = time.time()
        expires = min(
            now + min(params.ttl_ms or MAX_LIFETIME * 1000, MAX_LIFETIME * 1000) / 1000,
            access.expires_at or now + MAX_LIFETIME,
        )
        if expires <= now + 30:
            raise MCPError(-32602, "Refresh authentication before subscribing.")
        existing = self.store.get(sid) or {}
        if existing.get("secret") and existing["secret"] != secret:
            existing["oldSecret"] = existing["secret"]
            existing["rotateUntil"] = now + 300
        record = {
            **existing,
            "id": sid,
            "owner": owner,
            "token": access.token,
            "arguments": params.arguments.model_dump(mode="json"),
            "url": params.delivery.url,
            "secret": secret,
            "expires": expires,
            "verifiedUntil": verified_until,
        }
        # Subscription methods may interleave while callback verification awaits.
        records = self.store.records()
        if not self.store.get(sid) and (
            len(records) >= 1000 or sum(r["owner"] == owner for r in records) >= 100
        ):
            raise MCPError(
                -32602, "Event subscription limit reached; remove an existing subscription."
            )
        self.store.put(record)
        return {"id": sid, "refreshBefore": iso(expires), "cursor": None, "truncated": False}

    async def unsubscribe(self, ctx: Any, params: Unsubscribe) -> dict[str, Any]:
        provider = self.provider or get_oauth_provider()
        access = get_access_token()
        if not access or not provider:
            raise MCPError(-32602, "Events require an authenticated Norman connection.")
        self.store.delete(identity(principal(access, provider), params))
        return {}

    async def tick(self) -> None:
        provider = self.provider or get_oauth_provider()
        for record in self.store.records():
            try:
                await self.process(provider, record)
            except Exception:
                # Do not log URLs, signing keys, bearer tokens or financial payloads.
                logger.warning("MCP event observation or delivery failed")

    async def process(self, provider: Any, record: dict[str, Any]) -> None:
        now = time.time()
        sid = record["id"]
        if record["expires"] <= now:
            self.store.delete(sid)
            return
        access = provider.tokens.get(record["token"]) if provider else None
        if not access or (access.expires_at and access.expires_at <= now):
            return  # No delivery until a subscription refresh supplies valid authentication.
        token = provider.get_norman_token(record["token"])
        if not token:
            return
        api = NormanAPI(authenticate_on_init=False)
        # A fresh per-subscription client; never use the shared request client or
        # current company selection. A later switch_company cannot retarget a subscription.
        api.access_token = token
        api.token_source = "env"
        api._env_company_id = record["arguments"]["company_id"]
        run = await read(api, f"assistant/workflow-runs/{record['arguments']['run_id']}/")
        if run.get("error"):
            return  # A 403, disconnect or source outage never permits delivery of cached data.
        current = self.store.get(sid)
        if (
            not current
            or current.get("token") != record["token"]
            or current.get("secret") != record["secret"]
        ):
            return
        record = current  # Preserve same-token refreshes that happened during the source read.
        if record["expires"] <= time.time() or record["token"] not in provider.tokens:
            return
        reason = run.get("blockedReason")
        if run.get("state") != "active" or reason not in REASONS:
            record.pop("pending", None)
            record.pop("fingerprint", None)
            self.store.put(record)
            return
        data = {
            "company_id": record["arguments"]["company_id"],
            "run_id": record["arguments"]["run_id"],
            "title": str(run.get("title") or "Workflow")[:200],
            "reason": reason,
            "detail": str(run.get("blockedDetail") or "")[:8000],
        }
        step = next((s.get("key") for s in run.get("steps", []) if s.get("active")), None)
        fingerprint = hashlib.sha256(
            json.dumps({"data": data, "step": step}, sort_keys=True).encode()
        ).hexdigest()
        pending = record.get("pending")
        if pending and pending["fingerprint"] != fingerprint:
            pending = None
        if not pending and record.get("fingerprint") == fingerprint:
            return
        if not pending:
            pending = {
                "event": {
                    "eventId": "evt_" + secrets.token_hex(16),
                    "name": EVENT,
                    "timestamp": run.get("updatedAt") or iso(now),
                    "data": data,
                    "cursor": None,
                },
                "fingerprint": fingerprint,
                "attempts": 0,
                "nextAttempt": now,
            }
            record["pending"] = pending
            self.store.put(record)  # Persist before sending; retry keeps the same eventId.
        if pending["nextAttempt"] > now or pending["attempts"] >= 8:
            return
        try:
            code, _ = await asyncio.to_thread(
                self.post,
                record["url"],
                record["secret"],
                sid,
                pending["event"]["eventId"],
                pending["event"],
                **(
                    {"old_secret": record["oldSecret"]}
                    if record.get("rotateUntil", 0) > now
                    else {}
                ),
            )
        except Exception:
            code = 503
        # Re-read after the await: unsubscribe or refresh must win over an in-flight delivery.
        current = self.store.get(sid)
        if (
            not current
            or current.get("token") != record["token"]
            or current.get("secret") != record["secret"]
        ):
            return
        if 200 <= code < 300:
            current["fingerprint"] = fingerprint
            current.pop("pending", None)
        elif code == 410:
            self.store.delete(sid)
            return
        elif code == 413 or (400 <= code < 500 and code not in (408, 429)):
            pending["attempts"] = 8
            current["pending"] = pending
        else:
            pending["attempts"] += 1
            pending["nextAttempt"] = now + min(30 * 2 ** pending["attempts"], 900)
            current["pending"] = pending
        self.store.put(current)

    async def run(self, interval: float = 30) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(interval)


def register_events(server: Any, service: EventService) -> None:
    lowlevel = server._lowlevel_server

    async def discover_capability(ctx: Any, call_next: Callable[[Any], Awaitable[Any]]) -> Any:
        result = await call_next(ctx)
        if ctx.method == "server/discover" and isinstance(result, dict):
            # SDK 2.2's generated wire schema strips unknown capabilities even
            # though MCP defines an open set. Add the draft capability after its sieve.
            result.setdefault("capabilities", {})["events"] = {}
        return result

    lowlevel.middleware.append(discover_capability)
    lowlevel.add_request_handler("events/list", RequestParams, service.list_events)
    lowlevel.add_request_handler("events/subscribe", Subscribe, service.subscribe)
    lowlevel.add_request_handler("events/unsubscribe", Unsubscribe, service.unsubscribe)
