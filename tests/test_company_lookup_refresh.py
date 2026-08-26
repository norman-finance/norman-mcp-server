"""The company lookup must survive an expired Norman access token.

Norman access tokens live one hour. Almost every tool reads `api.company_id`
first, to build its company-scoped URL, so the lookup runs before any
`_make_request` and cannot inherit that method's transparent refresh. Without
its own 401 handling the lookup returned None and the user was told
"No company available. Please authenticate first." about an hour after
connecting -- reported as "permanent authentication must be possible".
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from norman_mcp import context
from norman_mcp.api import client as client_module
from norman_mcp.api.client import NormanAPI

EXPIRED = "norman_expired"
FRESH = "norman_fresh"


@pytest.fixture(autouse=True)
def disable_actual_api_calls():
    """Override the global autouse fixture: these tests need real HTTP."""
    yield


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        path = urlparse(self.path).path
        self.server.seen.append((path, token))

        if token == EXPIRED:
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        body = {"results": [{"publicId": f"company-of-{token}"}]}
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class _Provider:
    """Mimics the provider: the stored Norman token is stale until refreshed."""

    def __init__(self, refreshable=True):
        self.token_mapping = {"mcp_a": EXPIRED}
        self.refreshable = refreshable
        self.refresh_calls = 0

    def get_norman_token(self, mcp_token):
        return self.token_mapping.get(mcp_token)

    def refresh_norman_token_sync(self, mcp_token):
        self.refresh_calls += 1
        if not self.refreshable:
            return None
        self.token_mapping[mcp_token] = FRESH
        return FRESH

    def get_company_for_token(self, mcp_token):
        return None

    def set_company_for_token(self, mcp_token, company_id):
        pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.seen = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def _wire(monkeypatch, server, provider):
    host, port = server.server_address[:2]

    class _Cfg:
        api_base_url = f"http://{host}:{port}/"
        NORMAN_API_TIMEOUT = 10

    monkeypatch.setattr(client_module, "config", _Cfg())
    monkeypatch.setattr(context, "oauth_provider", provider)


def _in_request(fn):
    out, errors = {}, []

    def run():
        try:
            auth_context_var.set(
                AuthenticatedUser(AccessToken(token="mcp_a", client_id="c", scopes=["read"]))
            )
            out["value"] = fn()
        except BaseException as exc:
            errors.append(exc)

    t = threading.Thread(target=run)
    t.start()
    t.join(timeout=30)
    if errors:
        raise errors[0]
    return out.get("value")


def test_expired_token_is_refreshed_and_company_resolves(monkeypatch, server):
    provider = _Provider()
    _wire(monkeypatch, server, provider)

    api = NormanAPI(authenticate_on_init=False)
    api.token_source = "oauth"

    assert _in_request(lambda: api.company_id) == f"company-of-{FRESH}"
    assert provider.refresh_calls == 1
    assert [t for _, t in server.seen] == [EXPIRED, FRESH]


def test_refresh_is_attempted_only_once(monkeypatch, server):
    """A token that stays rejected must not loop."""
    provider = _Provider()
    provider.refresh_norman_token_sync = lambda mcp_token: EXPIRED  # never fixes it
    _wire(monkeypatch, server, provider)

    api = NormanAPI(authenticate_on_init=False)
    api.token_source = "oauth"

    assert _in_request(lambda: api.company_id) is None
    assert [t for _, t in server.seen] == [EXPIRED, EXPIRED]


def test_unrefreshable_session_reports_no_company(monkeypatch, server):
    provider = _Provider(refreshable=False)
    _wire(monkeypatch, server, provider)

    api = NormanAPI(authenticate_on_init=False)
    api.token_source = "oauth"

    assert _in_request(lambda: api.company_id) is None
    assert provider.refresh_calls == 1
