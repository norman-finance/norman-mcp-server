"""Redirect URI allow-listing for the MCP authorization server.

Norman's MCP server is a *delegated* OAuth Authorization Server: it sends the
user to Norman's real OAuth server to authenticate, then redirects the issued
authorization code back to the client's ``redirect_uri``. Because the consent
the user sees lives on Norman's domain (and only ever shows the legitimate
``mcp.norman.finance/oauth/callback`` destination), the user has no way to see
the *final* redirect target. If we accepted arbitrary ``redirect_uri`` values,
an attacker could register a client pointing at their own server, phish a victim
through the otherwise-trustworthy Norman consent flow, and receive an
authorization code that maps to the victim's Norman token — full account
takeover.

To close that path we only allow redirect targets that are actually used by
legitimate MCP clients:

* HTTP loopback (localhost / 127.0.0.1 / [::1]) on any port — RFC 8252 §7.3,
  needed by native clients and the MCP Inspector that bind random local ports.
* Custom (non-http) schemes — native-app deep links (e.g. ``cursor://``).
* HTTPS only for an explicit host allow-list (known connector origins),
  extensible via the ``NORMAN_MCP_ALLOWED_REDIRECT_HOSTS`` env var.

Everything else — notably plain ``https://attacker.com/...`` — is rejected.
"""

import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# HTTPS redirect hosts that ship as allowed by default. These are the origins
# of the MCP clients we actually support (and Norman's own callback host).
# Matching is exact host OR a subdomain of one of these (e.g. mcp.norman.finance
# matches "norman.finance").
_DEFAULT_ALLOWED_HTTPS_HOSTS = {
    "norman.finance",
    "chatgpt.com",
    "claude.ai",
    "claude.com",
}

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _allowed_https_hosts() -> set[str]:
    """Return the configured HTTPS host allow-list (defaults + env extension)."""
    hosts = set(_DEFAULT_ALLOWED_HTTPS_HOSTS)
    extra = os.environ.get("NORMAN_MCP_ALLOWED_REDIRECT_HOSTS", "")
    for host in extra.split(","):
        host = host.strip().lower()
        if host:
            hosts.add(host)
    return hosts


def _host_is_allowed(host: str) -> bool:
    host = (host or "").lower()
    if not host:
        return False
    for allowed in _allowed_https_hosts():
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def is_allowed_redirect_uri(uri: str) -> bool:
    """Return True if ``uri`` is an acceptable OAuth redirect target.

    Used both at Dynamic Client Registration time and (authoritatively) when
    validating the ``redirect_uri`` on an /authorize request.
    """
    if not uri:
        return False
    try:
        parsed = urlparse(str(uri))
    except Exception:
        return False

    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()

    if scheme == "http":
        # Only loopback HTTP is acceptable (RFC 8252). Any other HTTP host is
        # rejected — both because it is an insecure transport and because a
        # remote HTTP host is a valid code-exfiltration target.
        return host in _LOOPBACK_HOSTS
    if scheme == "https":
        return _host_is_allowed(host)
    if scheme and scheme not in ("http", "https"):
        # Custom scheme: native-app deep link (cursor://, vscode://, ...).
        # These can only be intercepted by a handler installed on the user's own
        # machine, so they are not a remote-exfiltration vector.
        return True
    return False
