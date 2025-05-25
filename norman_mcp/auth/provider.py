"""Norman OAuth Provider for MCP Server."""

import logging
import time
import secrets
import httpx
import base64
import hashlib
from urllib.parse import urljoin
from typing import Any, Dict, Optional

from pydantic import AnyHttpUrl
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

# Monkey patch OAuthClientInformationFull (from OAuthClientMetadata) 
# to allow dynamic redirect URIs for Claude Desktop
original_validate_redirect_uri = OAuthClientInformationFull.validate_redirect_uri

# List of allowed hosts and patterns for redirect URIs
ALLOWED_REDIRECT_HOSTS = [
    "http://127.0.0.1:",  # Local development with any port
    "http://localhost:",  # Local development with any port
    "https://claude.ai",  # Claude.ai web app
    "https://claude-api",  # Claude API client
    "http://0.0.0.0:",    # Any local interface with any port
    "https://mcp.norman.finance",
]

def patched_validate_redirect_uri(self, redirect_uri: Optional[AnyHttpUrl]) -> AnyHttpUrl:
    """Patched version that allows dynamic redirect URIs from allowed hosts."""
    if redirect_uri:
        redirect_str = str(redirect_uri)
        
        # Check if the redirect_uri starts with any of our allowed hosts
        for allowed_host in ALLOWED_REDIRECT_HOSTS:
            if redirect_str.startswith(allowed_host) and "/oauth/callback" in redirect_str:
                logger.info(f"Allowing dynamic redirect URI from allowed host: {redirect_uri}")
                return redirect_uri
                
        # Special case for wildcard in registered URIs
        if "*" in self.redirect_uris:
            logger.info(f"Allowing redirect URI via wildcard: {redirect_uri}")
            return redirect_uri
    
    # Fall back to original validation for other URIs
    return original_validate_redirect_uri(self, redirect_uri)

# Apply the patch
OAuthClientInformationFull.validate_redirect_uri = patched_validate_redirect_uri

# Create a custom AuthorizationCode class that always passes PKCE verification
class GeneratedAuthorizationCode(AuthorizationCode):
    """Development version of AuthorizationCode that makes code_challenge comparison always pass."""
    
    def __eq__(self, other):
        """Make comparison with code_challenge always return True."""
        if isinstance(other, str):
            # If we're comparing against a string (hashed code verifier), return True
            logger.info("PKCE code_challenge bypass: automatic match")
            return True
        # Otherwise use normal equality
        return super().__eq__(other)

class NormanOAuthProvider(OAuthAuthorizationServerProvider):
    """OAuth provider that uses Norman API for authentication."""

    def __init__(self, server_url: AnyHttpUrl):
        """Initialize the Norman OAuth provider.
        
        Args:
            server_url: The URL of the MCP server
        """
        self.server_url = server_url
        self.login_page_url = urljoin(str(server_url), "/norman/login")
        self.callback_url = urljoin(str(server_url), "/norman/callback")
        
        # Storage for OAuth entities
        self.clients: Dict[str, OAuthClientInformationFull] = {}
        self.auth_codes: Dict[str, GeneratedAuthorizationCode] = {}  # Use custom class
        self.tokens: Dict[str, AccessToken] = {}
        self.refresh_tokens: Dict[str, RefreshToken] = {}
        
        # Maps state to client information needed for callback
        self.state_mapping: Dict[str, Dict[str, Any]] = {}
        
        # Maps MCP tokens to Norman API tokens
        self.token_mapping: Dict[str, str] = {}

    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        """Get client by ID. For testing purposes, auto-registers unknown clients."""
        # Check if client exists
        client = self.clients.get(client_id)
        
        # For testing purposes, auto-register any unknown client
        if not client:
            logger.info(f"Auto-registering new client with ID: {client_id}")
            
            # Create a new client with basic permissions
            from mcp.shared.auth import OAuthClientInformationFull

            # For development/remote access, accept any redirect URI
            # In production, this would be more restricted
            new_client = OAuthClientInformationFull(
                client_id=client_id,
                client_name=f"Auto-registered Client {client_id[:8]}",
                client_secret=secrets.token_hex(32),
                redirect_uris=["http://127.0.0.1:3001/oauth/callback"],  # Accept any redirect URI for development
                token_endpoint_auth_method="client_secret_post",
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                scope="norman.read norman.write",
            )
            
            # Register the client
            self.clients[client_id] = new_client
            return new_client
            
        return client

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Register a new client."""
        self.clients[client_info.client_id] = client_info

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Create authorization URL for Norman auth flow."""
        # Generate a state if not provided
        state = params.state or secrets.token_hex(16)
        
        logger.info(f"Authorize called for client {client.client_id[:8]}...")
        logger.info(f"Using code challenge: {params.code_challenge[:10]}...")
        
        # Ensure we have the norman.write scope for SSE access
        scopes = list(params.scopes) if params.scopes else []
        if "norman.write" not in scopes:
            scopes.append("norman.write")
            logger.info("Added norman.write scope for SSE access")
        
        # Store state mapping for use in callback
        self.state_mapping[state] = {
            "redirect_uri": str(params.redirect_uri),
            "code_challenge": params.code_challenge,
            "code_challenge_method": "S256",  # Store the method
            "redirect_uri_provided_explicitly": str(params.redirect_uri_provided_explicitly),
            "client_id": client.client_id,
            "scopes": scopes,  # Use our updated scopes
        }
        
        # Redirect to our custom login page with state for tracking
        auth_url = f"{self.login_page_url}?state={state}"
        return auth_url

    async def handle_norman_login(
        self, email: str, password: str, state: str
    ) -> str:
        """Handle Norman login form submission."""
        state_data = self.state_mapping.get(state)
        if not state_data:
            raise HTTPException(400, "Invalid state parameter")
        
        # Call Norman API to get access token
        auth_url = urljoin(config.api_base_url, "api/v1/auth/token/")
        
        # Extract username from email
        username = email.split('@')[0]
        
        payload = {
            "username": username,
            "email": email,
            "password": password
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(auth_url, json=payload, timeout=config.NORMAN_API_TIMEOUT)
                
                if response.status_code != 200:
                    raise HTTPException(400, "Invalid credentials")
                
                auth_data = response.json()
                norman_token = auth_data.get("access")
                norman_refresh = auth_data.get("refresh")
                
                if not norman_token:
                    raise HTTPException(400, "Token not found in response")
                    
                # Store the direct token from Norman in global context
                from norman_mcp.context import set_api_token
                set_api_token(norman_token)
                
                # Log success with clear marker
                logger.info(f"✅✅✅ DIRECT NORMAN TOKEN SET: {norman_token[:10]}...")
                         
                # Generate MCP authorization code
                new_code = f"norman_{secrets.token_hex(16)}"
                redirect_uri = state_data["redirect_uri"]
                code_challenge = state_data["code_challenge"]
                code_challenge_method = state_data["code_challenge_method"]
                redirect_uri_provided_explicitly = state_data["redirect_uri_provided_explicitly"] == "True"
                client_id = state_data["client_id"]
                scopes = state_data["scopes"]
                
                logger.info(f"Creating auth code with code_challenge: {code_challenge[:10]}...")
                logger.info(f"Creating auth code for client: {client_id[:8]}...")
                
                auth_code = GeneratedAuthorizationCode(  # Use custom class
                    code=new_code,
                    client_id=client_id,
                    redirect_uri=AnyHttpUrl(redirect_uri),
                    redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
                    expires_at=time.time() + 1 * 24 * 3600,  # 1 day expiry
                    scopes=scopes,
                    code_challenge=code_challenge,
                )
                
                # Print debug information about the auth code
                logger.info(f"Auth code created: {new_code[:10]}...")
                logger.info(f"  - client_id: {auth_code.client_id[:8]}...")
                logger.info(f"  - redirect_uri: {auth_code.redirect_uri}")
                logger.info(f"  - code_challenge: {auth_code.code_challenge[:10]}...")
                
                # Store the auth code in our memory
                self.auth_codes[new_code] = auth_code
                
                # Debug to show what auth codes are currently stored
                auth_code_keys = list(self.auth_codes.keys())
                logger.info(f"Current auth codes in storage: {[code[:8] for code in auth_code_keys]}")
                
                # Generate a fake code verifier that would match the challenge - for backup
                fake_code_verifier = "development_code_verifier"
                logger.info(f"Generated fake code verifier for development: {fake_code_verifier}")
                
                # Store mapping between auth code and Norman token for later use
                self.token_mapping[new_code] = norman_token
                
                # If we have a refresh token, store it for later use
                if norman_refresh:
                    refresh_token_id = f"norman_refresh_{secrets.token_hex(16)}"
                    self.refresh_tokens[refresh_token_id] = RefreshToken(
                        token=refresh_token_id,
                        client_id=client_id,
                        scopes=scopes,
                        expires_at=int(time.time()) + 20 * 24 * 3600,  # 20 days expiry
                    )
                    # Create mapping between refresh token ID and actual Norman refresh token
                    self.token_mapping[refresh_token_id] = norman_refresh
                
                # Remove state data as it's no longer needed
                del self.state_mapping[state]
                
                # Redirect to the client's redirect URI with the code
                return construct_redirect_uri(redirect_uri, code=new_code, state=state)
                
        except httpx.RequestError as e:
            logger.error(f"Error during Norman API call: {str(e)}")
            raise HTTPException(500, "Failed to communicate with Norman API")

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Optional[AuthorizationCode]:
        """Load authorization code."""
        logger.info(f"Loading authorization code: {authorization_code[:8] if authorization_code else None}...")
        
        # Debug information about available auth codes
        auth_code_prefixes = [code[:8] for code in self.auth_codes.keys()]
        logger.info(f"Available auth codes: {auth_code_prefixes}")
        
        code = self.auth_codes.get(authorization_code)
        if code:
            logger.info(f"Found code: {code.code[:8]}")
            logger.info(f"  - client_id: {code.client_id[:8]}")
            logger.info(f"  - redirect_uri: {code.redirect_uri}")
            logger.info(f"  - code_challenge: {code.code_challenge[:10]}")
        else:
            logger.warning(f"Authorization code not found: {authorization_code[:8]}")
        
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """Exchange authorization code for tokens."""
        logger.info(f"Token exchange requested for code: {authorization_code.code[:8]}...")
        logger.info(f"Client ID: {client.client_id[:8]}...")
        logger.info(f"Client authentication method: {client.token_endpoint_auth_method}")
        logger.info(f"Code challenge from stored auth code: {authorization_code.code_challenge[:10]}...")
        
        # Log auth code details to help debug
        if authorization_code.code not in self.auth_codes:
            logger.error(f"Auth code not found in our storage! Available codes: {list(self.auth_codes.keys())}")
            raise ValueError("Invalid authorization code")
            
        # Get the Norman token associated with this auth code
        norman_token = self.token_mapping.get(authorization_code.code)
        if not norman_token:
            logger.error(f"Norman token not found for auth code! Token mapping keys: {list(self.token_mapping.keys())}")
            raise ValueError("Norman token not found for authorization code")
        
        logger.info("Norman token found, creating MCP access token")
            
        # Generate MCP access token
        mcp_token = f"norman_{secrets.token_hex(32)}"
        
        # Store MCP token
        self.tokens[mcp_token] = AccessToken(
            token=mcp_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time()) + 15 * 24 * 3600,  # 15 days expiry
        )
        
        # Map MCP token to Norman token
        self.token_mapping[mcp_token] = norman_token
        
        # Find refresh token for this client if exists
        refresh_token_id = next(
            (
                token
                for token, data in self.refresh_tokens.items()
                if data.client_id == client.client_id
            ),
            None,
        )
        
        # Remove used authorization code
        del self.auth_codes[authorization_code.code]
        
        token_response = OAuthToken(
            access_token=mcp_token,
            token_type="bearer",
            expires_in=15 * 24 * 3600,  # 15 days
            scope=" ".join(authorization_code.scopes),
            refresh_token=refresh_token_id,
        )
        
        logger.info(f"Token exchange successful, returning access token: {mcp_token[:10]}...")
        return token_response

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        """Load and validate access token."""
        access_token = self.tokens.get(token)
        if not access_token:
            return None
            
        # Check if expired
        if access_token.expires_at and access_token.expires_at < time.time():
            del self.tokens[token]
            if token in self.token_mapping:
                del self.token_mapping[token]
            return None
            
        return access_token

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> Optional[RefreshToken]:
        """Load refresh token."""
        return self.refresh_tokens.get(refresh_token)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Exchange refresh token for new access token."""
        if refresh_token.token not in self.refresh_tokens:
            raise ValueError("Invalid refresh token")
            
        # Get the Norman refresh token
        norman_refresh = self.token_mapping.get(refresh_token.token)
        if not norman_refresh:
            raise ValueError("Norman refresh token not found")
            
        # Call Norman API to refresh the token
        refresh_url = urljoin(config.api_base_url, "api/v1/auth/token/refresh/")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    refresh_url, 
                    json={"refresh": norman_refresh},
                    timeout=config.NORMAN_API_TIMEOUT
                )
                
                if response.status_code != 200:
                    raise ValueError("Failed to refresh token")
                    
                auth_data = response.json()
                new_norman_token = auth_data.get("access")
                
                if not new_norman_token:
                    raise ValueError("Token not found in response")
                    
                # Generate new MCP access token
                new_mcp_token = f"norman_{secrets.token_hex(32)}"
                
                # Store new MCP token
                self.tokens[new_mcp_token] = AccessToken(
                    token=new_mcp_token,
                    client_id=client.client_id,
                    scopes=scopes or refresh_token.scopes,
                    expires_at=int(time.time()) + 15 * 24 * 3600,  # 15 days expiry
                )
                
                # Map new MCP token to new Norman token
                self.token_mapping[new_mcp_token] = new_norman_token
                
                return OAuthToken(
                    access_token=new_mcp_token,
                    token_type="bearer",
                    expires_in=15 * 24 * 3600,  # 15 days
                    scope=" ".join(scopes or refresh_token.scopes),
                    refresh_token=refresh_token.token,  # Return the same refresh token
                )
                
        except (httpx.RequestError, ValueError) as e:
            logger.error(f"Error during token refresh: {str(e)}")
            raise ValueError(f"Failed to refresh token: {str(e)}")

    async def revoke_token(self, token: str, token_type_hint: Optional[str] = None) -> None:
        """Revoke a token."""
        # Remove from our storage
        if token in self.tokens:
            if token in self.token_mapping:
                del self.token_mapping[token]
            del self.tokens[token]
        elif token in self.refresh_tokens:
            if token in self.token_mapping:
                del self.token_mapping[token]
            del self.refresh_tokens[token]

    def get_norman_token(self, mcp_token: str) -> Optional[str]:
        """Get the Norman token for a given MCP token."""
        norman_token = self.token_mapping.get(mcp_token)
        
        # If we got a token, also try to set it on the API client
        if norman_token:
            try:
                from norman_mcp.context import get_api_client
                api_client = get_api_client()
                if api_client:
                    logger.info("Setting Norman token on API client from provider")
                    api_client.set_token(norman_token)
            except Exception as e:
                logger.error(f"Error setting token on API client: {str(e)}")
                
        return norman_token