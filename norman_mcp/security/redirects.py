"""Transport-level validation for dynamically registered OAuth redirects.

Remote MCP clients register their callback URIs through Dynamic Client
Registration. The OAuth SDK then requires an exact match between the redirect
used by ``/authorize`` and the URI stored for that client. This module only
enforces rules that apply independently of a specific platform:

* HTTPS callbacks are accepted.
* HTTP is accepted only for loopback clients (RFC 8252 section 7.3).
* Custom schemes are accepted for native-app deep links.

There is deliberately no vendor/domain list here. Perplexity, Gemini, Grok, and
future clients can register their own exact callback without a server release.
"""

from urllib.parse import urlparse

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def is_allowed_redirect_uri(uri: str) -> bool:
    """Return whether ``uri`` is safe to store during client registration."""
    if not uri:
        return False
    try:
        parsed = urlparse(str(uri))
    except Exception:
        return False

    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()

    if scheme == "http":
        return host in _LOOPBACK_HOSTS
    if scheme == "https":
        return bool(host)
    if scheme and scheme not in ("http", "https"):
        # Custom scheme: native-app deep link (cursor://, vscode://, ...).
        # These can only be intercepted by a handler installed on the user's own
        # machine, so they are not a remote-exfiltration vector.
        return True
    return False
