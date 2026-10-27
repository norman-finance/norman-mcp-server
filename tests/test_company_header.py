"""The active company travels as `X-Company-Id`, the way the API expects it.

Tools scope most calls through the URL (`/companies/<id>/...`), but every endpoint
that resolves the company server-side reads the header. We used to send a `companyId`
query parameter instead, which the API ignores: those endpoints silently answered for
whichever company the backend picked on its own, not the one `switch_company` chose.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urljoin, urlparse

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from norman_mcp import context
from norman_mcp.api import client as client_module
from norman_mcp.api.client import NormanAPI

MCP_TOKEN = "mcp_a"
NORMAN_TOKEN = "norman_a"


@pytest.fixture(autouse=True)
def disable_actual_api_calls():
    """Override the global autouse fixture: these tests need real HTTP."""
    yield


class _RecordingHandler(BaseHTTPRequestHandler):
    def _record_and_reply(self) -> None:
        parsed = urlparse(self.path)
        self.server.seen.append(
            {
                "path": parsed.path,
                "query": parse_qs(parsed.query),
                "company_header": self.headers.get("X-Company-Id"),
            },
        )
        body = (
            {"results": [{"publicId": "co-default"}]}
            if parsed.path == "/api/v1/companies/"
            else {"ok": True}
        )
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _record_and_reply  # noqa: N815 - BaseHTTPRequestHandler API
    do_POST = _record_and_reply  # noqa: N815

    def log_message(self, *args) -> None:
        pass


class _FakeProvider:
    def __init__(self) -> None:
        self.token_to_company_id: dict[str, str] = {}

    def get_norman_token(self, mcp_token):  # noqa: ANN001, ANN201
        return NORMAN_TOKEN if mcp_token == MCP_TOKEN else None

    def get_company_for_token(self, mcp_token):  # noqa: ANN001, ANN201
        return self.token_to_company_id.get(mcp_token)

    def set_company_for_token(self, mcp_token, company_id):  # noqa: ANN001, ANN201
        if mcp_token and company_id:
            self.token_to_company_id[mcp_token] = company_id


@pytest.fixture
def fake_norman():  # noqa: ANN201
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingHandler)
    server.seen = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def api(fake_norman, monkeypatch):  # noqa: ANN001, ANN201
    host, port = fake_norman.server_address[:2]

    class _Cfg:
        api_base_url = f"http://{host}:{port}/"
        NORMAN_API_TIMEOUT = 10

    monkeypatch.setattr(client_module, "config", _Cfg())
    monkeypatch.setattr(context, "oauth_provider", _FakeProvider())
    client = NormanAPI(authenticate_on_init=False)
    client.token_source = "oauth"
    return client, _Cfg.api_base_url


def _in_request(body):  # noqa: ANN001, ANN202
    """Run `body` in a fresh thread, which is what a fresh request context is."""
    result, errors = {}, []

    def run() -> None:
        try:
            auth_context_var.set(
                AuthenticatedUser(AccessToken(token=MCP_TOKEN, client_id="c", scopes=["read"])),
            )
            context.set_api_token(NORMAN_TOKEN)
            result["value"] = body()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=30)
    if errors:
        raise errors[0]
    return result.get("value")


def test_the_active_company_travels_as_a_header(api, fake_norman) -> None:  # noqa: ANN001
    client, base = api

    _in_request(
        lambda: (
            client.set_company("co-chosen"),
            client._make_request("GET", urljoin(base, "api/v1/accounting/transactions/")),
        ),
    )

    call = next(c for c in fake_norman.seen if c["path"].endswith("/transactions/"))
    assert call["company_header"] == "co-chosen"
    assert "companyId" not in call["query"], "the inert query parameter is still being sent"


@pytest.mark.parametrize("tool,args,path", [
    ("create_bill", {"vendor_name": "Fixture", "amount": 10, "currency": "PLN"}, "/api/v1/accounting/bills/"),
    ("scan_bill_document", {"attachment_id": "doc-fixture"}, "/api/v1/accounting/bills/scan/"),
    ("list_routines", {}, "/api/v1/assistant/routines/"),
    ("confirm_routine", {"routine_id": "routine-fixture"}, "/api/v1/assistant/routines/"),
    ("dismiss_routine", {"routine_id": "routine-fixture"}, "/api/v1/assistant/routines/"),
    ("request_workflow_input", {"run_id": "run-fixture", "step": "review", "question": "Ready?"},
     "/api/v1/assistant/workflow-runs/run-fixture/step/"),
])
def test_new_unscoped_tools_send_selected_company_through_real_http(
    api, fake_norman, monkeypatch, tool, args, path,
):
    from norman_mcp import config
    from tests.mcp_harness import call_tool, structured

    client, base = api
    monkeypatch.setattr(config, "api_base_url", base)
    previous = context.get_api_client()

    def run():
        client.set_company("co-pl-selected")
        return call_tool(tool, args, client)

    try:
        assert structured(_in_request(run)) == {"ok": True}
    finally:
        context.set_api_client(previous)
    calls = [call for call in fake_norman.seen if call["path"] == path]
    assert len(calls) == 1
    assert calls[0]["company_header"] == "co-pl-selected"
    assert "companyId" not in calls[0]["query"]


def test_the_companies_list_is_not_scoped(api, fake_norman) -> None:  # noqa: ANN001
    """Listing companies is how a caller discovers them; scoping it would hide the others."""
    client, base = api

    _in_request(
        lambda: (
            client.set_company("co-chosen"),
            client._make_request("GET", urljoin(base, "api/v1/companies/")),
        ),
    )

    call = next(c for c in fake_norman.seen if c["path"] == "/api/v1/companies/")
    assert call["company_header"] is None


def test_without_a_selection_the_first_listed_company_is_used(
    api, fake_norman
) -> None:  # noqa: ANN001
    """The API orders the list by the caller's own last-active company, so the default
    follows a switch even after the per-token selection was lost to a token refresh."""
    client, base = api

    _in_request(lambda: client._make_request("GET", urljoin(base, "api/v1/invoices/")))

    call = next(c for c in fake_norman.seen if c["path"].endswith("/invoices/"))
    assert call["company_header"] == "co-default"


def test_parallel_explicit_company_requests_do_not_change_the_active_company(api, fake_norman):
    import asyncio
    client, base = api

    async def read_clients():
        await asyncio.gather(*(client.arequest("GET", urljoin(base, "api/v1/taxes/tax-settings/"),
                                               company_id=company_id)
                               for company_id in ("client-a", "client-b")))
        assert client.company_id == "co-chosen"

    _in_request(lambda: (client.set_company("co-chosen"), asyncio.run(read_clients())))
    calls = [c for c in fake_norman.seen if c["path"].endswith("/tax-settings/")]
    assert {call["company_header"] for call in calls} == {"client-a", "client-b"}
