"""Regression coverage for the actual OpenAI findings, without external writes."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mcp.server.mcpserver import MCPServer

from norman_mcp.tools.corporate_tax_registration import register_corporate_tax_registration_tools
from norman_mcp.server import mcp


@pytest.mark.parametrize(
    "name",
    [
        "update_invoice_settings",
        "save_invoice_email_template",
        "dismiss_rule_execution",
        "add_incorporation_shareholder",
        "update_incorporation_shareholder",
        "toggle_agent",
        "stop_workflow",
        "schedule_workflow",
        "unschedule_workflow",
    ],
)
def test_replacements_and_cancellations_are_destructive(name):
    assert mcp._tool_manager._tools[name].annotations.destructive_hint is True


@pytest.mark.parametrize(
    "name", ["update_invoice_email_settings", "resume_recurring_invoice", "schedule_workflow"]
)
def test_enabling_future_external_actions_is_open_world(name):
    annotations = mcp._tool_manager._tools[name].annotations
    assert annotations.open_world_hint is True
    assert annotations.destructive_hint is True


def test_legacy_account_template_alias_keeps_a_distinct_display_name():
    tools = mcp._tool_manager._tools
    assert tools["list_coa_templates"].title != tools["list_chart_of_accounts_templates"].title
    assert tools["list_coa_templates"].annotations.read_only_hint is True
    assert tools["list_chart_of_accounts_templates"].annotations.read_only_hint is True


def _corporate_tools(api):
    server = MCPServer()
    register_corporate_tax_registration_tools(server)
    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))
    return server._tool_manager._tools, ctx


@pytest.mark.parametrize("key", ["taxId", "tax_id", "SSN", "passportNumber", "nationalId"])
def test_personal_identifiers_never_reach_the_api(key):
    api = SimpleNamespace(_make_request=Mock())
    tools, ctx = _corporate_tools(api)
    result = asyncio.run(
        tools["set_corporate_people"].fn(
            ctx,
            "test-registration",
            representatives=[{"firstName": "Sample", key: "synthetic-id"}],
            shareholder_entries=None,
        )
    )
    assert "authenticated Norman app" in result["error"]
    assert result["url"].endswith("/corporate-tax-registration")
    api._make_request.assert_not_called()


def test_stored_identifiers_are_withheld_without_mutating_the_api_record():
    stored = {
        "publicId": "test-registration",
        "representatives": [
            {
                "firstName": "Sample",
                "taxId": "synthetic-id",
                "passport_number": "synthetic-passport",
            },
        ],
    }
    api = SimpleNamespace(_make_request=Mock(return_value=stored))
    tools, ctx = _corporate_tools(api)
    result = asyncio.run(tools["get_corporate_tax_registration"].fn(ctx))
    assert result["representatives"] == [{"firstName": "Sample"}]
    assert stored["representatives"][0]["taxId"] == "synthetic-id"
    assert stored["representatives"][0]["passport_number"] == "synthetic-passport"


def test_non_identifier_people_updates_keep_the_existing_request_contract():
    api = SimpleNamespace(_make_request=Mock(return_value={"status": "data_collection"}))
    tools, ctx = _corporate_tools(api)
    result = asyncio.run(
        tools["set_corporate_people"].fn(
            ctx,
            "test-registration",
            representatives=[{"firstName": "Sample"}],
            shareholder_entries=None,
        )
    )
    assert result == {"status": "data_collection"}
    args, kwargs = api._make_request.call_args
    assert args[0] == "PATCH"
    assert kwargs["json_data"] == {"representatives": [{"firstName": "Sample"}]}


@pytest.mark.parametrize(
    "group, argument",
    [
        ("representatives", "representatives"),
        ("shareholderEntries", "shareholder_entries"),
        ("shareholder_entries", "shareholder_entries"),
    ],
)
def test_replacing_people_cannot_discard_hidden_identifiers(group, argument):
    stored = {group: [{"firstName": "Sample", "taxId": "synthetic-id"}]}
    api = SimpleNamespace(_make_request=Mock(return_value=stored))
    tools, ctx = _corporate_tools(api)
    params = {"representatives": None, "shareholder_entries": None, argument: []}
    result = asyncio.run(tools["set_corporate_people"].fn(ctx, "test-registration", **params))
    assert "preserve stored personal identifiers" in result["error"]
    assert api._make_request.call_count == 1
    assert api._make_request.call_args.args[0] == "GET"


def test_people_update_stops_if_preflight_fails():
    api = SimpleNamespace(_make_request=Mock(return_value={"error": "unavailable"}))
    tools, ctx = _corporate_tools(api)
    result = asyncio.run(
        tools["set_corporate_people"].fn(
            ctx,
            "test-registration",
            representatives=[],
            shareholder_entries=None,
        )
    )
    assert "no changes were made" in result["error"]
    assert api._make_request.call_count == 1
