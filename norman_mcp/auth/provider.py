"""Norman OAuth Provider for MCP Server.

This provider acts as an OAuth Authorization Server that delegates
authentication to Norman's OAuth server. It:
1. Redirects users to Norman's OAuth authorize endpoint
2. Receives callbacks with authorization codes from Norman
3. Exchanges Norman codes for Norman tokens
4. Issues MCP tokens that map to Norman tokens
"""

import os
import logging
import time
import secrets
import httpx
from urllib.parse import urljoin, urlencode
from typing import Any, Dict, Optional

from pydantic import AnyHttpUrl, AnyUrl
from starlette.exceptions import HTTPException

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


class NormanOAuthProvider(OAuthAuthorizationServerProvider):
    """OAuth provider that delegates authentication to Norman's OAuth server."""

    def __init__(self, server_url: AnyHttpUrl):
        """Initialize the Norman OAuth provider.
        
        Args:
            server_url: The URL of the MCP server (used for callbacks)
        """
        self.server_url = server_url
        
        # Norman OAuth endpoints
        self.norman_authorize_url = urljoin(config.api_base_url, "api/v1/oauth/authorize/")
        self.norman_token_url = urljoin(config.api_base_url, "api/v1/oauth/token/")
        
        # MCP Server's callback URL (Norman redirects here after auth)
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
        
        # Maps state to client information needed for callback
        self.state_mapping: Dict[str, Dict[str, Any]] = {}
        
        # Maps MCP tokens to Norman API tokens
        self.token_mapping: Dict[str, str] = {}
        
        # Pre-register the Norman OAuth client if configured
        self._register_norman_client()

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
                scope="read write",
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
            client = OAuthClientInformationFull(
                client_id=client_id,
                client_name=f"Client {client_id[:8]}",
                client_secret=secrets.token_hex(32),
                redirect_uris=default_redirect_uris,  # type: ignore
                token_endpoint_auth_method="none",
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                scope="read write",
            )
            self.clients[client_id] = client
            logger.debug(f"Registered redirect_uris: {[str(u) for u in client.redirect_uris]}")
            
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

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Register a new OAuth client via Dynamic Client Registration."""
        # Ensure client has proper scopes for Norman API access
        if not client_info.scope or "read" not in client_info.scope:
            # Create a new client with proper scopes
            client_info = OAuthClientInformationFull(
                client_id=client_info.client_id,
                client_name=client_info.client_name,
                client_secret=client_info.client_secret,
                redirect_uris=client_info.redirect_uris,
                token_endpoint_auth_method=client_info.token_endpoint_auth_method or "none",
                grant_types=client_info.grant_types or ["authorization_code", "refresh_token"],
                response_types=client_info.response_types or ["code"],
                scope="read write",  # Ensure scopes are set
            )
        self.clients[client_info.client_id] = client_info
        logger.info(f"Registered client: {client_info.client_id} with scope: {client_info.scope}")

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
            "scopes": list(params.scopes) if params.scopes else ["read", "write"],
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
                
                # Store Norman token in global context
                from norman_mcp.context import set_api_token
                set_api_token(norman_token)
                
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
        
        # Clean up used authorization code
        del self.auth_codes[authorization_code.code]
        if authorization_code.code in self.token_mapping:
            del self.token_mapping[authorization_code.code]
        if f"refresh_{authorization_code.code}" in self.token_mapping:
            del self.token_mapping[f"refresh_{authorization_code.code}"]
        
        logger.info(f"✅ Issued MCP token: {mcp_token[:15]}...")
        
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
        
        # Check expiration
        if access_token.expires_at and access_token.expires_at < time.time():
            del self.tokens[token]
            if token in self.token_mapping:
                del self.token_mapping[token]
            return None
        
        # Set Norman token in context when validating
        norman_token = self.token_mapping.get(token)
        if norman_token:
            from norman_mcp.context import set_api_token
            set_api_token(norman_token)
        
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
                
                logger.info(f"✅ Refreshed MCP token: {new_mcp_token[:15]}...")
                
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
        if token in self.tokens:
            if token in self.token_mapping:
                del self.token_mapping[token]
            del self.tokens[token]
            logger.info(f"Revoked access token: {token[:10]}...")
            
        elif token in self.refresh_tokens:
            if token in self.token_mapping:
                del self.token_mapping[token]
            del self.refresh_tokens[token]
            logger.info(f"Revoked refresh token: {token[:10]}...")

    def get_norman_token(self, mcp_token: str) -> Optional[str]:
        """Get the Norman API token for a given MCP token."""
        return self.token_mapping.get(mcp_token)
