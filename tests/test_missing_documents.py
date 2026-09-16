import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from norman_mcp.tools.tax_advisor import register_tax_advisor_tools

COMPANY = "d926d139-1f89-41a0-8e2e-ceeb721d5fe1"


class Registry:
    def __init__(self):
        self.tools = {}
    def tool(self, **kwargs):
        def register(fn):
            self.tools[fn.__name__] = fn
            return fn
        return register


def run(api, start=None, end=None, company=COMPANY):
    registry = Registry()
    register_tax_advisor_tools(registry)
    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))
    return asyncio.run(registry.tools["get_missing_documents_summary"](ctx, company, start, end))


def tx(pk, **extra):
    return {"publicId": pk, "attachment": None, "invoice": None, "documentNotRequired": False,
            "valueDate": "2025-11-12", "amount": "-12.50", "companyCategory": {"name": "Office"}, **extra}


def test_all_pages_use_company_scoped_route_and_receipt_semantics():
    api = SimpleNamespace(company_id=COMPANY, arequest=AsyncMock(side_effect=[
        {"count": 5, "next": "https://untrusted.invalid/?page=2", "results": [tx("1"), tx("2", invoice="invoice-id")]},
        {"count": 5, "next": None, "results": [tx("3", documentNotRequired=True), tx("4", attachment="receipt-id"), tx("5")]},
    ]))
    result = run(api, "2025-01-01", "2025-12-31")
    assert result["totalTransactions"] == 5
    assert result["totalMissing"] == 2
    assert result["byMonth"][0]["totalAmount"] == 25
    assert result["topMissingByAmount"][0]["category"] == "Office"
    for i, call in enumerate(api.arequest.call_args_list, 1):
        assert call.args[0] == "GET"
        assert call.args[1].endswith(f"/companies/{COMPANY}/accounting/transactions/")
        assert call.kwargs["params"]["page"] == i
        assert call.kwargs["params"]["dateFrom"] == "2025-01-01"
        assert call.kwargs["params"]["dateTo"] == "2025-12-31"


@pytest.mark.parametrize("response", [{"error": "Forbidden"}, {"detail": "Forbidden"}, {}, [],
    {"count": 1, "results": []}, {"count": 1, "results": [{"publicId": "1"}]},
    {"count": 1, "results": [tx("1")], "next": "unexpected"}])
def test_unavailable_or_incomplete_is_not_a_successful_zero(response):
    result = run(SimpleNamespace(company_id=COMPANY, arequest=AsyncMock(return_value=response)))
    assert result["status"] == "unavailable"
    assert "error" in result
    assert "totalMissing" not in result and "totalTransactions" not in result


def test_second_page_failure_does_not_claim_a_partial_audit_is_complete():
    api = SimpleNamespace(company_id=COMPANY, arequest=AsyncMock(side_effect=[{"count": 2, "results": [tx("1")]}, TimeoutError("secret")] ))
    result = run(api)
    assert result["status"] == "unavailable"
    assert "secret" not in str(result)
    assert "totalMissing" not in result


@pytest.mark.parametrize("second", [
    {"count": 2, "results": [tx("1")]},  # API ignored page.
    {"count": 3, "results": [tx("2")]},  # Collection changed.
])
def test_repeated_or_changed_pages_are_rejected(second):
    api = SimpleNamespace(company_id=COMPANY, arequest=AsyncMock(side_effect=[{"count": 2, "results": [tx("1")]}, second]))
    assert run(api)["status"] == "unavailable"
    assert api.arequest.await_count == 2


def test_real_empty_collection_and_snake_case_response():
    assert run(SimpleNamespace(company_id=COMPANY, arequest=AsyncMock(return_value={"count": 0, "results": [], "next": None})))["totalMissing"] == 0
    row = {"public_id": "1", "document_not_required": True, "attachment": None, "invoice": None}
    assert run(SimpleNamespace(company_id=COMPANY, arequest=AsyncMock(return_value={"count": 1, "results": [row]})))["totalMissing"] == 0


@pytest.mark.parametrize("start,end,company", [("bad", None, COMPANY), ("2025-12-31", "2025-01-01", COMPANY), (None, None, "../other")])
def test_invalid_scope_makes_no_requests(start, end, company):
    api = SimpleNamespace(company_id=COMPANY, arequest=AsyncMock())
    assert run(api, start, end, company)["status"] == "unavailable"
    api.arequest.assert_not_called()


def test_mismatched_active_company_does_not_read_or_relabel_another_company():
    api = SimpleNamespace(company_id="different", arequest=AsyncMock())
    assert run(api)["status"] == "unavailable"
    api.arequest.assert_not_called()
