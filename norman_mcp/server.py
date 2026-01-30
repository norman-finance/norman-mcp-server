"""Norman MCP Server with OAuth authentication.

This server uses Norman's OAuth for authentication:
1. Clients connect to the MCP server
2. Server redirects to Norman OAuth for authentication
3. After auth, Norman redirects back with authorization code
4. Server exchanges code for Norman tokens
5. Server issues MCP tokens mapped to Norman tokens
"""

import os
import logging
from contextlib import asynccontextmanager

from pydantic import AnyHttpUrl
from dotenv import load_dotenv
import httpx
from starlette.middleware.cors import CORSMiddleware

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.auth.routes import validate_issuer_url

from norman_mcp.api.client import NormanAPI
from norman_mcp.tools.clients import register_client_tools
from norman_mcp.tools.invoices import register_invoice_tools
from norman_mcp.tools.taxes import register_tax_tools
from norman_mcp.tools.transactions import register_transaction_tools
from norman_mcp.tools.documents import register_document_tools
from norman_mcp.tools.company import register_company_tools
from norman_mcp.prompts.templates import register_prompts
from norman_mcp.resources.endpoints import register_resources
from norman_mcp.auth.provider import NormanOAuthProvider
from norman_mcp.auth.routes import create_norman_auth_routes

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


# Allow HTTP for localhost in development
def custom_validate_url(url):
    """Allow HTTP for localhost URLs."""
    if url.host in ("localhost", "127.0.0.1", "0.0.0.0"):
        return
    validate_issuer_url(url)

import mcp.server.auth.routes
mcp.server.auth.routes.validate_issuer_url = custom_validate_url

# Patch to add "none" as supported token auth method (for public clients with PKCE)
_original_build_metadata = mcp.server.auth.routes.build_metadata
def patched_build_metadata(*args, **kwargs):
    """Add 'none' to supported token auth methods for public clients."""
    metadata = _original_build_metadata(*args, **kwargs)
    if metadata.token_endpoint_auth_methods_supported:
        metadata = metadata.model_copy(update={
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"]
        })
    return metadata
mcp.server.auth.routes.build_metadata = patched_build_metadata




async def authenticate_with_credentials(api_client):
    """Authenticate using environment variables (for stdio transport)."""
    from norman_mcp.config.settings import config
    
    norman_email = os.environ.get("NORMAN_EMAIL")
    norman_password = os.environ.get("NORMAN_PASSWORD")
    
    if not norman_email or not norman_password:
        logger.warning("NORMAN_EMAIL or NORMAN_PASSWORD not set")
        return False
    
    auth_url = f"{config.api_base_url}api/v1/auth/token/"
    username = norman_email.split('@')[0]
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                auth_url,
                json={"username": username, "email": norman_email, "password": norman_password},
                timeout=config.NORMAN_API_TIMEOUT
            )
            
            if response.status_code != 200:
                logger.error(f"Authentication failed: {response.status_code}")
                return False
            
            norman_token = response.json().get("access")
            if not norman_token:
                return False
            
            api_client.set_token(norman_token)
            
            from norman_mcp.context import set_api_token
            set_api_token(norman_token)
            
            logger.info(f"✅ Authenticated: {norman_email}")
            return True
            
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        return False


@asynccontextmanager
async def lifespan(app):
    """Server startup/shutdown lifecycle."""
    logger.info("Starting Norman MCP server")
    
    api_client = NormanAPI(authenticate_on_init=False)
    
    transport = getattr(app, "_transport", "sse")
    if transport == "stdio":
        await authenticate_with_credentials(api_client)
    else:
        from norman_mcp.context import set_api_client, get_api_token
        token = get_api_token()
        if token:
            api_client.set_token(token)
        set_api_client(api_client)
        logger.info(f"Using {transport} transport with OAuth")
    
    yield {"api": api_client}
    
    logger.info("Shutting down Norman MCP server")


def create_app(host=None, port=None, public_url=None, transport="sse", streamable_http_options=None):
    """Create and configure the MCP server.
    
    Args:
        host: Host to bind to (default: 0.0.0.0)
        port: Port to bind to (default: 3001)
        public_url: Public URL for OAuth callbacks (must use localhost, not 0.0.0.0)
        transport: Transport - 'stdio', 'sse', or 'streamable-http'
        streamable_http_options: Options for streamable-http transport
    """
    host = host or os.environ.get("NORMAN_MCP_HOST", "0.0.0.0")
    port = port or int(os.environ.get("NORMAN_MCP_PORT", "3001"))
    # Always use localhost for public URL (not 0.0.0.0 which causes OAuth issues)
    public_url = public_url or os.environ.get("NORMAN_MCP_PUBLIC_URL", f"http://localhost:{port}")
    
    if streamable_http_options is None:
        streamable_http_options = {"stateless": False, "json_response": True}
    
    logger.info(f"Creating app: transport={transport}, url={public_url}")
    
    transport_type = transport.replace('_', '-') if transport else "sse"
    
    # Skip OAuth for stdio with credentials
    norman_email = os.environ.get("NORMAN_EMAIL")
    norman_password = os.environ.get("NORMAN_PASSWORD")
    use_oauth = not (transport_type == "stdio" and norman_email and norman_password)
    
    oauth_provider = None
    auth_settings = None
    
    if use_oauth:
        server_url = AnyHttpUrl(public_url)
        oauth_provider = NormanOAuthProvider(server_url=server_url)
        
        auth_settings = AuthSettings(
            issuer_url=server_url,
            resource_server_url=server_url,
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["read", "write"],
                default_scopes=["read", "write"],
            ),
            required_scopes=[],
            scopes_supported=["read", "write"],
        )
    
    server = FastMCP(
        "Norman Finance API", 
        instructions="Norman Finance MCP Server - Access your financial data",
        lifespan=lifespan,
        auth_server_provider=oauth_provider,
        auth=auth_settings,
        host=host,
        port=port,
        debug=True,
        stateless_http=streamable_http_options.get("stateless", False),
        json_response=streamable_http_options.get("json_response", True),
    )
    
    server._transport = transport_type
    
    # Register OAuth callback route
    if use_oauth:
        for route in create_norman_auth_routes(oauth_provider):
            server._custom_starlette_routes.append(route)
    
    # Register tools, prompts, and resources
    register_client_tools(server)
    register_invoice_tools(server)
    register_tax_tools(server)
    register_transaction_tools(server)
    register_document_tools(server)
    register_company_tools(server)
    register_prompts(server)
    register_resources(server)
    
    return server


def create_cors_app(server: FastMCP):
    """Wrap FastMCP app with CORS middleware for browser clients."""
    from starlette.applications import Starlette
    from starlette.routing import Mount
    
    # Get the underlying ASGI app
    app = server.streamable_http_app()
    
    # Wrap with CORS
    cors_app = CORSMiddleware(
        app,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    
    return cors_app


# Create default server instance
mcp = create_app()

if __name__ == "__main__":
    from norman_mcp.cli import main
    main()
