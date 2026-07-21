"""Norman OAuth Provider for MCP Server.

This provider acts as an OAuth Authorization Server that delegates
authentication to Norman's OAuth server. It:
1. Redirects users to Norman's OAuth authorize endpoint
2. Receives callbacks with authorization codes from Norman
3. Exchanges Norman codes for Norman tokens
4. Issues MCP tokens that map to Norman tokens
"""

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
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from norman_mcp.config.settings import config

logger = logging.getLogger(__name__)


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
        # Per-MCP-token company id cache. Populated by the API client the
        # first time a company id is fetched for a user, and consulted by
        # load_access_token to seed the per-request ContextVar so that
        # subsequent requests see the company id without a refetch. Also
        # updated by switch_company to persist user selections across
        # requests (ContextVars are per-request only).
        self.token_to_company_id: Dict[str, str] = {}

        self._persist_lock = threading.Lock()
        self._load_state()
        self._register_norman_client()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _state_path(self) -> Path:
        return Path(_STATE_FILE)

    def _save_state(self) -> None:
        """Persist clients, refresh tokens, and token mappings to disk."""
        with self._persist_lock:
            try:
                path = self._state_path()
                path.parent.mkdir(parents=True, exist_ok=True)

                clients_ser = {}
                for cid, c in self.clients.items():
                    clients_ser[cid] = {
                        "client_id": c.client_id,
                        "client_name": c.client_name,
                        "client_secret": c.client_secret,
                        "redirect_uris": [str(u) for u in c.redirect_uris],
                        "token_endpoint_auth_method": c.token_endpoint_auth_method,
                        "grant_types": c.grant_types,
                        "response_types": c.response_types,
                        "scope": c.scope,
                    }

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

                data = {
                    "clients": clients_ser,
                    "refresh_tokens": refresh_ser,
                    "tokens": tokens_ser,
                    "token_mapping": self.token_mapping,
                    "token_to_company_id": self.token_to_company_id,
                }

                tmp = path.with_suffix(".tmp")
                tmp.write_text(_json.dumps(data, indent=2))
                tmp.replace(path)
                logger.debug("OAuth state persisted to %s", path)
            except Exception:
                logger.warning("Failed to persist OAuth state", exc_info=True)

    def _load_state(self) -> None:
        """Load persisted state from disk on startup."""
        path = self._state_path()
        if not path.exists():
            logger.info("No persisted OAuth state found at %s", path)
            return
        try:
            data = _json.loads(path.read_text())
            now = time.time()

            migrated = False
            for cid, c in data.get("clients", {}).items():
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
                self.clients[cid] = OAuthClientInformationFull(
                    client_id=c["client_id"],
                    client_name=c.get("client_name"),
                    client_secret=stored_secret,
                    redirect_uris=c.get("redirect_uris", []),
                    token_endpoint_auth_method=auth_method,
                    grant_types=c.get("grant_types", ["authorization_code", "refresh_token"]),
                    response_types=c.get("response_types", ["code"]),
                    scope=c.get("scope", DEFAULT_SCOPE),
                )

            for rid, r in data.get("refresh_tokens", {}).items():
                if r.get("expires_at", 0) > now:
                    self.refresh_tokens[rid] = RefreshToken(
                        token=r["token"],
                        client_id=r["client_id"],
                        scopes=r.get("scopes", []),
                        expires_at=r.get("expires_at", 0),
                    )

            for tid, t in data.get("tokens", {}).items():
                if t.get("expires_at", 0) > now:
                    self.tokens[tid] = AccessToken(
                        token=t["token"],
                        client_id=t["client_id"],
                        scopes=t.get("scopes", []),
                        expires_at=t.get("expires_at", 0),
                    )

            self.token_mapping = data.get("token_mapping", {})
            self.token_to_company_id = data.get("token_to_company_id", {})
            logger.info(
                "Restored OAuth state: %d clients, %d refresh tokens, %d access tokens",
                len(self.clients), len(self.refresh_tokens), len(self.tokens),
            )
            if migrated:
                # Persist the scrubbed secrets so the next restart doesn't log the migration again.
                self._save_state()
        except Exception:
            logger.warning("Failed to load OAuth state from %s", path, exc_info=True)

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
        client = self.clients.get(client_id)
        if client and redirect_uri not in [str(uri) for uri in client.redirect_uris]:
            # Create new client with updated redirect URIs
            new_uris = list(client.redirect_uris) + [AnyUrl(redirect_uri)]
            self.clients[client_id] = OAuthClientInformationFull(
                client_id=client.client_id,
                client_name=client.client_name,
                client_secret=client.client_secret,
                redirect_uris=new_uris,
                token_endpoint_auth_method=client.token_endpoint_auth_method,
                grant_types=client.grant_types,
                response_types=client.response_types,
                scope=client.scope,
            )
            logger.info(f"Added redirect URI for client {client_id[:8]}: {redirect_uri}")
            self._save_state()

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Register a new OAuth client via Dynamic Client Registration."""
        if not client_info.scope or not any(s in client_info.scope for s in SUPPORTED_SCOPES):
            client_info = OAuthClientInformationFull(
                client_id=client_info.client_id,
                client_name=client_info.client_name,
                client_secret=client_info.client_secret,
                redirect_uris=client_info.redirect_uris,
                token_endpoint_auth_method=client_info.token_endpoint_auth_method or "none",
                grant_types=client_info.grant_types or ["authorization_code", "refresh_token"],
                response_types=client_info.response_types or ["code"],
                scope=DEFAULT_SCOPE,
            )
        self.clients[client_info.client_id] = client_info
        logger.info(f"Registered client: {client_info.client_id} with scope: {client_info.scope}")
        self._save_state()

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Redirect to Norman's OAuth authorize endpoint."""
        state = params.state or secrets.token_hex(16)
        
        logger.info(f"Authorization request from client: {client.client_id[:8]}...")
        
        # Dynamically add the redirect URI if not already registered
        redirect_uri_str = str(params.redirect_uri)
        if redirect_uri_str not in [str(uri) for uri in client.redirect_uris]:
            self.add_redirect_uri(client.client_id, redirect_uri_str)
        
        # Store state mapping for callback
        self.state_mapping[state] = {
            "redirect_uri": redirect_uri_str,
            "code_challenge": params.code_challenge,
            "code_challenge_method": "S256",  # PKCE always uses S256
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "client_id": client.client_id,
            "scopes": list(params.scopes) if params.scopes else SUPPORTED_SCOPES,
        }
        
        # Build Norman OAuth authorization URL
        oauth_params = {
            "response_type": "code",
            "client_id": get_norman_oauth_client_id(),
            "redirect_uri": self.callback_url,
            "state": state,
            "scope": "read write",
        }
        
        auth_url = f"{self.norman_authorize_url}?{urlencode(oauth_params)}"
        logger.info(f"Redirecting to Norman OAuth: {auth_url}")
        
        return auth_url

    async def handle_oauth_callback(self, code: str, state: str) -> str:
        """Handle OAuth callback from Norman.
        
        Args:
            code: Authorization code from Norman
            state: State parameter to match with original request
            
        Returns:
            Redirect URL to the MCP client with new authorization code
        """
        state_data = self.state_mapping.get(state)
        if not state_data:
            raise HTTPException(400, "Invalid or expired state parameter")
        
        logger.info(f"OAuth callback received, exchanging code with Norman...")
        
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
                    logger.error(f"Norman token exchange failed: {response.status_code}")
                    logger.error(f"Response: {response.text}")
                    raise HTTPException(400, "Failed to exchange authorization code")
                
                auth_data = response.json()
                norman_token = auth_data.get("access_token")
                norman_refresh = auth_data.get("refresh_token")
                
                if not norman_token:
                    raise HTTPException(400, "No access token in Norman response")

                # Note: per-request ContextVars are seeded by load_access_token
                # on each incoming request, so we don't need to set it here.
                logger.info(f"✅ Norman token obtained: {norman_token[:15]}...")
                
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
                    expires_at=time.time() + 600,  # 10 minutes
                    scopes=scopes,
                    code_challenge=code_challenge,
                )
                
                self.auth_codes[mcp_code] = auth_code
                self.token_mapping[mcp_code] = norman_token
                
                # Store refresh token if available
                if norman_refresh:
                    self.token_mapping[f"refresh_{mcp_code}"] = norman_refresh
                
                # Clean up state
                del self.state_mapping[state]
                
                # Redirect client with MCP authorization code
                redirect_url = construct_redirect_uri(redirect_uri, code=mcp_code, state=state)
                logger.info(f"Redirecting to client: {redirect_url[:50]}...")
                
                self._save_state()
                return redirect_url
                
        except httpx.RequestError as e:
            logger.error(f"Network error during Norman token exchange: {e}")
            raise HTTPException(500, "Failed to communicate with Norman API")

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Optional[AuthorizationCode]:
        """Load an authorization code."""
        logger.info(f"Loading auth code: {authorization_code[:20]}... for client {client.client_id[:10]}...")
        logger.info(f"Available codes: {list(self.auth_codes.keys())[:3]}")
        code = self.auth_codes.get(authorization_code)
        if code:
            logger.info(f"✅ Found auth code, expires_at={code.expires_at}, scopes={code.scopes}")
        else:
            logger.warning(f"❌ Auth code not found!")
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """Exchange authorization code for MCP tokens."""
        logger.info(f"Token exchange for code: {authorization_code.code[:10]}...")
        
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
        
        logger.info(f"✅ Issued MCP token: {mcp_token[:15]}...")
        self._save_state()

        return OAuthToken(
            access_token=mcp_token,
            token_type="bearer",
            expires_in=86400,
            scope=" ".join(authorization_code.scopes),
            refresh_token=refresh_token_id,
        )

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        """Load and validate an access token and seed per-request context."""
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

        # Seed per-request ContextVars so the tool handler sees the right
        # Norman token and company id for THIS user. ContextVars are
        # isolated per async task, so concurrent users don't leak state.
        from norman_mcp.context import (
            set_api_company_id,
            set_api_token,
            set_api_token_source,
        )

        norman_token = self.token_mapping.get(token)
        if norman_token:
            set_api_token(norman_token)
            set_api_token_source("oauth")

        cached_company_id = self.token_to_company_id.get(token)
        if not cached_company_id and norman_token:
            # First request for this session: look up the user's company so
            # tools that read api.company_id work without a prior set_token().
            cached_company_id = await self._fetch_company_id(norman_token)
            if cached_company_id:
                self.token_to_company_id[token] = cached_company_id
                self._save_state()

        if cached_company_id:
            set_api_company_id(cached_company_id)

        return access_token

    async def _fetch_company_id(self, norman_token: str) -> Optional[str]:
        """Resolve the user's primary company id from the Norman API."""
        companies_url = urljoin(config.api_base_url, "api/v1/companies/")
        try:
            async with httpx.AsyncClient() as http_client:
                response = await http_client.get(
                    companies_url,
                    headers={
                        "Authorization": f"Bearer {norman_token}",
                        "User-Agent": "NormanMCPServer/0.1.0",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    timeout=config.NORMAN_API_TIMEOUT,
                )
                if response.status_code != 200:
                    logger.warning(
                        "Company lookup failed (%s) for norman token %s...",
                        response.status_code, norman_token[:8],
                    )
                    return None
                companies = response.json().get("results", [])
                if not companies:
                    return None
                return companies[0].get("publicId")
        except Exception as e:
            logger.warning("Company lookup raised: %s", e)
            return None

    def set_company_for_token(self, mcp_token: str, company_id: Optional[str]) -> None:
        """Persist the active company id against an MCP token across requests."""
        if company_id:
            self.token_to_company_id[mcp_token] = company_id
        else:
            self.token_to_company_id.pop(mcp_token, None)
        self._save_state()

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
        """Exchange refresh token for new access token."""
        norman_refresh = self.token_mapping.get(refresh_token.token)
        if not norman_refresh:
            raise ValueError("Norman refresh token not found")
        
        # Refresh with Norman's token endpoint
        token_payload = {
            "grant_type": "refresh_token",
            "refresh_token": norman_refresh,
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
                    raise ValueError(f"Norman refresh failed: {response.status_code}")
                
                auth_data = response.json()
                new_norman_token = auth_data.get("access_token")
                new_norman_refresh = auth_data.get("refresh_token")
                
                if not new_norman_token:
                    raise ValueError("No access token in refresh response")
                
                # Generate new MCP access token
                new_mcp_token = f"mcp_{secrets.token_hex(32)}"
                
                self.tokens[new_mcp_token] = AccessToken(
                    token=new_mcp_token,
                    client_id=client.client_id,
                    scopes=scopes or refresh_token.scopes,
                    expires_at=int(time.time()) + 86400,
                )
                
                self.token_mapping[new_mcp_token] = new_norman_token

                # Update refresh token if new one provided
                if new_norman_refresh:
                    self.token_mapping[refresh_token.token] = new_norman_refresh
                self.token_mapping[f"refresh_for_{new_mcp_token}"] = (
                    new_norman_refresh or self.token_mapping.get(refresh_token.token)
                )
                
                logger.info(f"✅ Refreshed MCP token: {new_mcp_token[:15]}...")
                self._save_state()

                return OAuthToken(
                    access_token=new_mcp_token,
                    token_type="bearer",
                    expires_in=86400,
                    scope=" ".join(scopes or refresh_token.scopes),
                    refresh_token=refresh_token.token,
                )
                
        except httpx.RequestError as e:
            logger.error(f"Network error during token refresh: {e}")
            raise ValueError(f"Failed to refresh token: {e}")

    async def revoke_token(self, token: str, token_type_hint: Optional[str] = None) -> None:
        """Revoke a token."""
        changed = False
        if token in self.tokens:
            if token in self.token_mapping:
                del self.token_mapping[token]
            if token in self.token_to_company_id:
                del self.token_to_company_id[token]
            del self.tokens[token]
            logger.info(f"Revoked access token: {token[:10]}...")
            changed = True
        elif token in self.refresh_tokens:
            if token in self.token_mapping:
                del self.token_mapping[token]
            del self.refresh_tokens[token]
            logger.info(f"Revoked refresh token: {token[:10]}...")
            changed = True
        if changed:
            self._save_state()

    def get_norman_token(self, mcp_token: str) -> Optional[str]:
        """Get the Norman API token for a given MCP token."""
        return self.token_mapping.get(mcp_token)

    def refresh_norman_token_sync(self, mcp_token: str) -> Optional[str]:
        """Refresh the Norman access token for an MCP access token (sync).

        Called from NormanAPI._make_request (which uses `requests`) when
        Norman returns 401 mid-session: we swap in a fresh Norman access
        token so the MCP client does not need to reconnect. Returns the
        new Norman access token, or None if refresh is impossible
        (no stored refresh token, or refresh call failed).
        """
        import requests as _requests

        norman_refresh = self.token_mapping.get(f"refresh_for_{mcp_token}")
        if not norman_refresh:
            logger.warning("No Norman refresh token stored for mcp_token %s...", mcp_token[:12])
            return None

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
        except _requests.exceptions.RequestException as e:
            logger.error("Network error during Norman refresh: %s", e)
            return None

        if response.status_code != 200:
            logger.error(
                "Norman refresh failed for mcp_token %s...: %s",
                mcp_token[:12], response.status_code,
            )
            return None

        data = response.json()
        new_norman_token = data.get("access_token")
        new_norman_refresh = data.get("refresh_token")
        if not new_norman_token:
            return None

        self.token_mapping[mcp_token] = new_norman_token
        if new_norman_refresh:
            self.token_mapping[f"refresh_for_{mcp_token}"] = new_norman_refresh
        self._save_state()
        logger.info("✅ Refreshed Norman token for mcp_token %s...", mcp_token[:12])
        return new_norman_token
