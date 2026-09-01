"""Contract tests for the public connector's portable MCP Apps UI."""

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from mcp.types import CallToolResult

from norman_mcp.apps.public import (
    APP_MIME_TYPE,
    APP_RESOURCE_URI,
    register_public_apps,
)


class FakeMcp:
    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., Any]] = {}
        self.tool_options: dict[str, dict[str, Any]] = {}
        self.resources: dict[str, Callable[..., Any]] = {}
        self.resource_options: dict[str, dict[str, Any]] = {}

    def tool(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        del args

        def register(function: Callable[..., Any]) -> Callable[..., Any]:
            self.tools[function.__name__] = function
            self.tool_options[function.__name__] = kwargs
            return function

        return register

    def resource(
        self, uri: str, **kwargs: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def register(function: Callable[..., Any]) -> Callable[..., Any]:
            self.resources[uri] = function
            self.resource_options[uri] = kwargs
            return function

        return register


class FakeApi:
    company_id = "company-1"

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    async def arequest(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        self.requests.append((method, url, kwargs))
        if url.endswith("/attachments/"):
            return {
                "results": [
                    {
                        "public_id": "doc-1",
                        "file_name": "invoice.pdf",
                        "brand_name": "Acme GmbH",
                        "amount": "119.00",
                        "currency": "EUR",
                        "transactions": [],
                    }
                ]
            }
        if url.endswith("/accounting/transactions/"):
            return {
                "results": [
                    {
                        "public_id": "tx-1",
                        "description": "Acme invoice",
                        "amount": "119.00",
                        "currency": {"code": "EUR"},
                        "user_status": "UNVERIFIED",
                        "company_category": None,
                        "attachment": None,
                    }
                ]
            }
        if url.endswith("/accounting/ledger/accounts/1200/"):
            return {
                "code": "1200",
                "debit_total": "100.00",
                "credit_total": "20.00",
                "saldo": "80.00",
                "results": [
                    {
                        "public_id": "entry-1",
                        "booking_date": "2026-01-03",
                        "debit_code": "1200",
                        "credit_code": "8400",
                        "amount": "100.00",
                        "signed_amount": "100.00",
                        "running_saldo": "100.00",
                    }
                ],
            }
        if url.endswith("/accounting/ledger/accounts/"):
            return {
                "results": [
                    {
                        "code": "1200",
                        "name": "Bank",
                        "debit_total": "100.00",
                        "credit_total": "20.00",
                        "saldo": "80.00",
                    }
                ]
            }
        return {"results": []}


def _context(api: FakeApi) -> SimpleNamespace:
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))


def _registered() -> tuple[FakeMcp, FakeApi]:
    mcp = FakeMcp()
    api = FakeApi()
    register_public_apps(mcp)
    return mcp, api


def test_registers_portable_resource_and_decoupled_tools() -> None:
    mcp, _api = _registered()

    assert APP_RESOURCE_URI in mcp.resources
    assert mcp.resource_options[APP_RESOURCE_URI]["mime_type"] == APP_MIME_TYPE
    assert mcp.resource_options[APP_RESOURCE_URI]["meta"]["ui"]["csp"] == {
        "connectDomains": [],
        "resourceDomains": [],
    }
    assert {
        "get_document_review_data",
        "render_document_review",
        "get_reconciliation_cockpit_data",
        "render_reconciliation_cockpit",
        "get_ledger_explorer_data",
        "render_ledger_explorer",
    } == set(mcp.tools)
    for name in (
        "render_document_review",
        "render_reconciliation_cockpit",
        "render_ledger_explorer",
    ):
        meta = mcp.tool_options[name]["meta"]
        assert meta["ui"]["resourceUri"] == APP_RESOURCE_URI
        assert meta["openai/outputTemplate"] == APP_RESOURCE_URI


def test_widget_is_self_contained_and_uses_standard_bridge() -> None:
    mcp, _api = _registered()
    html = asyncio.run(mcp.resources[APP_RESOURCE_URI]())

    assert "ui/notifications/tool-result" in html
    assert 'request("ui/initialize"' in html
    assert 'method:"ui/notifications/initialized"' in html
    assert 'appInfo:{name:"Norman Accounting Workbench"' in html
    assert 'appCapabilities:{availableDisplayModes:["inline"]}' in html
    assert "state.bridgeReady=true" in html
    assert 'request("tools/call"' in html
    assert 'request("ui/message"' in html
    assert "https://" not in html


def test_document_and_reconciliation_data_are_compact_and_actionable() -> None:
    mcp, api = _registered()
    ctx = _context(api)

    documents = asyncio.run(
        mcp.tools["get_document_review_data"](
            ctx, search=None, date_from=None, date_to=None, linked=None, limit=30
        )
    )
    reconciliation = asyncio.run(
        mcp.tools["get_reconciliation_cockpit_data"](ctx, date_from=None, date_to=None, limit=50)
    )

    assert documents["items"][0] == {
        "id": "doc-1",
        "fileName": "invoice.pdf",
        "type": "other",
        "brand": "Acme GmbH",
        "number": "",
        "date": "",
        "amount": "119.00",
        "currency": "EUR",
        "vatRate": None,
        "description": "",
        "linked": False,
        "transactionIds": [],
        "status": "Needs match",
    }
    assert reconciliation["summary"]["needsAttention"] == 1
    assert reconciliation["items"][0]["issues"] == [
        "Missing document",
        "Uncategorized",
        "Needs review",
    ]


def test_ledger_data_drills_down_without_mutation() -> None:
    mcp, api = _registered()
    ctx = _context(api)

    accounts = asyncio.run(
        mcp.tools["get_ledger_explorer_data"](ctx, date_from=None, date_to=None, account_code=None)
    )
    detail = asyncio.run(
        mcp.tools["get_ledger_explorer_data"](
            ctx, date_from=None, date_to=None, account_code="1200"
        )
    )

    assert accounts["mode"] == "accounts"
    assert accounts["items"][0]["balance"] == "80.00"
    assert detail["mode"] == "account"
    assert detail["account"]["code"] == "1200"
    assert detail["items"][0]["runningBalance"] == "100.00"
    assert all(method == "GET" for method, _url, _kwargs in api.requests)


def test_render_tools_return_structured_content_and_widget_only_meta() -> None:
    mcp, api = _registered()
    result = asyncio.run(
        mcp.tools["render_document_review"](
            _context(api), payload={"items": [{"id": "doc-1"}], "summary": {"total": 1}}
        )
    )

    assert isinstance(result, CallToolResult)
    assert result.structuredContent["view"] == "documents"
    assert result.meta == {"norman/view": "documents"}
