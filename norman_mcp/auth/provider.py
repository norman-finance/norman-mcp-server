"""Norman OAuth Provider for MCP Server.

This provider acts as an OAuth Authorization Server that delegates
authentication to Norman's OAuth server. It:
1. Redirects users to Norman's OAuth authorize endpoint
2. Receives callbacks with authorization codes from Norman
3. Exchanges Norman codes for Norman tokens
4. Issues MCP tokens that map to Norman tokens
"""

import asyncio
import hashlib
import json as _json
import os
import logging
import time
import secrets
import threading
import httpx
from pathlib import Path
from urllib.parse import urljoin, urlencode
from typing import Any, Dict, Optional

from pydantic import AnyHttpUrl, AnyUrl
from starlette.exceptions import HTTPException

# Scopes we accept: our own read/write plus MCP-standard scopes that
# clients like OpenClaw, mcporter, etc. may request.
SUPPORTED_SCOPES = ["read", "write", "mcp:tools", "mcp:resources", "mcp:prompts"]
DEFAULT_SCOPE = " ".join(SUPPORTED_SCOPES)

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from norman_mcp.config.settings import config
from norman_mcp.security.redirects import is_allowed_redirect_uri

logger = logging.getLogger(__name__)
OAUTH_TRANSACTION_TTL = 600


class OAuthCallbackError(Exception):
    """A failed callback that can safely return to its validated client."""

    def __init__(self, redirect_url: str):
        super().__init__("OAuth authorization could not complete")
        self.redirect_url = redirect_url


def get_norman_oauth_client_id() -> str:
    """Get Norman OAuth client ID from environment."""
    client_id = os.environ.get("NORMAN_OAUTH_CLIENT_ID")
    if not client_id:
        raise ValueError("NORMAN_OAUTH_CLIENT_ID environment variable is required")
    return client_id


def get_norman_oauth_client_secret() -> str | None:
    """Get Norman OAuth client secret from environment (optional for public clients)."""
    return os.environ.get("NORMAN_OAUTH_CLIENT_SECRET")


_STATE_FILE = os.environ.get(
    "MCP_OAUTH_STATE_FILE",
    str(Path.home() / ".norman-mcp" / "oauth_state.json"),
)


class NormanOAuthProvider(OAuthAuthorizationServerProvider):
    """OAuth provider that delegates authentication to Norman's OAuth server."""

    def __init__(self, server_url: AnyHttpUrl):
        self.server_url = server_url

        self.norman_authorize_url = urljoin(config.api_base_url, "api/v1/oauth/authorize/")
        self.norman_token_url = urljoin(config.api_base_url, "api/v1/oauth/token/")
        self.callback_url = urljoin(str(server_url), "/oauth/callback")

        logger.info(f"Norman OAuth Provider initialized:")
        logger.info(f"  - Norman Authorize: {self.norman_authorize_url}")
        logger.info(f"  - Norman Token: {self.norman_token_url}")
        logger.info(f"  - MCP Callback: {self.callback_url}")

        # Storage for OAuth entities
        self.clients: Dict[str, OAuthClientInformationFull] = {}
        self.auth_codes: Dict[str, AuthorizationCode] = {}
        self.tokens: Dict[str, AccessToken] = {}
        self.refresh_tokens: Dict[str, RefreshToken] = {}

        self.state_mapping: Dict[str, Dict[str, Any]] = {}
        self.token_mapping: Dict[str, str] = {}
        # Active company per MCP token. Keyed by the caller's own MCP token, so
        # one user's selection can never be observed by another -- unlike the old
        # `NormanAPI.company_id` attribute, which was shared process-wide and was
        # both how switch_company "persisted" and how companies leaked.
        self.token_to_company_id: Dict[str, str] = {}
        # MCP access/refresh token -> grant id. Every token minted from one
        # authorization (refreshes included) shares the id, so per-connection
        # limits cannot be multiplied by refreshing.
        self.token_grants: Dict[str, str] = {}
        # Persisted records this version could not load, keyed by section. They
        # are written back verbatim so a partial load never erases them from disk.
        self._unloaded_state: Dict[str, Dict[str, Any]] = {}

        self._persist_lock = threading.Lock()
        self._refresh_locks: Dict[str, threading.Lock] = {}
        self._load_state()
        self._register_norman_client()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _state_path(self) -> Path:
        return Path(_STATE_FILE)

    def _save_state(self) -> None:
        """Persist credentials and bounded browser authorization transactions."""
        with self._persist_lock:
            try:
                path = self._state_path()
                path.parent.mkdir(parents=True, exist_ok=True)

                now = time.time()
                for key, code in list(getattr(self, "auth_codes", {}).items()):
                    if code.expires_at <= now:
                        self.auth_codes.pop(key, None)
                        self.token_mapping.pop(key, None)
                        self.token_mapping.pop(f"refresh_{key}", None)
                for key, pending in list(getattr(self, "state_mapping", {}).items()):
                    expires_at = pending.get("expires_at")
                    if expires_at is not None and (
                        not isinstance(expires_at, (int, float)) or expires_at <= now
                    ):
                        self.state_mapping.pop(key, None)

                clients_ser = {}
                for cid, c in self.clients.items():
                    # Preserve the complete SDK record, including application type,
                    # issued-at timestamps and client secret expiry across restarts.
                    clients_ser[cid] = c.model_dump(mode="json", exclude_none=True)

                refresh_ser = {}
                for rid, r in self.refresh_tokens.items():
                    refresh_ser[rid] = {
                        "token": r.token,
                        "client_id": r.client_id,
                        "scopes": r.scopes,
                        "expires_at": r.expires_at,
                    }

                tokens_ser = {}
                for tid, t in self.tokens.items():
                    tokens_ser[tid] = {
                        "token": t.token,
                        "client_id": t.client_id,
                        "scopes": t.scopes,
                        "expires_at": t.expires_at,
                    }

                unloaded = getattr(self, "_unloaded_state", {})
                data = {
                    "clients": {**unloaded.get("clients", {}), **clients_ser},
                    "refresh_tokens": {**unloaded.get("refresh_tokens", {}), **refresh_ser},
                    "tokens": {**unloaded.get("tokens", {}), **tokens_ser},
                    "token_mapping": self.token_mapping,
                    "token_to_company_id": self.token_to_company_id,
                    "token_grants": getattr(self, "token_grants", {}),
                    "auth_codes": {
                        key: code.model_dump(mode="json")
                        for key, code in getattr(self, "auth_codes", {}).items()
                        if code.expires_at > now
                    },
                    "state_mapping": {
                        key: pending
                        for key, pending in getattr(self, "state_mapping", {}).items()
                        if isinstance(pending.get("expires_at"), (int, float))
                        and pending["expires_at"] > now
                    },
                }

                tmp = path.with_suffix(".tmp")
                tmp.write_text(_json.dumps(data, indent=2))
                tmp.chmod(0o600)
                tmp.replace(path)
                logger.debug("OAuth state persisted to %s", path)
            except Exception:
                logger.warning("Failed to persist OAuth state", exc_info=True)

    def _load_state(self) -> None:
        """Load persisted state from disk on startup.

        Every record is restored on its own. One record this version cannot read
        (e.g. an empty client_id that SDK 1 auto-registered and SDK 2 rejects)
        must not abort the rest: the next save would otherwise rewrite the only
        state file without the other clients, tokens and Norman mappings.
        Unreadable records are kept verbatim and written back on save.
        """
        path = self._state_path()
        if not path.exists():
            logger.info("No persisted OAuth state found at %s", path)
            return
        try:
            data = _json.loads(path.read_text())
            if not isinstance(data, dict):
                raise ValueError("OAuth state is not a JSON object")
        except Exception:
            # Keep the unreadable file: the next save replaces it.
            backup = path.with_name(f"{path.name}.unreadable-{int(time.time())}")
            try:
                backup.write_bytes(path.read_bytes())
            except OSError:
                logger.error("Could not back up unreadable OAuth state %s", path, exc_info=True)
            logger.error("Failed to read OAuth state from %s; kept a copy at %s", path, backup, exc_info=True)
            return

        now = time.time()
        migrated = False
        skipped = 0

        def section(name: str) -> Dict[str, Any]:
            value = data.get(name) or {}
            return value if isinstance(value, dict) else {}

        def keep_unloaded(name: str, key: str, raw: Any) -> None:
            nonlocal skipped
            skipped += 1
            self.__dict__.setdefault("_unloaded_state", {}).setdefault(name, {})[key] = raw
            logger.warning("Skipping unreadable OAuth %s record %r", name, str(key)[:12], exc_info=True)

        for cid, c in section("clients").items():
            try:
                # Migration: an older version of `get_client` auto-registered
                # public clients with a random `client_secret` while setting
                # `token_endpoint_auth_method="none"`. That combination makes
                # every /token call fail with "Client secret is required"
                # (see ClientAuthenticator). Strip the stored secret from
                # method=none clients so they behave as public clients again.
                auth_method = c.get("token_endpoint_auth_method", "none")
                stored_secret = c.get("client_secret")
                if auth_method == "none" and stored_secret:
                    logger.info("Migrating public client %s... — dropping stale client_secret", cid[:12])
                    stored_secret = None
                    migrated = True
                self.clients[cid] = OAuthClientInformationFull.model_validate(
                    {
                        # Legacy state omitted these fields; keep its established defaults.
                        "redirect_uris": [],
                        "token_endpoint_auth_method": "none",
                        "grant_types": ["authorization_code", "refresh_token"],
                        "response_types": ["code"],
                        "scope": DEFAULT_SCOPE,
                        **c,
                        "client_secret": stored_secret,
                    }
                )
            except Exception:
                keep_unloaded("clients", cid, c)

        for rid, r in section("refresh_tokens").items():
            try:
                if r.get("expires_at", 0) > now:
                    self.refresh_tokens[rid] = RefreshToken(
                        token=r["token"],
                        client_id=r["client_id"],
                        scopes=r.get("scopes", []),
                        expires_at=r.get("expires_at", 0),
                    )
            except Exception:
                keep_unloaded("refresh_tokens", rid, r)

        for tid, t in section("tokens").items():
            try:
                if t.get("expires_at", 0) > now:
                    self.tokens[tid] = AccessToken(
                        token=t["token"],
                        client_id=t["client_id"],
                        scopes=t.get("scopes", []),
                        expires_at=t.get("expires_at", 0),
                    )
            except Exception:
                keep_unloaded("tokens", tid, t)

        for key, raw in section("auth_codes").items():
            try:
                code = AuthorizationCode.model_validate(raw)
                if code.expires_at > now:
                    self.auth_codes[key] = code
            except Exception:
                # Codes are short-lived. An unreadable code must never become
                # redeemable or prevent other connections from loading.
                logger.warning("Ignoring unreadable OAuth authorization code")

        for key, pending in section("state_mapping").items():
            if (
                isinstance(pending, dict)
                and isinstance(pending.get("expires_at"), (int, float))
                and pending["expires_at"] > now
            ):
                self.state_mapping[key] = pending

        self.token_mapping = section("token_mapping")
        for key in section("auth_codes"):
            if (
                key not in self.auth_codes
                and key not in self.tokens
                and key not in self.refresh_tokens
            ):
                if key in self.token_mapping or f"refresh_{key}" in self.token_mapping:
                    migrated = True
                self.token_mapping.pop(key, None)
                self.token_mapping.pop(f"refresh_{key}", None)
        self.token_to_company_id = section("token_to_company_id")
        live = set(self.tokens) | set(self.refresh_tokens)
        self.token_grants = {t: g for t, g in section("token_grants").items() if t in live}
        logger.info(
            "Restored OAuth state: %d clients, %d refresh tokens, %d access tokens (%d unreadable kept)",
            len(self.clients),
            len(self.refresh_tokens),
            len(self.tokens),
            skipped,
        )
        if migrated:
            # Persist public-client migrations and expired code cleanup.
            self._save_state()

    def _register_norman_client(self) -> None:
        """Pre-register the Norman OAuth client from environment variables."""
        try:
            client_id = get_norman_oauth_client_id()
            client_secret = get_norman_oauth_client_secret()

            # Common redirect URIs for MCP clients (Inspector, etc.)
            redirect_uris = [
                "http://localhost:3000/callback",
                "http://localhost:5173/oauth/callback",
                "http://localhost:6274/oauth/callback",
                "http://localhost:6274/oauth/callback/debug",
                "http://127.0.0.1:6274/oauth/callback",
                "http://127.0.0.1:6274/oauth/callback/debug",
                "https://mcp.norman.finance/oauth/callback",
                "https://mcp.norman.finance/callback",
                "https://chatgpt.com/connector_platform_oauth_redirect"
            ]

            # Register as public client (no client_secret) for MCP clients like Inspector
            # The client_secret is only used for MCP server -> Norman communication
            client = OAuthClientInformationFull(
                client_id=client_id,
                client_name="Norman MCP Client",
                client_secret=None,  # Public client - no secret, uses PKCE
                redirect_uris=redirect_uris,  # type: ignore
                token_endpoint_auth_method="none",
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                scope=DEFAULT_SCOPE,
            )
            self.clients[client_id] = client
            logger.info(f"Pre-registered Norman OAuth client: {client_id[:20]}...")

        except ValueError as e:
            logger.warning(f"Norman OAuth client not pre-registered: {e}")

    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        """Get client by ID. Auto-registers unknown clients for development."""
        client = self.clients.get(client_id)

        if not client:
            logger.info(f"Auto-registering client: {client_id}")
            # Default redirect URIs for common development scenarios
            # Using strings directly - Pydantic will validate and convert
            default_redirect_uris = [
                "http://localhost:3000/callback",
                "http://localhost:5173/oauth/callback",
                "http://localhost:6274/oauth/callback",
                "http://localhost:6274/oauth/callback/debug",  # MCP Inspector debug mode
                "http://127.0.0.1:6274/oauth/callback",
                "http://127.0.0.1:6274/oauth/callback/debug",
                "https://mcp.norman.finance/oauth/callback",
                "https://mcp.norman.finance/callback",
                "https://chatgpt.com/connector_platform_oauth_redirect"
            ]
            # Public client: no client_secret, authenticated via PKCE.
            # Setting a random secret here is a trap — the MCP SDK's
            # ClientAuthenticator requires `request_client_secret` whenever
            # `client.client_secret` is truthy, regardless of
            # `token_endpoint_auth_method="none"`, so any public-client
            # /token call would 401 with "Client secret is required".
            client = OAuthClientInformationFull(
                client_id=client_id,
                client_name=f"Client {client_id[:8]}",
                client_secret=None,
                redirect_uris=default_redirect_uris,  # type: ignore
                token_endpoint_auth_method="none",
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                scope=DEFAULT_SCOPE,
            )
            self.clients[client_id] = client
            logger.debug(f"Registered redirect_uris: {[str(u) for u in client.redirect_uris]}")
            self._save_state()

        return client

    def add_redirect_uri(self, client_id: str, redirect_uri: str) -> None:
        """Add a redirect URI to an existing client (for dynamic registration)."""
        if not is_allowed_redirect_uri(redirect_uri):
            logger.warning(f"Refusing to add disallowed redirect URI for {client_id[:8]}: {redirect_uri}")
            return
        client = self.clients.get(client_id)
        if client and redirect_uri not in [str(uri) for uri in client.redirect_uris]:
            # Create new client with updated redirect URIs
            new_uris = list(client.redirect_uris) + [AnyUrl(redirect_uri)]
            # Copy rather than rebuild: a rebuild from a field subset silently
            # dropped the secret expiry, issue time and application type.
            self.clients[client_id] = client.model_copy(update={"redirect_uris": new_uris})
            logger.info(f"Added redirect URI for client {client_id[:8]}: {redirect_uri}")
            self._save_state()

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Register a new OAuth client via Dynamic Client Registration.

        Open DCR is intentional (MCP clients self-register), so preserve the
        metadata they submit and return a conforming RFC 7591 success response.
        Redirect trust is enforced authoritatively on every /authorize request
        via validate_redirect_uri, before an authorization code can be issued.
        """
        updates: Dict[str, Any] = {}
        if not client_info.scope or not any(s in client_info.scope for s in SUPPORTED_SCOPES):
            updates.update(
                token_endpoint_auth_method=client_info.token_endpoint_auth_method or "none",
                response_types=client_info.response_types or ["code"],
                scope=DEFAULT_SCOPE,
            )
        # Every authorization-code grant here also issues a refresh token. SDK 1
        # rejected registrations without refresh_token; SDK 2 accepts them, and
        # the client would then hold refresh tokens /token refuses to redeem.
        grant_types = list(client_info.grant_types or ["authorization_code"])
        if "authorization_code" in grant_types and "refresh_token" not in grant_types:
            grant_types.append("refresh_token")
        if grant_types != list(client_info.grant_types or []):
            updates["grant_types"] = grant_types
        # In place: the SDK answers the registration with this same object, so the
        # client sees exactly the grants and scope that are stored.
        for field, value in updates.items():
            setattr(client_info, field, value)
        self.clients[client_info.client_id] = client_info
        logger.info(f"Registered client: {client_info.client_id} with scope: {client_info.scope}")
        self._save_state()

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Redirect to Norman's OAuth authorize endpoint."""
        # Each browser attempt gets its own upstream state. Hosts can reuse
        # their state during retries; that must not overwrite another PKCE
        # challenge or send a callback to a different client.
        state = secrets.token_urlsafe(32)

        logger.info(f"Authorization request from client: {client.client_id[:8]}...")

        # Dynamically add the redirect URI if not already registered
        redirect_uri_str = str(params.redirect_uri)
        if redirect_uri_str not in [str(uri) for uri in client.redirect_uris]:
            self.add_redirect_uri(client.client_id, redirect_uri_str)

        # Store state mapping for callback
        self.state_mapping[state] = {
            "client_state": params.state,
            "expires_at": time.time() + OAUTH_TRANSACTION_TTL,
            "redirect_uri": redirect_uri_str,
            "code_challenge": params.code_challenge,
            "code_challenge_method": "S256",  # PKCE always uses S256
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "client_id": client.client_id,
            "scopes": list(params.scopes) if params.scopes else SUPPORTED_SCOPES,
        }
        self._save_state()

        # Build Norman OAuth authorization URL
        oauth_params = {
            "response_type": "code",
            "client_id": get_norman_oauth_client_id(),
            "redirect_uri": self.callback_url,
            "state": state,
            "scope": "read write",
        }

        auth_url = f"{self.norman_authorize_url}?{urlencode(oauth_params)}"
        logger.info("OAuth browser authorization started: attempt=%s", self._attempt_id(state))

        return auth_url

    @staticmethod
    def _attempt_id(state: str) -> str:
        """Correlate browser stages without logging the bearer state value."""
        return hashlib.sha256(state.encode()).hexdigest()[:12]

    def _consume_callback_state(self, state: str | None) -> Dict[str, Any] | None:
        if not state:
            return None
        with self._persist_lock:
            pending = self.state_mapping.pop(state, None)
        if pending is None:
            return None
        self._save_state()
        expires_at = pending.get("expires_at")
        if expires_at is not None and (
            not isinstance(expires_at, (int, float)) or expires_at <= time.time()
        ):
            return None
        redirect_uri = pending.get("redirect_uri")
        client = self.clients.get(pending.get("client_id"))
        if (
            not isinstance(redirect_uri, str)
            or not is_allowed_redirect_uri(redirect_uri)
            or client is None
            or redirect_uri not in [str(uri) for uri in client.redirect_uris]
        ):
            return None
        # Old in-memory transactions had the host state as their lookup key.
        if "client_state" not in pending:
            pending["client_state"] = state
        return pending

    @staticmethod
    def _callback_error_url(pending: Dict[str, Any], error: str) -> str:
        descriptions = {
            "access_denied": "Norman authorization was not granted. Please reconnect.",
            "temporarily_unavailable": "Norman authorization is temporarily unavailable. Please retry.",
            "invalid_request": "Norman authorization could not complete. Please reconnect.",
            "server_error": "Norman authorization could not complete. Please reconnect.",
        }
        if error not in descriptions:
            error = "server_error"
        return construct_redirect_uri(
            pending["redirect_uri"],
            error=error,
            error_description=descriptions[error],
            state=pending.get("client_state"),
        )

    def callback_error_redirect(self, state: str | None, error: str) -> str | None:
        """Return a failure only to the client registered for this attempt."""
        pending = self._consume_callback_state(state)
        if pending is None:
            return None
        logger.info("OAuth browser authorization failed: attempt=%s", self._attempt_id(state))
        return self._callback_error_url(pending, error)

    async def handle_oauth_callback(self, code: str, state: str) -> str:
        """Handle OAuth callback from Norman.
        
        Args:
            code: Authorization code from Norman
            state: State parameter to match with original request
            
        Returns:
            Redirect URL to the MCP client with new authorization code
        """
        state_data = self._consume_callback_state(state)
        if not state_data:
            raise HTTPException(400, "Invalid or expired state parameter")

        logger.info("OAuth callback received: attempt=%s", self._attempt_id(state))

        # Exchange Norman's authorization code for tokens
        token_payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.callback_url,
            "client_id": get_norman_oauth_client_id(),
        }

        # Add client secret if configured
        client_secret = get_norman_oauth_client_secret()
        if client_secret:
            token_payload["client_secret"] = client_secret

        try:
            async with httpx.AsyncClient() as http_client:
                response = await http_client.post(
                    self.norman_token_url,
                    data=token_payload,
                    timeout=config.NORMAN_API_TIMEOUT
                )

                if response.status_code != 200:
                    logger.warning(
                        "Norman authorization code exchange rejected: status=%s",
                        response.status_code,
                    )
                    error = (
                        "temporarily_unavailable"
                        if response.status_code == 429 or response.status_code >= 500
                        else "server_error"
                    )
                    raise OAuthCallbackError(self._callback_error_url(state_data, error))

                auth_data = response.json()
                if not isinstance(auth_data, dict):
                    raise ValueError("Invalid Norman token response")
                norman_token = auth_data.get("access_token")
                norman_refresh = auth_data.get("refresh_token")

                if not isinstance(norman_token, str) or not norman_token:
                    raise ValueError("Invalid Norman access token")
                if norman_refresh is not None and (
                    not isinstance(norman_refresh, str) or not norman_refresh
                ):
                    raise ValueError("Invalid Norman refresh token")

                # Generate MCP authorization code for the client
                mcp_code = f"mcp_{secrets.token_hex(16)}"
                redirect_uri = state_data["redirect_uri"]
                client_id = state_data["client_id"]
                scopes = state_data["scopes"]
                code_challenge = state_data["code_challenge"]

                # Create and store MCP authorization code
                auth_code = AuthorizationCode(
                    code=mcp_code,
                    client_id=client_id,
                    redirect_uri=AnyUrl(redirect_uri),
                    redirect_uri_provided_explicitly=state_data["redirect_uri_provided_explicitly"],
                    expires_at=time.time() + OAUTH_TRANSACTION_TTL,
                    scopes=scopes,
                    code_challenge=code_challenge,
                )

                self.auth_codes[mcp_code] = auth_code
                self.token_mapping[mcp_code] = norman_token

                # Store refresh token if available
                if norman_refresh:
                    self.token_mapping[f"refresh_{mcp_code}"] = norman_refresh

                # Redirect client with MCP authorization code
                redirect_url = construct_redirect_uri(
                    redirect_uri, code=mcp_code, state=state_data.get("client_state")
                )
                logger.info(
                    "OAuth callback returning to client: attempt=%s", self._attempt_id(state)
                )

                self._save_state()
                return redirect_url

        except httpx.RequestError:
            logger.warning("Norman authorization code exchange temporarily unavailable")
            raise OAuthCallbackError(
                self._callback_error_url(state_data, "temporarily_unavailable")
            ) from None
        except (ValueError, TypeError):
            logger.warning("Invalid Norman authorization code exchange response")
            raise OAuthCallbackError(self._callback_error_url(state_data, "server_error")) from None

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Optional[AuthorizationCode]:
        """Load an authorization code."""
        code = self.auth_codes.get(authorization_code)
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """Exchange authorization code for MCP tokens."""

        # Get the Norman token associated with this code
        norman_token = self.token_mapping.get(authorization_code.code)
        if not norman_token:
            raise ValueError("Norman token not found for authorization code")

        # Generate MCP access token
        mcp_token = f"mcp_{secrets.token_hex(32)}"

        # Store MCP token
        self.tokens[mcp_token] = AccessToken(
            token=mcp_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time()) + 86400,  # 24 hours
        )

        # Map MCP token to Norman token
        self.token_mapping[mcp_token] = norman_token
        grant = f"grant_{secrets.token_hex(16)}"
        self.token_grants[mcp_token] = grant

        # Check for refresh token
        norman_refresh = self.token_mapping.get(f"refresh_{authorization_code.code}")
        refresh_token_id = None

        if norman_refresh:
            refresh_token_id = f"mcp_refresh_{secrets.token_hex(16)}"
            self.refresh_tokens[refresh_token_id] = RefreshToken(
                token=refresh_token_id,
                client_id=client.client_id,
                scopes=authorization_code.scopes,
                expires_at=int(time.time()) + 30 * 86400,  # 30 days
            )
            self.token_mapping[refresh_token_id] = norman_refresh
            self.token_grants[refresh_token_id] = grant
            # Also index by access token so we can transparently refresh the
            # Norman access token when it expires mid-session (see
            # NormanAPI._make_request 401 handler).
            self.token_mapping[f"refresh_for_{mcp_token}"] = norman_refresh

        # Clean up used authorization code
        del self.auth_codes[authorization_code.code]
        if authorization_code.code in self.token_mapping:
            del self.token_mapping[authorization_code.code]
        if f"refresh_{authorization_code.code}" in self.token_mapping:
            del self.token_mapping[f"refresh_{authorization_code.code}"]

        logger.info("OAuth client token issued")
        self._save_state()

        return OAuthToken(
            access_token=mcp_token,
            token_type="bearer",
            expires_in=86400,
            scope=" ".join(authorization_code.scopes),
            refresh_token=refresh_token_id,
        )

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        """Load and validate an access token."""
        access_token = self.tokens.get(token)

        if not access_token:
            return None

        if access_token.expires_at and access_token.expires_at < time.time():
            del self.tokens[token]
            if token in self.token_mapping:
                del self.token_mapping[token]
            if token in self.token_to_company_id:
                del self.token_to_company_id[token]
            self._save_state()
            return None

        # Seed the per-request context from THIS caller's own token. Both values
        # are request-scoped ContextVars (see norman_mcp.context) -- never write
        # caller identity anywhere process-wide.
        from norman_mcp.context import set_api_company_id, set_api_token

        norman_token = self.token_mapping.get(token)
        if norman_token:
            set_api_token(norman_token)

        # Restore the company this caller last selected via switch_company. Keyed
        # by their MCP token, so it cannot be observed by anyone else.
        company_id = self.token_to_company_id.get(token)
        if company_id:
            set_api_company_id(company_id)

        return access_token

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> Optional[RefreshToken]:
        """Load a refresh token."""
        return self.refresh_tokens.get(refresh_token)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Refresh off the event loop, sharing the lock with transparent refresh."""
        return await asyncio.to_thread(
            self._exchange_refresh_token_sync, client, refresh_token, scopes
        )

    def _exchange_refresh_token_sync(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        with self._refresh_lock_for(refresh_token.token):
            # Recheck after waiting: the client may have revoked it meanwhile.
            if refresh_token.token not in self.refresh_tokens:
                raise TokenError("invalid_grant", "Refresh token no longer available")
            norman_token, norman_refresh = self._refresh_norman_credentials(refresh_token.token)
            # Company selection still belongs to the previous MCP access token;
            # this refresh fix does not migrate that existing per-token state.
            new_mcp_token = f"mcp_{secrets.token_hex(32)}"
            with self._persist_lock:
                if refresh_token.token not in self.refresh_tokens:
                    raise TokenError("invalid_grant", "Refresh token no longer available")
                self.tokens[new_mcp_token] = AccessToken(
                    token=new_mcp_token,
                    client_id=client.client_id,
                    scopes=scopes or refresh_token.scopes,
                    expires_at=int(time.time()) + 86400,
                )
                self.token_mapping[new_mcp_token] = norman_token
                self.token_mapping[f"refresh_for_{new_mcp_token}"] = norman_refresh
                # The refresh token is not rotated, so it identifies the grant even
                # for grants issued before grant ids were recorded.
                self.token_grants[new_mcp_token] = self.token_grants.get(
                    refresh_token.token, refresh_token.token
                )
            self._save_state()

            return OAuthToken(
                access_token=new_mcp_token,
                token_type="bearer",
                expires_in=86400,
                scope=" ".join(scopes or refresh_token.scopes),
                refresh_token=refresh_token.token,
            )

    def grant_for_token(self, token: str) -> str:
        """The authorization a token belongs to; unknown tokens stand for themselves."""
        return getattr(self, "token_grants", {}).get(token, token)

    async def revoke_token(self, token: str, token_type_hint: Optional[str] = None) -> None:
        """Invalidate one connection, including its still-live access aliases."""
        await asyncio.to_thread(self._invalidate_grant, token)

    def _invalidate_grant(self, mapping_key: str) -> None:
        # A client_id is shared by independent users. Invalidate only a stable
        # grant id or aliases of this exact upstream refresh token; legacy
        # connections did not yet persist grant ids.
        with self._persist_lock:
            access_key = mapping_key.removeprefix("refresh_for_")
            grant = getattr(self, "token_grants", {}).get(access_key)
            upstream_refresh = self.token_mapping.get(
                mapping_key
                if mapping_key in self.refresh_tokens or mapping_key.startswith("refresh_for_")
                else f"refresh_for_{mapping_key}"
            )
            members = {
                key
                for key in set(self.tokens) | set(self.refresh_tokens)
                if key == access_key
                or (grant is not None and getattr(self, "token_grants", {}).get(key) == grant)
                or (
                    upstream_refresh is not None
                    and self.token_mapping.get(
                        key if key in self.refresh_tokens else f"refresh_for_{key}"
                    )
                    == upstream_refresh
                )
            }
            for key in members:
                self.tokens.pop(key, None)
                self.refresh_tokens.pop(key, None)
                self.token_mapping.pop(key, None)
                self.token_mapping.pop(f"refresh_for_{key}", None)
                self.token_to_company_id.pop(key, None)
                getattr(self, "token_grants", {}).pop(key, None)
        if members:
            self._save_state()
            logger.info("OAuth connection invalidated: aliases=%s", len(members))

    def get_norman_token(self, mcp_token: str) -> Optional[str]:
        """Get the Norman API token for a given MCP token."""
        return self.token_mapping.get(mcp_token)

    def get_company_for_token(self, mcp_token: str) -> Optional[str]:
        """Get the company this MCP token last selected, if any."""
        return self.token_to_company_id.get(mcp_token)

    def set_company_for_token(self, mcp_token: str, company_id: Optional[str]) -> None:
        """Remember the active company for one MCP token.

        Keyed by the caller's own token, so a selection is visible only to the
        caller -- this is what lets switch_company outlive a single request
        without reintroducing shared mutable company state.

        The caller's access to `company_id` must already have been verified;
        this only persists the choice. See tools/tax_advisor.switch_company,
        which confirms the company is reachable before calling this.
        """
        if not mcp_token:
            return
        if company_id:
            if self.token_to_company_id.get(mcp_token) == company_id:
                return
            self.token_to_company_id[mcp_token] = company_id
        elif mcp_token in self.token_to_company_id:
            del self.token_to_company_id[mcp_token]
        else:
            return
        self._save_state()

    def refresh_norman_token_sync(self, mcp_token: str) -> Optional[str]:
        """Refresh the Norman access token for an MCP access token (sync).

        Called from NormanAPI._make_request (which uses `requests`) when
        Norman returns 401 mid-session: we swap in a fresh Norman access
        token so the MCP client does not need to reconnect. Returns the
        new Norman access token, or None if refresh is impossible
        (no stored refresh token, or refresh call failed).
        """
        previous_token = self.token_mapping.get(mcp_token)
        with self._refresh_lock_for(f"refresh_for_{mcp_token}"):
            current_token = self.token_mapping.get(mcp_token)
            if current_token and current_token != previous_token:
                # Another request already refreshed while this one was waiting.
                return current_token
            try:
                norman_token, _ = self._refresh_norman_credentials(f"refresh_for_{mcp_token}")
            except (TokenError, HTTPException) as exc:
                # Never log response bodies or request payloads containing tokens.
                error_code = exc.error if isinstance(exc, TokenError) else exc.status_code
                logger.warning("Transparent Norman refresh failed: %s", error_code)
                return None
            self._save_state()
            return norman_token

    def _refresh_lock_for(self, mapping_key: str):
        """Use the stable MCP refresh handle as the lock identity for a grant.

        Existing state already links both refresh paths by the exact opaque
        upstream refresh token. Never group by client_id: one MCP client can
        belong to many independent Norman accounts.
        """
        with self._persist_lock:
            norman_refresh = self.token_mapping.get(mapping_key)
            lock_key = mapping_key
            if norman_refresh:
                lock_key = next(
                    (
                        key
                        for key in list(self.refresh_tokens)
                        if self.token_mapping.get(key) == norman_refresh
                    ),
                    mapping_key,
                )
            return self._refresh_locks.setdefault(lock_key, threading.Lock())

    def _refresh_norman_credentials(self, mapping_key: str) -> tuple[str, str]:
        """Rotate all aliases of one upstream grant; caller holds its refresh lock."""
        import requests as _requests

        norman_refresh = self.token_mapping.get(mapping_key)
        if not norman_refresh:
            raise TokenError("invalid_grant", "Norman refresh token no longer available")
        token_payload = {
            "grant_type": "refresh_token",
            "refresh_token": norman_refresh,
            "client_id": get_norman_oauth_client_id(),
        }
        client_secret = get_norman_oauth_client_secret()
        if client_secret:
            token_payload["client_secret"] = client_secret

        try:
            response = _requests.post(
                self.norman_token_url,
                data=token_payload,
                timeout=config.NORMAN_API_TIMEOUT,
            )
        except _requests.exceptions.RequestException:
            raise HTTPException(
                503,
                "Norman authorization service temporarily unavailable",
                headers={"Retry-After": "5"},
            ) from None

        if response.status_code == 429 or response.status_code >= 500:
            raise HTTPException(
                503,
                "Norman authorization service temporarily unavailable",
                headers={"Retry-After": "5"},
            )
        try:
            data = response.json()
        except ValueError:
            raise HTTPException(502, "Invalid response from Norman authorization service") from None
        if not isinstance(data, dict):
            raise HTTPException(502, "Invalid response from Norman authorization service")
        if response.status_code != 200:
            if response.status_code == 400 and data.get("error") == "invalid_grant":
                self._invalidate_grant(mapping_key)
                raise TokenError("invalid_grant", "Norman authorization expired; please reconnect")
            raise HTTPException(502, "Norman authorization service rejected the refresh request")
        new_norman_token = data.get("access_token")
        new_norman_refresh = data.get("refresh_token")
        if new_norman_refresh is None:
            new_norman_refresh = norman_refresh
        if (
            not isinstance(new_norman_token, str)
            or not new_norman_token
            or not isinstance(new_norman_refresh, str)
            or not new_norman_refresh
        ):
            raise HTTPException(502, "Invalid response from Norman authorization service")

        # Keep the persisted format compatible with existing sessions. Update
        # both the client-facing refresh handle and every still-live MCP access
        # token that shares this exact upstream grant, in either refresh path.
        with self._persist_lock:
            # Revocation can arrive while the upstream network call is in
            # flight. A successful response must never resurrect its grant.
            access_key = mapping_key.removeprefix("refresh_for_")
            if (
                mapping_key not in self.token_mapping
                or (mapping_key.startswith("refresh_for_") and access_key not in self.tokens)
                or (
                    not mapping_key.startswith("refresh_for_")
                    and mapping_key not in self.refresh_tokens
                )
            ):
                raise TokenError("invalid_grant", "Norman authorization no longer available")
            for key, value in list(self.token_mapping.items()):
                if value != norman_refresh:
                    continue
                if key in self.refresh_tokens:
                    self.token_mapping[key] = new_norman_refresh
                elif key.startswith("refresh_for_"):
                    self.token_mapping[key] = new_norman_refresh
                    access_key = key.removeprefix("refresh_for_")
                    if access_key in self.tokens:
                        self.token_mapping[access_key] = new_norman_token
        return new_norman_token, new_norman_refresh
