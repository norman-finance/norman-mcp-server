"""Context variables for the Norman MCP server.

Per-request state (Norman access token, company id, token source) lives in
``contextvars.ContextVar`` so that concurrent requests under the HTTP/SSE
transports don't leak tokens across users. Each asyncio task inherits the
current context at creation and can ``set()`` its own value in isolation.
"""

from contextvars import ContextVar
from typing import Optional

from mcp.server.fastmcp import Context

# Re-export Context from mcp.server.fastmcp
# This allows us to use norman_mcp.context.Context throughout the codebase
# while maintaining a single source of truth.

# Process-wide singletons (safe to be module globals — not per-request state).
oauth_provider = None
_api_client = None


def set_oauth_provider(provider):
    """Set the global OAuth provider reference."""
    global oauth_provider
    oauth_provider = provider


def get_oauth_provider():
    """Get the global OAuth provider reference (may be None before startup)."""
    return oauth_provider


def set_api_client(client):
    """Set the global API client."""
    global _api_client
    _api_client = client


def get_api_client():
    """Get the global API client."""
    return _api_client


# Per-request state. Module-level globals would leak across concurrent
# requests — see https://peps.python.org/pep-0567/ for ContextVar semantics.
_api_token_var: ContextVar[Optional[str]] = ContextVar(
    "norman_api_token", default=None
)
_api_company_id_var: ContextVar[Optional[str]] = ContextVar(
    "norman_api_company_id", default=None
)
_api_token_source_var: ContextVar[str] = ContextVar(
    "norman_api_token_source", default="env"
)


def set_api_token(token: Optional[str]) -> None:
    """Set the Norman API token for the current request/task."""
    _api_token_var.set(token)


def get_api_token() -> Optional[str]:
    """Get the Norman API token for the current request/task."""
    return _api_token_var.get()


def set_api_company_id(company_id: Optional[str]) -> None:
    """Set the Norman company id for the current request/task."""
    _api_company_id_var.set(company_id)


def get_api_company_id() -> Optional[str]:
    """Get the Norman company id for the current request/task."""
    return _api_company_id_var.get()


def set_api_token_source(source: str) -> None:
    """Set the token source label ('env' | 'oauth' | 'global') for the current request."""
    _api_token_source_var.set(source)


def get_api_token_source() -> str:
    """Get the token source label for the current request."""
    return _api_token_source_var.get()


def reset_request_state() -> None:
    """Clear all per-request ContextVars. Intended for tests."""
    _api_token_var.set(None)
    _api_company_id_var.set(None)
    _api_token_source_var.set("env")
