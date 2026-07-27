from contextvars import ContextVar
from typing import Optional

from mcp.server.fastmcp import Context

# Re-export Context from mcp.server.fastmcp
# This allows us to use norman_mcp.context.Context throughout the codebase
# while maintaining a single source of truth

"""Context variables for the Norman MCP server.

SECURITY: the Norman access token and company id are **per-request** identity.
They used to be plain module globals, which meant one user's token could be
read by another user's concurrent request in the same process (one swarm
replica + `--stateless` => every user shares one interpreter). That is a
cross-tenant data leak, so they are ContextVars now: each ASGI request runs in
its own task with its own copied context, so a write here is visible only to
the request that made it.

Do NOT turn these back into module globals, and do not cache a resolved token
on a shared object (see `NormanAPI._resolve_norman_token`).
"""

# The OAuth provider is genuinely process-wide -- it owns the client/token
# registry and holds no per-request identity -- so it stays a module global.
oauth_provider = None

def set_oauth_provider(provider):
    """Set the global OAuth provider reference."""
    global oauth_provider
    oauth_provider = provider

def get_oauth_provider():
    """Get the global OAuth provider reference (may be None before startup)."""
    return oauth_provider

# The API client instance. Stateless HTTP builds a fresh one per request via the
# lifespan; SSE/stdio reuse one. Either way it must not carry identity state.
_api_client = None

# Per-request identity. Never make these module globals again.
_api_token: ContextVar[Optional[str]] = ContextVar("norman_api_token", default=None)
_api_company_id: ContextVar[Optional[str]] = ContextVar("norman_api_company_id", default=None)

def set_api_client(client):
    """Set the global API client."""
    global _api_client
    _api_client = client

def get_api_client():
    """Get the global API client."""
    return _api_client

def set_api_token(token: Optional[str]) -> None:
    """Set the Norman API token for the current request only."""
    _api_token.set(token)

def get_api_token() -> Optional[str]:
    """Get the Norman API token for the current request."""
    return _api_token.get()

def set_api_company_id(company_id: Optional[str]) -> None:
    """Cache the company id resolved for the current request only."""
    _api_company_id.set(company_id)

def get_api_company_id() -> Optional[str]:
    """Get the company id resolved for the current request."""
    return _api_company_id.get()
