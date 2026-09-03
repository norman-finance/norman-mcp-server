"""Redirect-URI allow-list tests (OAuth authorization-code phishing defense)."""

import pytest

from norman_mcp.security.redirects import is_allowed_redirect_uri


def test_rejects_external_https():
    # The reported attack: attacker-controlled HTTPS exfiltration target.
    assert is_allowed_redirect_uri("https://attacker.com/steal") is False
    assert is_allowed_redirect_uri("https://norman.finance.attacker.com/cb") is False


def test_allows_known_connector_https_hosts():
    assert is_allowed_redirect_uri("https://chatgpt.com/connector_platform_oauth_redirect")
    assert is_allowed_redirect_uri("https://claude.ai/api/mcp/auth_callback")
    # Subdomain of an allow-listed base domain.
    assert is_allowed_redirect_uri("https://mcp.norman.finance/oauth/callback")


def test_allows_http_loopback_any_port():
    assert is_allowed_redirect_uri("http://localhost:6274/oauth/callback")
    assert is_allowed_redirect_uri("http://127.0.0.1:51763/callback")
    assert is_allowed_redirect_uri("http://[::1]:6274/cb")


def test_rejects_plain_http_to_remote_host():
    assert is_allowed_redirect_uri("http://attacker.com/steal") is False


def test_allows_custom_native_scheme():
    assert is_allowed_redirect_uri("cursor://anysphere.cursor/callback")


def test_env_extension_adds_hosts(monkeypatch):
    monkeypatch.setenv("NORMAN_MCP_ALLOWED_REDIRECT_HOSTS", "partner.example, other.test")
    assert is_allowed_redirect_uri("https://partner.example/cb")
    assert is_allowed_redirect_uri("https://api.partner.example/cb")
    assert is_allowed_redirect_uri("https://other.test/cb")


def test_empty_or_garbage_rejected():
    assert is_allowed_redirect_uri("") is False
    assert is_allowed_redirect_uri("not a url") is False


def test_sdk_validate_patch_enforces_allowlist():
    """Importing the server monkeypatches the SDK validator to the allow-list.

    Critically, this rejects a disallowed URI even when the client has it in its
    own registered redirect_uris (open DCR lets an attacker self-register it).
    """
    import norman_mcp.server  # noqa: F401  (applies the monkeypatch on import)
    from mcp.shared.auth import OAuthClientInformationFull, InvalidRedirectUriError

    fn = OAuthClientInformationFull.validate_redirect_uri

    class _DummyClient:
        # Even though the attacker "registered" attacker.com, it must be rejected.
        redirect_uris = ["https://attacker.com/steal"]

    with pytest.raises(InvalidRedirectUriError):
        fn(_DummyClient(), "https://attacker.com/steal")

    assert fn(_DummyClient(), "https://chatgpt.com/cb") == "https://chatgpt.com/cb"
