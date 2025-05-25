from mcp.server.fastmcp import Context

# Re-export Context from mcp.server.fastmcp
# This allows us to use norman_mcp.context.Context throughout the codebase
# while maintaining a single source of truth 

"""Context variables for the Norman MCP server."""

# Global variable to store the OAuth provider across modules
oauth_provider = None 

# Global variable to store the API client
_api_client = None

# Global variables for direct API access
_api_token = None
_api_company_id = None

def set_api_client(client):
    """Set the global API client."""
    global _api_client
    _api_client = client
    
def get_api_client():
    """Get the global API client."""
    return _api_client

def set_api_token(token):
    """Set the global API token for all API calls."""
    global _api_token
    _api_token = token
    
def get_api_token():
    """Get the global API token."""
    return _api_token