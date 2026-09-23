"""Allow Grok's observed OAuth callback without trusting its entire domain."""

import pytest

from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull

from norman_mcp.security.redirects import is_allowed_redirect_uri

GROK_CALLBACK = "https://grok.com/connectors-oauth-exchange-code/"


@pytest.fixture(autouse=True)
def default_allowlist(monkeypatch):
    monkeypatch.delenv("NORMAN_MCP_ALLOWED_REDIRECT_HOSTS", raising=False)


def test_grok_callback_is_allowed():
    assert is_allowed_redirect_uri(GROK_CALLBACK)


@pytest.mark.parametrize(
    "uri",
    [
        "http://grok.com/connectors-oauth-exchange-code/",
        "https://grok.com/other-callback/",
        "https://grok.com/connectors-oauth-exchange-code/extra",
        "https://grok.com/connectors-oauth-exchange-code/?next=https://attacker.example",
        "https://grok.com/connectors-oauth-exchange-code/#fragment",
        "https://grok.com:8443/connectors-oauth-exchange-code/",
        "https://sub.grok.com/connectors-oauth-exchange-code/",
        "https://grok.com.attacker.example/connectors-oauth-exchange-code/",
        "https://evil-grok.com/connectors-oauth-exchange-code/",
        "https://grok.com@attacker.example/connectors-oauth-exchange-code/",
        "https://attacker@grok.com/connectors-oauth-exchange-code/",
    ],
)
def test_other_grok_redirect_targets_remain_blocked(uri):
    assert not is_allowed_redirect_uri(uri)


def test_authorize_validator_accepts_grok_and_still_rejects_external_redirects():
    import norman_mcp.server  # noqa: F401 (installs the authorization validator)

    client = OAuthClientInformationFull(
        client_id="grok-callback-regression", redirect_uris=[GROK_CALLBACK]
    )
    assert str(client.validate_redirect_uri(GROK_CALLBACK)) == GROK_CALLBACK
    with pytest.raises(InvalidRedirectUriError, match="redirect_uri not allowed"):
        client.validate_redirect_uri("https://attacker.example/steal")
