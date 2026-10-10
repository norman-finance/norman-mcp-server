"""Allow Cursor's web OAuth callback without trusting its entire domain."""

import pytest
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull

from norman_mcp.security.redirects import is_allowed_redirect_uri

CURSOR_CALLBACK = "https://www.cursor.com/agents/mcp/oauth/callback"
BLOCKED_REDIRECTS = [
    "http://www.cursor.com/agents/mcp/oauth/callback",
    "https://www.cursor.com/other-callback",
    CURSOR_CALLBACK + "/",
    CURSOR_CALLBACK + "/extra",
    CURSOR_CALLBACK + "?next=https://attacker.example",
    CURSOR_CALLBACK + "#fragment",
    "https://www.cursor.com:8443/agents/mcp/oauth/callback",
    "https://cursor.com/agents/mcp/oauth/callback",
    "https://sub.www.cursor.com/agents/mcp/oauth/callback",
    "https://www.cursor.com.attacker.example/agents/mcp/oauth/callback",
    "https://evil-cursor.com/agents/mcp/oauth/callback",
    "https://www.cursor.com@attacker.example/agents/mcp/oauth/callback",
    "https://attacker@www.cursor.com/agents/mcp/oauth/callback",
]


@pytest.fixture(autouse=True)
def default_allowlist(monkeypatch):
    monkeypatch.delenv("NORMAN_MCP_ALLOWED_REDIRECT_HOSTS", raising=False)


def test_cursor_callback_is_allowed():
    assert is_allowed_redirect_uri(CURSOR_CALLBACK)


@pytest.mark.parametrize("uri", BLOCKED_REDIRECTS)
def test_other_cursor_redirect_targets_remain_blocked(uri):
    assert not is_allowed_redirect_uri(uri)


@pytest.mark.parametrize("omit_redirect_uri", [False, True])
def test_authorize_validator_accepts_cursor_callback(omit_redirect_uri):
    import norman_mcp.server  # noqa: F401 (installs the authorization validator)

    client = OAuthClientInformationFull(
        client_id="cursor-callback-regression", redirect_uris=[CURSOR_CALLBACK]
    )
    redirect_uri = None if omit_redirect_uri else CURSOR_CALLBACK
    assert str(client.validate_redirect_uri(redirect_uri)) == CURSOR_CALLBACK


@pytest.mark.parametrize("uri", BLOCKED_REDIRECTS)
def test_authorize_validator_rejects_registered_cursor_variants(uri):
    import norman_mcp.server  # noqa: F401 (installs the authorization validator)

    client = OAuthClientInformationFull(client_id="cursor-blocked-regression", redirect_uris=[uri])
    # Open registration must not let an unsafe callback through either path.
    for redirect_uri in (uri, None):
        with pytest.raises(InvalidRedirectUriError, match="redirect_uri not allowed"):
            client.validate_redirect_uri(redirect_uri)
