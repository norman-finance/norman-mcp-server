"""Every tool returns an object, and a failed call is reported as failed.

These go through the production server's `tools/call` handler, so FastMCP's
output validation runs exactly as it does for a client: a tool annotated
`-> Dict[str, Any]` that handed back the API's bare list or string used to fail
with "Input should be a valid dictionary" although the API call had succeeded.
"""

import pytest
from mcp.server.fastmcp import FastMCP

from norman_mcp.server import mcp as server
from norman_mcp.tools.accounting import register_accounting_tools
from norman_mcp.tools.categories import register_category_tools
from norman_mcp.tools.clients import register_client_tools
from norman_mcp.tools.company import register_company_tools
from norman_mcp.tools.documents import register_document_tools
from norman_mcp.tools.invoices import register_invoice_tools
from norman_mcp.tools.results import as_object, is_failure
from norman_mcp.tools.taxes import register_tax_tools
from norman_mcp.apps import register_public_apps
from tests.mcp_harness import FakeApi, call_tool, error_payload, structured

SME_COMPANY = {"publicId": "company-1", "isSme": True}
SKR_ENTRIES = [{"accountNumber": "4200", "nameDe": "Raumkosten", "nameEn": "Rent"}]


def sme_api(listing):  # noqa: ANN001, ANN201
    """The company lookup is an SME; every other endpoint answers `listing`."""
    return FakeApi(lambda method, url, _kw: SME_COMPANY if url.endswith("/companies/company-1/") else listing)


@pytest.mark.parametrize(
    ("tool", "arguments", "api"),
    [
        ("list_coa_templates", {}, FakeApi([{"code": "skr03"}, {"code": "skr04"}])),
        ("list_chart_of_accounts_templates", {}, FakeApi([{"code": "skr03"}, {"code": "skr04"}])),
        ("search_skr_by_code", {"code": "42"}, sme_api(SKR_ENTRIES)),
        ("suggest_skr_category", {"query": "office rent"}, sme_api(SKR_ENTRIES)),
        # A generic tool with no special handling: the guard wraps the list.
        ("list_tax_states", {}, FakeApi([{"code": "BE"}, {"code": "BY"}])),
    ],
)
def test_a_bare_list_from_the_api_comes_back_as_results(tool, arguments, api):  # noqa: ANN001
    result = call_tool(tool, arguments, api)

    data = structured(result)
    assert isinstance(data["results"], list) and data["results"]


def test_an_empty_ai_suggestion_explains_itself():
    data = structured(call_tool("suggest_skr_category", {"query": "xyz"}, sme_api([])))

    assert data["results"] == []
    assert "No matching categories" in data["message"]


def test_a_valid_tax_number_is_no_longer_a_validation_crash():
    # The API answers 201 with the bare JSON string "Tax number is valid".
    result = call_tool("validate_tax_number", {"tax_number": "1121081508150", "region_code": "BE"}, FakeApi("Tax number is valid"))

    assert not result.isError
    assert "Tax number is valid" in str(structured(result))


def test_a_bare_string_from_the_api_comes_back_as_a_message():
    data = structured(call_tool("list_tax_settings", {}, FakeApi("Nothing configured")))

    assert data == {"message": "Nothing configured"}


def test_an_api_failure_is_reported_as_a_tool_error_with_the_api_detail():
    paywall = {
        "error": "Sending invoices by email is not included in your plan.",
        "status_code": 403,
        "code": "invoice_send_limit_reached",
        "detail": {
            "detail": "Sending invoices by email is not included in your plan.",
            "code": "invoice_send_limit_reached",
        },
    }

    result = call_tool("get_company_balance", {}, FakeApi(paywall))

    assert result.isError is True
    assert result.structuredContent is None
    assert error_payload(result) == paywall


def test_a_precondition_failure_is_reported_as_a_tool_error():
    result = call_tool("get_company_balance", {}, FakeApi({"never": "called"}, company_id=None))

    assert error_payload(result) == {"error": "No company available. Please authenticate first."}


def test_a_widget_view_keeps_its_error_for_the_widget_to_render():
    api = FakeApi({"error": "Access forbidden. Check your account permissions.", "status_code": 403})

    data = structured(call_tool("get_document_review_data", {}, api))

    assert data["view"] == "documents"
    assert data["error"] == "Access forbidden. Check your account permissions."


def test_a_successful_object_passes_through_unchanged():
    balance = {"balance": "1200.00", "currency": "EUR"}

    assert structured(call_tool("get_company_balance", {}, FakeApi(balance))) == balance


def test_every_registered_tool_is_guarded():
    unguarded = [name for name, tool in server._tool_manager._tools.items() if not hasattr(tool.fn, "__wrapped__")]  # noqa: SLF001

    assert unguarded == []


def test_the_guard_leaves_every_tool_schema_unchanged():
    plain = FastMCP()
    for register in (
        register_accounting_tools,
        register_category_tools,
        register_client_tools,
        register_company_tools,
        register_document_tools,
        register_invoice_tools,
        register_tax_tools,
        register_public_apps,
    ):
        register(plain)

    for name, tool in plain._tool_manager._tools.items():  # noqa: SLF001
        guarded = server._tool_manager._tools[name]  # noqa: SLF001
        assert guarded.parameters == tool.parameters, name
        assert guarded.output_schema == tool.output_schema, name
        assert guarded.description == tool.description, name
        assert guarded.context_kwarg == tool.context_kwarg, name


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"a": 1}, {"a": 1}),
        ([1, 2], {"results": [1, 2]}),
        ("ok", {"message": "ok"}),
        (None, {}),
        (3, {"result": 3}),
    ],
)
def test_as_object(value, expected):  # noqa: ANN001
    assert as_object(value) == expected


@pytest.mark.parametrize(
    ("value", "failed"),
    [
        ({"error": "boom"}, True),
        ({"error": "boom", "status_code": 500}, True),
        ({"error": ""}, False),
        ({"error": None, "id": 1}, False),
        ({"view": "documents", "error": "boom"}, False),
        ([{"error": "boom"}], False),
        ("error", False),
    ],
)
def test_is_failure(value, failed):  # noqa: ANN001
    assert is_failure(value) is failed
