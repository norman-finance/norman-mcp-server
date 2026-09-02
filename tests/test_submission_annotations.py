import asyncio
from types import SimpleNamespace

from mcp.server.fastmcp import FastMCP

from norman_mcp.tools.company import register_company_tools
from norman_mcp.tools.categories import register_category_tools
from norman_mcp.tools.corporate_tax_registration import register_corporate_tax_registration_tools
from norman_mcp.tools.gewerbe_registration import register_gewerbe_registration_tools
from norman_mcp.tools.incorporation import register_incorporation_tools
from norman_mcp.tools.invoices import register_invoice_tools
from norman_mcp.tools.offers import register_offer_tools
from norman_mcp.tools.rules import register_rule_tools
from norman_mcp.tools.tax_advisor import register_tax_advisor_tools
from norman_mcp.tools.taxes import register_tax_tools


READ_ONLY = (True, False, False)
WRITE = (False, False, False)
DESTRUCTIVE_WRITE = (False, False, True)
EXTERNAL_IRREVERSIBLE_WRITE = (False, True, True)


def _annotation_tuple(tool):  # noqa: ANN001, ANN202
    annotations = tool.annotations
    return (
        annotations.readOnlyHint,
        annotations.openWorldHint,
        annotations.destructiveHint,
    )


def test_registration_tools_advertise_truthful_submission_annotations() -> None:
    server = FastMCP()
    register_incorporation_tools(server)
    register_gewerbe_registration_tools(server)
    register_corporate_tax_registration_tools(server)
    tools = server._tool_manager._tools  # noqa: SLF001

    expected = {
        "get_incorporation": READ_ONLY,
        "get_incorporation_choices": READ_ONLY,
        "create_incorporation": WRITE,
        "update_incorporation_company": WRITE,
        "update_incorporation_capital": WRITE,
        "add_incorporation_shareholder": WRITE,
        "update_incorporation_shareholder": WRITE,
        "invite_incorporation_shareholder": EXTERNAL_IRREVERSIBLE_WRITE,
        "remove_incorporation_shareholder": DESTRUCTIVE_WRITE,
        "set_incorporation_agreement": WRITE,
        "update_incorporation_notary_preferences": WRITE,
        "generate_incorporation_documents": WRITE,
        "get_incorporation_document_preview": READ_ONLY,
        "match_incorporation_notaries": EXTERNAL_IRREVERSIBLE_WRITE,
        "request_incorporation_notary": EXTERNAL_IRREVERSIBLE_WRITE,
        "suggest_incorporation_purpose": READ_ONLY,
        "check_incorporation_name": READ_ONLY,
        "complete_incorporation_step": WRITE,
        "get_gewerbe_registration": READ_ONLY,
        "get_gewerbe_registration_choices": READ_ONLY,
        "create_gewerbe_registration": WRITE,
        "update_gewerbe_basic": WRITE,
        "update_gewerbe_business": WRITE,
        "update_gewerbe_owner": WRITE,
        "suggest_gewerbe_activity": READ_ONLY,
        "generate_gewerbe_document": WRITE,
        "get_gewerbe_document_preview": READ_ONLY,
        "get_gewerbe_trade_office": READ_ONLY,
        "get_corporate_tax_registration": READ_ONLY,
        "get_corporate_tax_registration_choices": READ_ONLY,
        "create_corporate_tax_registration": WRITE,
        "update_corporate_company": WRITE,
        "update_corporate_registration_details": WRITE,
        "set_corporate_people": DESTRUCTIVE_WRITE,
        "update_corporate_financials": WRITE,
        "update_corporate_vat_and_bank": WRITE,
        "get_corporate_submission_link": READ_ONLY,
    }

    assert set(tools) == set(expected)
    assert {name: _annotation_tuple(tool) for name, tool in tools.items()} == expected


def test_external_actions_and_internal_ai_use_truthful_annotations() -> None:
    server = FastMCP()
    register_invoice_tools(server)
    register_offer_tools(server)
    register_tax_advisor_tools(server)
    register_tax_tools(server)
    register_category_tools(server)
    register_rule_tools(server)
    tools = server._tool_manager._tools  # noqa: SLF001

    assert _annotation_tuple(tools["send_invoice"]) == EXTERNAL_IRREVERSIBLE_WRITE
    assert _annotation_tuple(tools["send_invoice_overdue_reminder"]) == EXTERNAL_IRREVERSIBLE_WRITE
    assert _annotation_tuple(tools["send_offer"]) == EXTERNAL_IRREVERSIBLE_WRITE
    assert _annotation_tuple(tools["ping_client_for_documents"]) == EXTERNAL_IRREVERSIBLE_WRITE
    assert _annotation_tuple(tools["submit_tax_report"]) == EXTERNAL_IRREVERSIBLE_WRITE
    assert _annotation_tuple(tools["approve_rule_execution"]) == EXTERNAL_IRREVERSIBLE_WRITE
    assert _annotation_tuple(tools["suggest_skr_category"]) == READ_ONLY


def test_every_exposed_tool_sets_all_required_submission_hints() -> None:
    from norman_mcp.server import mcp

    for tool in mcp._tool_manager._tools.values():  # noqa: SLF001
        assert None not in _annotation_tuple(tool), tool.name


class _DatevApi:
    company_id = "company-1"

    def __init__(self) -> None:
        self.calls = []

    def _make_request(self, method, url, params=None, json_data=None):  # noqa: ANN001, ANN202
        self.calls.append((method, url, params, json_data))
        if method == "GET":
            return {
                "datevAdvisorNumber": "1234",
                "datevClientNumber": "5678",
                "chartOfAccounts": "skr03",
            }
        return {"success": True}


def test_datev_export_uses_live_endpoint_and_saved_company_settings() -> None:
    server = FastMCP()
    register_company_tools(server)
    tool = server._tool_manager._tools["trigger_datev_export"]  # noqa: SLF001
    api = _DatevApi()
    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))

    result = asyncio.run(
        tool.fn(
            ctx,
            date_from="2026-01-01",
            date_to="2026-12-31",
            include_documents=True,
            advisor_number=None,
            client_number=None,
            skr_variant=None,
        ),
    )

    assert result == {"success": True}
    method, url, _params, payload = api.calls[-1]
    assert method == "POST"
    assert url.endswith("/api/v1/accounting/datev-export/")
    assert payload == {
        "dateFrom": "2026-01-01",
        "dateTo": "2026-12-31",
        "includeDocuments": True,
        "advisorNumber": "1234",
        "clientNumber": "5678",
        "skrVariant": "SKR03",
    }
    assert _annotation_tuple(tool) == WRITE


def test_datev_export_requires_datev_numbers_before_requesting_export() -> None:
    server = FastMCP()
    register_company_tools(server)
    tool = server._tool_manager._tools["trigger_datev_export"]  # noqa: SLF001
    api = _DatevApi()
    api._make_request = lambda method, url, params=None, json_data=None: {}  # type: ignore[method-assign]
    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))

    result = asyncio.run(
        tool.fn(
            ctx,
            date_from="2026-01-01",
            date_to="2026-12-31",
            include_documents=True,
            advisor_number=None,
            client_number=None,
            skr_variant=None,
        ),
    )

    assert result["error"] == "DATEV advisor number and client number are required."
