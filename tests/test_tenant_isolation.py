"""Cross-tenant isolation regression tests.

Background: `_api_token` used to be a module global, and `NormanAPI._make_request`
copied it onto the shared client instance (`self.access_token`). With one swarm
replica serving every user in `--stateless` mode, two concurrent requests raced
on that single global: user A's tool call could go out carrying user B's Norman
bearer token, and the Norman API -- correctly scoping by the token's own user --
returned B's company data to A.

This exact defect was fixed once before and then reverted, with its test file
deleted. These tests are the guard: if per-request identity moves back onto
shared state, `test_concurrent_users_do_not_share_tokens` fails.

Real threads and a real (loopback) HTTP server are used deliberately. Blocking
tool calls run in a worker thread in production, and a fresh thread starts with
an empty contextvars Context -- so ContextVar-backed identity isolates, while a
module global does not. That difference is exactly what these tests assert.
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

# mcp token -> norman token, as the OAuth provider stores it
TOKEN_MAP = {"mcp_a": "norman_a", "mcp_b": "norman_b"}


@pytest.fixture(autouse=True)
def disable_actual_api_calls():
    """Override the global autouse fixture: these tests need real HTTP.

    conftest patches `requests.request`, which is the call under test here. The
    requests only ever reach a loopback stub started by the `fake_norman`
    fixture.
    """
    yield


class _FakeNormanHandler(BaseHTTPRequestHandler):
    """Minimal stand-in for the Norman API that reports which token it saw."""

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        auth = self.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        path = urlparse(self.path).path

        self.server.seen.append((path, token))

        if path == "/api/v1/companies/":
            body = {"results": [{"publicId": f"company-of-{token}"}]}
        else:
            # Mirrors the real API: results follow the *token*, not the URL path
            # (CompanyContextMixin resolves the company from request.user, and
            # ignores the company_pk in the URL entirely).
            body = {"results": [{"owner_token": token}], "path": path}

        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # silence test output
        pass


class _FakeProvider:
    """Stands in for NormanOAuthProvider's token registry."""

    def __init__(self, mapping):
        self.token_mapping = dict(mapping)

    def get_norman_token(self, mcp_token):
        return self.token_mapping.get(mcp_token)


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
def base_url(fake_norman):
    host, port = fake_norman.server_address[:2]
    return f"http://{host}:{port}/"


@pytest.fixture
def wired(fake_norman, base_url, monkeypatch):
    """Point the client at the fake API and install the fake provider."""

    class _Cfg:
        api_base_url = base_url
        NORMAN_API_TIMEOUT = 10

    monkeypatch.setattr(client_module, "config", _Cfg())
    monkeypatch.setattr(context, "oauth_provider", _FakeProvider(TOKEN_MAP))
    return fake_norman


def _enter_request(mcp_token, norman_token):
    """Do what the SDK auth middleware + load_access_token do per request."""
    auth_context_var.set(
        AuthenticatedUser(
            AccessToken(token=mcp_token, client_id="test-client", scopes=["read"])
        )
    )
    context.set_api_token(norman_token)


def _run_concurrently(bodies):
    """Run each body in its own thread (= its own empty context), collect errors."""
    errors = []

    def guard(fn):
        def wrapper():
            try:
                fn()
            except BaseException as exc:  # surface in the main thread
                errors.append(exc)

        return wrapper

    threads = [threading.Thread(target=guard(b)) for b in bodies]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    if errors:
        raise errors[0]


def test_concurrent_users_do_not_share_tokens(wired, base_url):
    """Two users racing on one shared client must each use their OWN token.

    The barrier forces the interleaving that used to lose the race: both users
    publish their token before either performs its HTTP call. Under the old
    module-global implementation, both outbound requests carried whichever token
    was written last.
    """
    # One shared instance, as the SSE/stateful transports reuse.
    api = NormanAPI(authenticate_on_init=False)
    api.token_source = "oauth"

    barrier = threading.Barrier(2)
    results = {}

    def one_user(mcp_token, norman_token):
        def body():
            _enter_request(mcp_token, norman_token)
            # Both tokens are now published; whoever reads shared state loses.
            barrier.wait(timeout=10)
            results[mcp_token] = api._make_request(
                "GET",
                f"{base_url}api/v1/companies/{api.company_id}/accounting/transactions/",
            )

        return body

    _run_concurrently([one_user("mcp_a", "norman_a"), one_user("mcp_b", "norman_b")])

    assert results["mcp_a"]["results"][0]["owner_token"] == "norman_a", (
        "user A's request went out with another user's token -- cross-tenant leak"
    )
    assert results["mcp_b"]["results"][0]["owner_token"] == "norman_b", (
        "user B's request went out with another user's token -- cross-tenant leak"
    )


def test_company_id_is_not_pinned_across_users(wired):
    """company_id must be resolved per request, not pinned by the first caller."""
    api = NormanAPI(authenticate_on_init=False)
    api.token_source = "oauth"

    barrier = threading.Barrier(2)
    seen = {}

    def one_user(mcp_token, norman_token):
        def body():
            _enter_request(mcp_token, norman_token)
            barrier.wait(timeout=10)
            seen[mcp_token] = api.company_id

        return body

    _run_concurrently([one_user("mcp_a", "norman_a"), one_user("mcp_b", "norman_b")])

    assert seen["mcp_a"] == "company-of-norman_a"
    assert seen["mcp_b"] == "company-of-norman_b"


def test_request_identity_never_cached_on_shared_instance(wired, base_url):
    """A completed OAuth request must leave no identity behind on the client."""
    api = NormanAPI(authenticate_on_init=False)
    api.token_source = "oauth"

    def body():
        _enter_request("mcp_a", "norman_a")
        api._make_request(
            "GET", f"{base_url}api/v1/companies/x/accounting/transactions/"
        )

    _run_concurrently([body])

    assert api.access_token is None, (
        "request token was cached on the shared client -- this is the leak vector"
    )
    assert api._env_company_id is None, (
        "request company id was cached on the shared client"
    )


def test_single_tenant_stdio_token_still_works(wired, base_url):
    """stdio/env mode keeps its token on the instance across tasks and threads.

    Guards the flip side of the fix: making OAuth identity request-scoped must
    not break the single-user stdio deployment, where there is no auth context
    and no per-request token to resolve from.
    """
    api = NormanAPI(authenticate_on_init=False)
    api.set_token("norman_solo", single_tenant=True)

    assert api.token_source == "env"
    assert api.company_id == "company-of-norman_solo"

    out = {}

    def body():  # a different thread => a fresh, empty context
        out["res"] = api._make_request(
            "GET", f"{base_url}api/v1/companies/x/accounting/transactions/"
        )

    _run_concurrently([body])

    assert out["res"]["results"][0]["owner_token"] == "norman_solo"


def test_unauthenticated_request_gets_no_token(wired, base_url):
    """With no auth context and no request-scoped token, refuse to call the API.

    Guards the other half of the bug: falling back to leftover shared state when
    the caller's own identity is missing.
    """
    api = NormanAPI(authenticate_on_init=False)
    api.token_source = "oauth"

    result = {}

    def body():
        # No _enter_request(): no auth context, no request token.
        result["out"] = api._make_request(
            "GET", f"{base_url}api/v1/companies/x/accounting/transactions/"
        )

    _run_concurrently([body])

    assert "error" in result["out"]
    assert wired.seen == [], "made an API call without a caller identity"
