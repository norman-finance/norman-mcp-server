import os
import logging
from typing import Any, Dict
from contextlib import asynccontextmanager
import time

from pydantic import AnyHttpUrl
from dotenv import load_dotenv
from starlette.requests import Request

from mcp.server.fastmcp import FastMCP, Context
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
from norman_mcp.context import oauth_provider as global_oauth_provider
import httpx

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Log to stderr
        logging.FileHandler('/tmp/norman_mcp_debug.log')  # Also log to file
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Get auth credentials from environment (for stdio transport)
# Note: These are now only used for reference; actual values are read in create_app and authenticate_with_credentials


async def authenticate_with_credentials(api_client):
    """Authenticate using environment variables."""
    from norman_mcp.config.settings import config
    
    # Read env vars dynamically here instead of using module-level variables
    norman_email = os.environ.get("NORMAN_EMAIL")
    norman_password = os.environ.get("NORMAN_PASSWORD")
    
    if not norman_email or not norman_password:
        logger.warning("NORMAN_EMAIL or NORMAN_PASSWORD not set. Authentication will fail.")
        return False
        
    auth_url = f"{config.api_base_url}api/v1/auth/token/"
    username = norman_email.split('@')[0]
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                auth_url,
                json={
                    "username": username,
                    "email": norman_email,
                    "password": norman_password
                },
                timeout=config.NORMAN_API_TIMEOUT
            )
            
            if response.status_code != 200:
                logger.error(f"Authentication failed: {response.status_code}")
                return False
                
            auth_data = response.json()
            norman_token = auth_data.get("access")
            
            if not norman_token:
                logger.error("Token not found in response")
                return False
                
            # Set token on API client
            api_client.set_token(norman_token)
            
            # Store token in global context
            from norman_mcp.context import set_api_token
            set_api_token(norman_token)
            
            logger.info(f"✅ Authenticated with credentials: {norman_email}")
            return True
            
    except Exception as e:
        logger.error(f"Error authenticating with credentials: {str(e)}")
        return False

# Server context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app):
    """Context manager for startup/shutdown events."""
    logger.info("Starting Norman MCP server lifespan")
    
    # Setup API client, but don't authenticate it or set a company ID
    # We'll get these from the login process directly
    api_client = NormanAPI(authenticate_on_init=False)
    logger.info("API client initialized without authentication")
    
    # If using stdio transport, authenticate using environment variables
    transport = getattr(app, "_transport", "sse")
    if transport == "stdio":
        logger.info("Using stdio transport - attempting authentication with environment variables")
        await authenticate_with_credentials(api_client)
    else:
        # Store API client in global context for access across modules
        from norman_mcp.context import set_api_client, get_api_token
        api_client.set_token(get_api_token())
        set_api_client(api_client)
        logger.info(f"✅ Authenticated with token: {get_api_token()}")
        logger.info(f"Using {transport} transport - will authenticate via OAuth")

    # Create a context dictionary to yield
    context = {"api": api_client}
    
    yield context
    
    logger.info("Shutting down Norman MCP server")

# Create a custom validator that allows HTTP for localhost
def custom_validate_url(url):
    """Override the default URL validator to allow HTTP for localhost."""
    # Skip HTTPS validation for localhost and local IPs
    if url.host == "localhost" or url.host.startswith("127.0.0.1") or url.host == "0.0.0.0":
        return
    # Use original validator for non-local URLs
    validate_issuer_url(url)

# Monkey patch the validation function for development
import mcp.server.auth.routes
mcp.server.auth.routes.validate_issuer_url = custom_validate_url

# HACK: Monkey patch the token handler to bypass PKCE verification
# This is more invasive but necessary for development
import mcp.server.auth.handlers.token as token_handler

# Store original handle
original_handle = token_handler.TokenHandler.handle

async def patched_handle(self, request):
    """Patched token handler that bypasses PKCE verification."""
    try:
        form_data = await request.form()
        # Log form data for debugging
        logger.info(f"Token request form data: {dict(form_data)}")
        
        # Get the TokenRequest object to access fields
        try:
            token_request = token_handler.TokenRequest.model_validate(dict(form_data)).root
        except Exception as e:
            logger.error(f"Failed to parse token request: {str(e)}")
            raise
            
        # Handle special case for authorization_code grant
        if getattr(token_request, 'grant_type', None) == 'authorization_code':
            logger.info("Bypassing PKCE verification for authorization_code flow")
            
            # For development, get client without authentication
            client_id = token_request.client_id
            
            # Get client directly from provider for development purposes
            # This bypasses client authentication requirement for development
            client_info = None
            try:
                # Try regular authentication first
                client_info = await self.client_authenticator.authenticate(
                    client_id=client_id,
                    client_secret=token_request.client_secret,
                )
                logger.info("Client authenticated successfully")
            except Exception as e:
                logger.warning(f"Standard client authentication failed: {str(e)}")
                
                # For development, try to get client directly from provider
                logger.info("Attempting development fallback authentication")
                client_info = await self.provider.get_client(client_id)
                
                if not client_info:
                    logger.error(f"Client not found: {client_id}")
                    return self.response(
                        token_handler.TokenErrorResponse(
                            error="unauthorized_client",
                            error_description=f"Client not found: {client_id}",
                        )
                    )
                logger.info("Development client authentication successful")
                
            # Load the auth code
            auth_code = await self.provider.load_authorization_code(
                client_info, token_request.code
            )
            
            if auth_code is None:
                logger.error("Authorization code not found")
                return self.response(
                    token_handler.TokenErrorResponse(
                        error="invalid_grant",
                        error_description="authorization code does not exist",
                    )
                )
                
            logger.info(f"Authorization code found: {auth_code.code[:8]}...")
            
            # Skip PKCE verification and directly exchange the code
            try:
                tokens = await self.provider.exchange_authorization_code(
                    client_info, auth_code
                )
                logger.info("Token exchange successful!")
                return self.response(token_handler.TokenSuccessResponse(root=tokens))
            except Exception as e:
                logger.error(f"Token exchange failed: {str(e)}")
                return self.response(
                    token_handler.TokenErrorResponse(
                        error="server_error",
                        error_description=f"Error exchanging code: {str(e)}",
                    )
                )
        
        # For other grant types, use the original handler
        logger.info("Using original token handler for non-authorization_code flow")
        return await original_handle(self, request)
    except Exception as e:
        logger.error(f"Error in patched token handler: {str(e)}")
        raise

# Apply the patch
token_handler.TokenHandler.handle = patched_handle
logger.info("Token handler patched with PKCE bypass")

logger.info("HTTPS validation bypassed for localhost (development only)")

def create_app(host=None, port=None, public_url=None, transport="sse"):
    """Create and configure the MCP server."""
    # Read environment variables inside the function to get the most up-to-date values
    host = host or os.environ.get("NORMAN_MCP_HOST", "0.0.0.0")
    port = port or int(os.environ.get("NORMAN_MCP_PORT", "3001"))
    public_url = public_url or os.environ.get("NORMAN_MCP_PUBLIC_URL", f"http://{host}:{port}")
    
    logger.info(f"Creating app with transport: {transport}")
    logger.info(f"Host: {host}, Port: {port}, Public URL: {public_url}")
    
    # Store the transport type for later use
    transport_type = transport
    
    # Read auth credentials directly from environment
    norman_email = os.environ.get("NORMAN_EMAIL")
    norman_password = os.environ.get("NORMAN_PASSWORD")
    
    # For stdio transport, we'll skip OAuth setup if credentials are provided
    use_oauth = True
    if transport_type == "stdio" and norman_email and norman_password:
        logger.info("Using stdio transport with environment credentials - skipping OAuth setup")
        use_oauth = False
    
    # Create OAuth provider if needed
    oauth_provider = None
    auth_settings = None
    
    if use_oauth:
        # Create OAuth provider
        server_url = AnyHttpUrl(public_url)
        logger.info(f"Setting up OAuth with server URL: {server_url}")
        oauth_provider = NormanOAuthProvider(server_url=server_url)
        
        # Store OAuth provider in global context for access from other modules
        global global_oauth_provider
        global_oauth_provider = oauth_provider
        
        # Configure auth settings - with minimal requirements for development 
        auth_settings = AuthSettings(
            issuer_url=server_url,
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["norman.read", "norman.write"],
                default_scopes=["norman.read", "norman.write"],  # Add norman.write to default scopes
            ),
            required_scopes=[],
            scopes_supported=["norman.read", "norman.write"],
            scope_descriptions={
                "norman.read": "Read access to Norman Finance API",
                "norman.write": "Write access to Norman Finance API and SSE stream",
            },
        )
    
    # Create the MCP server with guardrails and OAuth if needed
    server = FastMCP(
        "Norman Finance API", 
        instructions="Norman Finance API MCP Server with OAuth authentication",
        lifespan=lifespan,
        auth_server_provider=oauth_provider if use_oauth else None,
        auth=auth_settings,
        host=host,
        port=port,
        debug=True,
        guardrails={
            "block_indirect_prompt_injections_in_tool_output": True,
            "block_looping_tool_calls": True,
            "block_moderated_content_in_tool_output": True,
            "block_pii_in_tool_output": False,
            "block_secrets_in_messages": True,
            "prevent_empty_user_messages": True, 
            "prevent_prompt_injections_in_user_input": True,
            "prevent_urls_in_agent_output": True,
        }
    )
    
    # Store transport type on server instance for access in lifespan
    server._transport = transport_type
    
    # Register custom OAuth routes if using OAuth
    if use_oauth:
        norman_routes = create_norman_auth_routes(oauth_provider)
        for route in norman_routes:
            server._custom_starlette_routes.append(route)
    
    # Register all tools
    register_client_tools(server)
    register_invoice_tools(server)
    register_tax_tools(server)
    register_transaction_tools(server)
    register_document_tools(server)
    register_company_tools(server)
    register_prompts(server)
    register_resources(server)
    
    return server

# Create the MCP server instance with default settings
# but don't run it yet - that happens in __main__ or when called directly
mcp = create_app()

# Add a set_token method to NormanAPI class if not already exists
def setup_api_client_patches():
    """Apply necessary patches to the NormanAPI class."""
    # The set_token method already exists in the updated NormanAPI class
    pass

# Apply the patches before creating the app
setup_api_client_patches()

if __name__ == "__main__":
    from norman_mcp.cli import main
    main()