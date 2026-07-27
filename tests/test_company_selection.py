"""Per-caller persistence of the active company (switch_company).

`switch_company` promises that "all subsequent tool calls will operate on the
selected company". It used to keep that promise by writing `company_id` onto the
shared `NormanAPI` instance -- the same shared mutable state that leaked
companies between users, and which stopped persisting at all once the client
became per-request.

The selection now lives in `NormanOAuthProvider.token_to_company_id`, keyed by
the caller's own MCP token. These tests pin down both halves: it survives across
requests for the caller, and it is invisible to everyone else.
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

TOKEN_MAP = {"mcp_a": "norman_a", "mcp_b": "norman_b"}


@pytest.fixture(autouse=True)
def disable_actual_api_calls():
    """Override the global autouse fixture: these tests need real HTTP."""
    yield


class _FakeNormanHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        path = urlparse(self.path).path
        self.server.seen.append((path, token))

        # Companies the caller has no access to: the real API scopes the detail
        # endpoint by request.user, so an unreachable company 404s.
        denied = getattr(self.server, "deny", set())
        if any(f"/companies/{d}/" in path for d in denied):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if path == "/api/v1/companies/":
            body = {"results": [{"publicId": f"default-of-{token}"}]}
        else:
            body = {"results": [{"owner_token": token}], "path": path}

        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class _FakeProvider:
    """Stands in for NormanOAuthProvider's token + company registry."""

    def __init__(self, mapping):
        self.token_mapping = dict(mapping)
        self.token_to_company_id = {}
        self.saves = 0

    def get_norman_token(self, mcp_token):
        return self.token_mapping.get(mcp_token)

    def get_company_for_token(self, mcp_token):
        return self.token_to_company_id.get(mcp_token)

    def set_company_for_token(self, mcp_token, company_id):
        if not mcp_token:
            return
        if company_id:
            if self.token_to_company_id.get(mcp_token) == company_id:
                return
            self.token_to_company_id[mcp_token] = company_id
        elif mcp_token in self.token_to_company_id:
            del self.token_to_company_id[mcp_token]
        else:
            return
        self.saves += 1


@pytest.fixture
def fake_norman():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeNormanHandler)
    server.seen = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def provider(fake_norman, monkeypatch):
    host, port = fake_norman.server_address[:2]

    class _Cfg:
        api_base_url = f"http://{host}:{port}/"
        NORMAN_API_TIMEOUT = 10

    prov = _FakeProvider(TOKEN_MAP)
    monkeypatch.setattr(client_module, "config", _Cfg())
    monkeypatch.setattr(context, "oauth_provider", prov)
    return prov


def _serve_request(api, provider, mcp_token, norman_token, body):
    """Run `body` in a fresh thread == a fresh request context.

    Mirrors the real request path: the auth middleware seeds the token, then
    `load_access_token` seeds any saved company selection for this caller.
    """
    result = {}
    errors = []

    def run():
        try:
            auth_context_var.set(
                AuthenticatedUser(
                    AccessToken(token=mcp_token, client_id="c", scopes=["read"])
                )
            )
            context.set_api_token(norman_token)
            saved = provider.get_company_for_token(mcp_token)
            if saved:
                context.set_api_company_id(saved)
            result["value"] = body()
        except BaseException as exc:
            errors.append(exc)

    t = threading.Thread(target=run)
    t.start()
    t.join(timeout=30)
    if errors:
        raise errors[0]
    return result.get("value")


def test_selection_survives_the_next_request(provider):
    """A switch in request 1 is still active in request 2."""
    api = NormanAPI(authenticate_on_init=False)
    api.token_source = "oauth"

    _serve_request(api, provider, "mcp_a", "norman_a", lambda: api.set_company("CO-CHOSEN"))
    later = _serve_request(api, provider, "mcp_a", "norman_a", lambda: api.company_id)

    assert later == "CO-CHOSEN", "switch_company did not outlive the request"


def test_selection_is_not_visible_to_another_user(provider):
    """One caller's switch must not change anyone else's active company."""
    api = NormanAPI(authenticate_on_init=False)
    api.token_source = "oauth"

    _serve_request(api, provider, "mcp_a", "norman_a", lambda: api.set_company("CO-OF-A"))

    b_sees = _serve_request(api, provider, "mcp_b", "norman_b", lambda: api.company_id)
    a_sees = _serve_request(api, provider, "mcp_a", "norman_a", lambda: api.company_id)

    assert b_sees == "default-of-norman_b", "user B inherited another user's selection"
    assert a_sees == "CO-OF-A"


def test_concurrent_switches_do_not_cross(provider):
    """Two users switching at the same time keep their own selections."""
    api = NormanAPI(authenticate_on_init=False)
    api.token_source = "oauth"

    barrier = threading.Barrier(2)

    def switcher(mcp_token, norman_token, company):
        def body():
            def inner():
                barrier.wait(timeout=10)
                return api.set_company(company)

            return _serve_request(api, provider, mcp_token, norman_token, inner)

        return body

    threads = [
        threading.Thread(target=switcher("mcp_a", "norman_a", "CO-A")),
        threading.Thread(target=switcher("mcp_b", "norman_b", "CO-B")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert provider.token_to_company_id == {"mcp_a": "CO-A", "mcp_b": "CO-B"}


def test_default_company_is_not_persisted_as_a_choice(provider):
    """The lazy "first company" fallback must not look like a switch.

    Otherwise the first request would freeze the caller's default company into
    the state file, and a later change of their default would never be picked up.
    """
    api = NormanAPI(authenticate_on_init=False)
    api.token_source = "oauth"

    resolved = _serve_request(api, provider, "mcp_a", "norman_a", lambda: api.company_id)

    assert resolved == "default-of-norman_a"
    assert provider.token_to_company_id == {}, "a default was persisted as a selection"
    assert provider.saves == 0


def test_switch_company_does_not_persist_a_company_it_cannot_reach(provider, fake_norman):
    """An inaccessible company must not be recorded as the active one.

    The company id is sent as the `company` field when creating transactions, so
    pinning an arbitrary one onto your own session must not be possible. The
    server scopes /companies/{id}/ by the requesting user, and the tool has to
    respect that answer before persisting.
    """
    import asyncio

    from mcp.server.fastmcp import FastMCP

    from norman_mcp.tools import tax_advisor as tax_advisor_module
    from norman_mcp.tools.tax_advisor import register_tax_advisor_tools

    # The tool builds URLs from its own module-level config import.
    monkey_cfg = client_module.config
    original = tax_advisor_module.config
    tax_advisor_module.config = monkey_cfg

    srv = FastMCP()
    register_tax_advisor_tools(srv)
    switch_company = srv._tool_manager._tools["switch_company"].fn

    api = NormanAPI(authenticate_on_init=False)
    api.token_source = "oauth"

    class _Ctx:
        class request_context:  # noqa: N801 - mirrors the MCP Context shape
            lifespan_context = {"api": api}

    fake_norman.deny = {"CO-FOREIGN"}
    try:
        result = _serve_request(
            api,
            provider,
            "mcp_a",
            "norman_a",
            lambda: asyncio.run(switch_company(_Ctx(), company_id="CO-FOREIGN")),
        )
    finally:
        tax_advisor_module.config = original
        fake_norman.deny = set()

    assert "error" in result, f"switch reported success for an inaccessible company: {result}"
    assert result.get("activeCompanyId") is None
    assert provider.token_to_company_id == {}, "persisted a company the caller cannot reach"


def test_selection_is_reused_without_refetching(provider, fake_norman):
    """A saved selection short-circuits the /companies/ lookup."""
    api = NormanAPI(authenticate_on_init=False)
    api.token_source = "oauth"

    _serve_request(api, provider, "mcp_a", "norman_a", lambda: api.set_company("CO-CHOSEN"))

    def count_lookups():
        return sum(1 for path, _ in fake_norman.seen if path == "/api/v1/companies/")

    before = count_lookups()
    _serve_request(api, provider, "mcp_a", "norman_a", lambda: api.company_id)

    assert count_lookups() == before, "re-resolved the company despite a saved selection"
