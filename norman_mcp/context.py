from contextvars import ContextVar
from typing import Optional

from mcp.server.fastmcp import Context

# Re-export Context from mcp.server.fastmcp
# This allows us to use norman_mcp.context.Context throughout the codebase
# while maintaining a single source of truth

"""Context variables for the Norman MCP server."""

# Global variable to store the OAuth provider across modules.
# Set by server.create_app after the provider is constructed.
oauth_provider = None

def set_oauth_provider(provider):
    """Set the global OAuth provider reference."""
    global oauth_provider
    oauth_provider = provider

def get_oauth_provider():
    """Get the global OAuth provider reference (may be None before startup)."""
    return oauth_provider

# Global variable to store the API client.
# NOTE: the NormanAPI instance is shared across all requests in a process.
# It MUST NOT hold per-user state (token, company id) — those live in the
# request-scoped ContextVars below so concurrent users never see each other's
# data. See tests/test_concurrency.py for the regression this protects.
_api_client = None

# Per-request Norman API token / company id.
#
# These are ContextVars, NOT plain module globals. In a multi-user remote
# deployment (SSE / streamable-http) the server handles many users in one
# process; a plain global would let one user's token leak into another user's
# in-flight request. ContextVars are isolated per asyncio task / per copied
# context (e.g. anyio worker threads), so each request reads only its own value.
_api_token: ContextVar[Optional[str]] = ContextVar("norman_api_token", default=None)
_api_company_id: ContextVar[Optional[str]] = ContextVar("norman_api_company_id", default=None)

def set_api_client(client):
    """Set the global API client."""
    global _api_client
    _api_client = client

def get_api_client():
    """Get the global API client."""
    return _api_client

def set_api_token(token):
    """Set the Norman API token for the current request context."""
    _api_token.set(token)

def get_api_token():
    """Get the Norman API token for the current request context."""
    return _api_token.get()

def set_api_company_id(company_id):
    """Set the resolved company id for the current request context."""
    _api_company_id.set(company_id)

def get_api_company_id():
    """Get the resolved company id for the current request context."""
    return _api_company_id.get()
