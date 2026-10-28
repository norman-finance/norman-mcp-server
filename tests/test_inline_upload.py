"""Inline upload contracts: identity, per-file direction, once-only writes, UI handoff."""

import asyncio
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from mcp.server.mcpserver import MCPServer
from starlette.applications import Starlette
from starlette.datastructures import UploadFile
from starlette.testclient import TestClient

from norman_mcp.apps.document_upload import UPLOAD_URI, register_upload_app
from norman_mcp.files import inline_upload as upload


class Provider:
    def __init__(self):
        self.tokens = {
            "token-a": SimpleNamespace(
                token="token-a", client_id="client-a", expires_at=time.time() + 3600
            )
        }
        self.selected = "company-a"
        self.norman = "norman-a"

    def grant_for_token(self, token):
        return "grant-a" if token in ("token-a", "token-refreshed") else "grant-other"

    def get_company_for_token(self, token):
        return self.selected

    def get_norman_token(self, token):
        return self.norman if token in self.tokens else None

    def refresh_norman_token_sync(self, token):
        self.norman = "refreshed-norman"
        return self.norman


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_UPLOAD_STATE_FILE", str(tmp_path / "uploads.db"))
    provider = Provider()
    monkeypatch.setattr(upload, "get_oauth_provider", lambda: provider)
    store = upload.UploadStore()
    sid, ticket = store.create(
        upload.grant_key(provider, provider.tokens["token-a"]),
        "company-a",
        "company-a",
        "Example sp. z o.o.",
        "PL",
    )
    client = TestClient(Starlette(routes=upload.create_inline_upload_routes()))
    return provider, store, sid, ticket, client


def post(
    client,
    ticket,
    *,
    file_id="file_123456789012345",
    flow="EXPENSE",
    data=b"%PDF-1.4 test",
    name="receipt.pdf",
):
    return client.post(
        "/files/upload-app/file",
        headers={"Authorization": "Bearer " + ticket},
        data={"file_id": file_id, "cashflow_type": flow},
        files={"file": (name, data, "application/pdf")},
    )


def test_mixed_batch_pins_company_and_preserves_each_direction(setup, monkeypatch):
    provider, store, sid, ticket, client = setup
    calls = []

    async def save(p, access, company, file, name, flow):
        calls.append((access.token, company, name, flow, await file.read()))
        return {
            "status": "uploaded",
            "attachment_id": str(len(calls)),
            "processing_status": "pending",
        }

    monkeypatch.setattr(upload, "post_attachment", save)
    assert post(client, ticket).json()["status"] == "uploaded"
    assert (
        post(
            client, ticket, file_id="file_223456789012345", flow="INCOME", data=b"%PDF sale"
        ).json()["status"]
        == "uploaded"
    )
    assert [(c[1], c[3]) for c in calls] == [("company-a", "EXPENSE"), ("company-a", "INCOME")]
    summary = client.get(
        "/files/upload-app/session", headers={"Authorization": "Bearer " + ticket}
    ).json()
    assert summary["uploaded_count"] == 2
    assert [f["cashflow_type"] for f in summary["files"]] == ["EXPENSE", "INCOME"]
    assert all(f["processing_status"] == "pending" for f in summary["files"])
    assert "token-a" not in json.dumps(summary)
    assert upload.UploadStore(store.path).summary(store.session(session_id=sid)) == summary


def test_missing_or_invalid_ticket_and_cross_company_fail_before_write(setup, monkeypatch):
    provider, store, sid, ticket, client = setup

    async def fail(*args):
        pytest.fail("must not write")

    monkeypatch.setattr(upload, "post_attachment", fail)
    assert post(client, "wrong-ticket").status_code == 410
    assert client.post("/files/upload-app/file").status_code == 401
    provider.selected = "company-b"
    assert post(client, ticket).status_code == 409
    assert (
        client.get(
            "/files/upload-app/session", headers={"Authorization": "Bearer " + ticket}
        ).status_code
        == 409
    )


@pytest.mark.parametrize("change", ["expired", "revoked", "missing-norman"])
def test_expired_or_revoked_grant_denies_upload(setup, change):
    provider, store, sid, ticket, client = setup
    if change == "expired":
        provider.tokens["token-a"].expires_at = time.time() - 1
    elif change == "revoked":
        provider.tokens.clear()
    else:
        provider.norman = None
    assert post(client, ticket).status_code in (401, 409)
    assert not store.summary(store.session(session_id=sid))["files"]


def test_expired_session_and_refreshed_token(setup):
    provider, store, sid, ticket, client = setup
    old = provider.tokens.pop("token-a")
    provider.tokens["token-refreshed"] = SimpleNamespace(
        token="token-refreshed", client_id=old.client_id, expires_at=time.time() + 3600
    )
    assert upload.current_access(store.session(session_id=sid), provider).token == "token-refreshed"
    with store.connect() as db:
        db.execute("UPDATE sessions SET expires=?", (time.time() - 1,))
    assert post(client, ticket).status_code == 410


@pytest.mark.parametrize("status", ["uploaded", "unknown", "rejected"])
def test_repeated_file_id_never_repeats_upstream_write(setup, monkeypatch, status):
    _, store, sid, ticket, client = setup
    calls = []

    async def save(*args):
        calls.append(1)
        return (
            {"status": status, "attachment_id": "doc-a"}
            if status == "uploaded"
            else {"status": status, "error": "Try checking the result."}
        )

    monkeypatch.setattr(upload, "post_attachment", save)
    first = post(client, ticket).json()
    assert post(client, ticket).json() == first
    assert len(calls) == 1
    assert post(client, ticket, flow="INCOME").status_code == 409
    assert post(client, ticket, file_id="file_99999999999999").status_code == 409


def test_atomic_reservation_across_store_instances_and_restart(setup):
    _, store, sid, ticket, _ = setup
    session = store.session(session_id=sid)

    def reserve(_):
        return upload.UploadStore(store.path).reserve(
            session, "file_a", "a.pdf", 10, "sha", "INCOME"
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, range(4)))
    assert sum(r is None for r in results) == 1
    assert all(r is None or r["status"] == "unknown" for r in results)


@pytest.mark.parametrize(
    "flow,name,data",
    [
        ("AUTO", "a.pdf", b"pdf"),
        ("", "a.pdf", b"pdf"),
        ("EXPENSE", "evil.html", b"html"),
        ("INCOME", "empty.pdf", b""),
    ],
)
def test_invalid_file_or_unselected_direction_cannot_create_attachment(setup, flow, name, data):
    _, store, sid, ticket, client = setup
    assert post(client, ticket, flow=flow, name=name, data=data).status_code == 400
    assert not store.summary(store.session(session_id=sid))["files"]


def test_size_limits_and_clean_filename(setup, monkeypatch):
    _, store, sid, ticket, client = setup
    monkeypatch.setattr(upload, "MAX_FILE_SIZE", 16)
    assert post(client, ticket, data=b"x" * 17).status_code == 413
    seen = []

    async def save(p, a, c, f, n, flow):
        seen.append(n)
        return {"status": "uploaded", "attachment_id": "doc-a"}

    monkeypatch.setattr(upload, "post_attachment", save)
    assert post(client, ticket, name="../../receipt.pdf").status_code == 200
    assert seen == ["receipt.pdf"]
    assert post(client, ticket, data=b"x" * 70000).status_code == 413


def test_session_file_and_size_quota(setup, monkeypatch):
    _, store, sid, ticket, _ = setup
    session = store.session(session_id=sid)
    monkeypatch.setattr(upload, "MAX_FILES", 1)
    store.reserve(session, "file_a", "a.pdf", 12, "a", "INCOME")
    with pytest.raises(upload.UploadError):
        store.reserve(session, "file_b", "b.pdf", 12, "b", "EXPENSE")


@pytest.mark.parametrize("response_status", [201, 400, 500, 302])
def test_api_request_contract_and_ambiguous_status(setup, monkeypatch, response_status):
    provider, *_ = setup
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(response_status, json={"publicId": "doc-a"})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        upload.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    file = UploadFile(io.BytesIO(b"%PDF example"), filename="sale.pdf")
    result = asyncio.run(
        upload.post_attachment(
            provider, provider.tokens["token-a"], "company-a", file, "sale.pdf", "INCOME"
        )
    )
    assert len(requests) == 1
    request = requests[0]
    assert request.headers["authorization"] == "Bearer norman-a"
    assert request.headers["x-company-id"] == "company-a"
    assert request.url.path == "/api/v1/companies/company-a/attachments/"
    assert b'name="cashflow_type"\r\n\r\nINCOME' in request.content
    assert b'name="attachment_type"\r\n\r\ninvoice' in request.content
    assert (
        result["status"]
        == {201: "uploaded", 400: "rejected", 500: "unknown", 302: "unknown"}[response_status]
    )


def test_timeout_does_not_repeat_api_post(setup, monkeypatch):
    provider, *_ = setup
    requests = []

    async def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("timeout")

    original = httpx.AsyncClient
    monkeypatch.setattr(
        upload.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    file = UploadFile(io.BytesIO(b"%PDF example"), filename="sale.pdf")
    result = asyncio.run(
        upload.post_attachment(
            provider, provider.tokens["token-a"], "company-a", file, "sale.pdf", "EXPENSE"
        )
    )
    assert result["status"] == "unknown"
    assert len(requests) == 1


@pytest.mark.parametrize("second_status", [201, 401])
def test_only_definitive_401_refreshes_once(setup, monkeypatch, second_status):
    provider, *_ = setup
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(
            401 if len(requests) == 1 else second_status, json={"publicId": "doc-a"}
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        upload.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    file = UploadFile(io.BytesIO(b"%PDF example"), filename="sale.pdf")
    result = asyncio.run(
        upload.post_attachment(
            provider, provider.tokens["token-a"], "company-a", file, "sale.pdf", "INCOME"
        )
    )
    assert len(requests) == 2
    assert requests[0].headers["authorization"] == "Bearer norman-a"
    assert requests[1].headers["authorization"] == "Bearer refreshed-norman"
    assert all(b"%PDF example" in request.content for request in requests)
    assert result["status"] == ("uploaded" if second_status == 201 else "rejected")


def test_panel_total_bytes_and_active_session_limits(setup, monkeypatch):
    provider, store, sid, _, _ = setup
    session = store.session(session_id=sid)
    monkeypatch.setattr(upload, "MAX_TOTAL_SIZE", 20)
    store.reserve(session, "file_a", "a.pdf", 12, "a", "INCOME")
    with pytest.raises(upload.UploadError) as error:
        store.reserve(session, "file_b", "b.pdf", 9, "b", "EXPENSE")
    assert error.value.status == 413
    grant = upload.grant_key(provider, provider.tokens["token-a"])
    for _ in range(7):
        store.create(grant, "company-a", "company-a", "Example", "PL")
    with pytest.raises(upload.UploadError) as error:
        store.create(grant, "company-a", "company-a", "Example", "PL")
    assert error.value.status == 429


def test_tool_metadata_and_result_are_grant_scoped(setup, monkeypatch):
    from norman_mcp.apps import document_upload as app

    provider, store, sid, ticket, client = setup
    monkeypatch.setattr(app, "get_oauth_provider", lambda: provider)
    access = provider.tokens["token-a"]
    monkeypatch.setattr(app, "get_access_token", lambda: access)

    class API:
        company_id = "company-a"

        async def arequest(self, *args):
            return {"name": "Example", "country": "PL"}

    api = API()
    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))
    mcp = MCPServer()
    register_upload_app(mcp)
    open_tool = mcp._tool_manager._tools["request_file_upload"]
    assert open_tool.meta["ui"]["resourceUri"] == UPLOAD_URI
    result = asyncio.run(open_tool.fn(ctx, description="Receipts"))
    data = result.structured_content
    assert data["company_id"] == "company-a"
    assert result.meta["upload"]["ticket"]
    assert "norman-a" not in result.model_dump_json()
    status = mcp._tool_manager._tools["get_file_upload_status"].fn
    assert asyncio.run(status(ctx, sid)).structured_content["uploaded_count"] == 0
    access = SimpleNamespace(token="foreign", client_id="other", expires_at=time.time() + 60)
    assert asyncio.run(status(ctx, sid)).is_error
    access = provider.tokens["token-a"]
    api.company_id = "company-b"
    assert asyncio.run(status(ctx, sid)).is_error


def test_fallback_page_contains_no_credentials_and_is_not_cached(setup):
    *_, client = setup
    page = client.get("/files/upload-app")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["referrer-policy"] == "no-referrer"
    assert "token-a" not in page.text
    assert "file_ref" not in page.text
    assert "Revenue" in page.text and "Expense" in page.text
