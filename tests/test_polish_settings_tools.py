"""A Polish company's tax settings from an AI client: every tool proposes, the owner applies in Norman.

The Norman API refuses a Polish company's tax settings from OAuth clients, API keys and MCP servers
(`tax_setting_proposal_required`) and lets them propose instead. The tools POST a proposal and hand the owner its
`openUrl`, the tax settings in Norman with the proposal on top. No tool applies one or takes a KSeF token. A German
company's settings are written as before.
"""

import asyncio
import inspect
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.server.mcpserver import MCPServer

from norman_mcp.server import mcp as shared_server
from norman_mcp.tools.company import register_company_tools
from norman_mcp.tools.invoice_management import register_invoice_management_tools
from norman_mcp.tools.invoice_schemas import InvoiceSettings
from norman_mcp.tools.polish_settings import register_polish_settings_tools
from norman_mcp.tools.taxes import register_tax_tools
from tests.mcp_harness import FakeApi as ProtocolApi, call_tool, structured

COMPANY = "company-1"
OPEN_URL = f"https://app.norman.finance/account?section=tax-settings&company={COMPANY}&proposal=proposal-1"
CARD = {"cardType": "tax_setting_change", "proposalId": "proposal-1", "status": "pending", "openUrl": OPEN_URL}
SETTINGS_TOOLS = {"propose_tax_setting_change", "get_ksef_status", "search_polish_tax_offices"}


class FakeApi:
    company_id = COMPANY

    def __init__(self, country="PL", answers=None):
        self.country = country
        self.answers = answers or {}
        self.calls = []

    def _answer(self, method, url, body):
        self.calls.append((method, url, body))
        if method == "GET" and url.endswith(f"companies/{COMPANY}/"):
            return {"publicId": COMPANY, "country": self.country}
        if method == "POST" and url.endswith("tax-setting-proposals/"):
            return CARD
        for suffix, answer in self.answers.items():
            if url.endswith(suffix):
                return answer
        return {"ok": True}

    async def arequest(self, method, url, json_data=None, params=None, **_):
        return self._answer(method, url, json_data if json_data is not None else params)

    def _make_request(self, method, url, params=None, json_data=None, **_):
        return self._answer(method, url, json_data if json_data is not None else params)

    def posted(self):
        return [body for method, url, body in self.calls if method == "POST" and url.endswith("tax-setting-proposals/")]

    def writes(self):
        return [(method, url, body) for method, url, body in self.calls if method in {"PATCH", "PUT"}]


def tools(register):
    server = MCPServer()
    register(server)
    return server._tool_manager._tools  # noqa: SLF001


def call(_register, _tool, api, **kwargs):
    """Call a tool as the server would: every argument not given at its default, None."""
    fn = tools(_register)[_tool].fn
    arguments = {key: None for key in inspect.signature(fn).parameters if key != "ctx"} | kwargs
    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))
    return asyncio.run(fn(ctx, **arguments))


def test_the_shared_server_lists_the_tools_marked_for_poland():
    listed = shared_server._tool_manager._tools  # noqa: SLF001

    assert listed.keys() >= SETTINGS_TOOLS
    for name in SETTINGS_TOOLS:
        assert listed[name].description.startswith("Poland only.")


def test_discovery_marks_a_stored_proposal_as_an_additive_non_idempotent_write():
    listed = {tool.name: tool for tool in asyncio.run(shared_server.list_tools())}
    proposal = listed["propose_tax_setting_change"]
    assert proposal.annotations.read_only_hint is False
    assert proposal.annotations.destructive_hint is False
    assert proposal.annotations.open_world_hint is False
    assert proposal.annotations.idempotent_hint is False
    assert "Creates a pending proposal on each call" in proposal.description
    for name in SETTINGS_TOOLS - {"propose_tax_setting_change"}:
        assert listed[name].annotations.read_only_hint is True


def test_personal_identifier_is_not_exposed_in_the_public_proposal_schema():
    listed = {tool.name: tool for tool in asyncio.run(shared_server.list_tools())}
    schema = listed["propose_tax_setting_change"].input_schema
    assert "pesel" not in schema["properties"]
    assert "pesel" not in schema["properties"]["setting"]["enum"]
    # Business identifiers remain supported; this does not change company records.
    assert {"nip", "eu_vat_number"} <= schema["properties"].keys()


def test_the_cit_rate_offers_estonian_cit_next_to_9_and_19_percent():
    listed = {tool.name: tool for tool in asyncio.run(shared_server.list_tools())}
    cit_rate = listed["propose_tax_setting_change"].input_schema["properties"]["cit_rate"]
    values = next(option["enum"] for option in cit_rate["anyOf"] if "enum" in option)
    assert values == ["cit_standard", "cit_small", "cit_estonian"]
    assert "ZAW-RD" in cit_rate["description"]


def test_pesel_proposal_is_rejected_by_the_protocol_before_any_api_request():
    api = ProtocolApi()
    result = call_tool("propose_tax_setting_change", {"setting": "pesel", "pesel": "synthetic-id"}, api)
    assert result.is_error
    assert api.requests == []


def test_proposal_passes_protocol_input_and_output_validation_without_applying_settings():
    def respond(method, url, kwargs):
        if method == "GET":
            return {"country": "PL"}
        return CARD

    api = ProtocolApi(respond, company_id=COMPANY)
    result = structured(call_tool("propose_tax_setting_change", {"setting": "tax_office", "tax_office_code": "1435"}, api))
    assert result["proposal"] == CARD
    assert result["openUrl"] == OPEN_URL
    writes = [(method, url, kwargs["json_data"]) for method, url, kwargs in api.requests if method != "GET"]
    assert len(writes) == 1
    assert writes[0][0] == "POST"
    assert writes[0][2] == {"setting": "tax_office", "values": {"taxOfficeCode": "1435"}}
    assert writes[0][1].endswith(f"/companies/{COMPANY}/tax-setting-proposals/")


def test_a_proposal_returns_the_link_where_the_owner_applies_it():
    api = FakeApi()
    answer = call(
        register_polish_settings_tools, "propose_tax_setting_change", api,
        setting="tax_form", tax_form="flat", tax_form_from_year=2027,
    )

    assert api.posted() == [{"setting": "tax_form", "values": {"taxRegime": "flat", "taxRegimeFrom": 2027}}]
    assert (answer["proposal"], answer["openUrl"]) == (CARD, OPEN_URL)
    assert OPEN_URL in answer["message"]
    assert "No AI client can apply it" in answer["message"]
    assert api.writes() == []


@pytest.mark.parametrize(
    ("arguments", "values"),
    [
        ({"setting": "zus", "zus_scheme": "preferential", "zus_scheme_start": "2026-01-01"},
         {"zusRelief": "preferential", "zusSchemeStart": "2026-01-01"}),
        ({"setting": "vat_cash_method", "cash_method_off": True}, {"vatCashMethodFrom": None}),
        ({"setting": "tax_office", "tax_office_code": "1435"}, {"taxOfficeCode": "1435"}),
        ({"setting": "ksef_sync"}, {}),
        ({"setting": "cit_rate", "cit_rate": "cit_estonian"}, {"taxRegime": "cit_estonian"}),
    ],
)
def test_each_setting_sends_its_own_values(arguments, values):
    api = FakeApi()
    call(register_polish_settings_tools, "propose_tax_setting_change", api, **arguments)

    assert api.posted() == [{"setting": arguments["setting"], "values": values}]


def test_a_german_company_gets_no_proposal_and_one_setting_goes_per_call():
    german = FakeApi(country="DE")
    refused = call(register_polish_settings_tools, "propose_tax_setting_change", german, setting="nip", nip="5260250274")
    api = FakeApi()
    mixed = call(
        register_polish_settings_tools, "propose_tax_setting_change", api,
        setting="nip", nip="5260250274", deadline_reminders=False,
    )

    assert refused["code"] == "polish_company_required"
    assert german.posted() == []
    assert "one setting per call" in mixed["error"]
    assert api.posted() == []


def test_the_ksef_status_links_to_the_token_field_and_never_carries_a_token():
    api = FakeApi(answers={"ksef-connection/": {"connected": True, "mode": "token", "tokenStatus": "valid"}})
    answer = call(register_polish_settings_tools, "get_ksef_status", api)

    assert answer["connected"] is True
    assert answer["settingsUrl"].endswith(f"account?section=tax-settings&company={COMPANY}&field=ksefToken")
    assert "token" not in answer


def test_no_tool_takes_a_ksef_token_or_applies_a_proposal():
    for tool in shared_server._tool_manager._tools.values():  # noqa: SLF001
        assert not [name for name in inspect.signature(tool.fn).parameters if re.search("ksef.*token", name)], tool.name
    propose = shared_server._tool_manager._tools["propose_tax_setting_change"]  # noqa: SLF001
    assert not [name for name in inspect.signature(propose.fn).parameters if "token" in name]
    lines = [
        line
        for path in Path("norman_mcp").rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if "tax-setting-proposals" in line
    ]
    assert lines
    # The collection a proposal is POSTed to is the only proposal URL any tool names: never apply or cancel.
    assert not [line for line in lines if re.search(r"tax-setting-proposals/[^\s\"'),]", line)], lines


def test_the_tax_offices_are_searched():
    offices = [{"code": "1435", "name": "Urząd Skarbowy w Piasecznie", "city": "Piaseczno"}]
    api = FakeApi(answers={"tax-offices/": offices})

    assert call(register_polish_settings_tools, "search_polish_tax_offices", api, search="Piaseczno") == {
        "taxOffices": offices, "count": 1,
    }


# ── The settings writes of a Polish company propose ──────────────────────────────────────────────────────


def test_update_tax_setting_proposes_this_years_vat_status():
    api = FakeApi(answers={"tax-settings/setting-1/": {"taxType": "sales", "taxYear": date.today().year}})
    answer = call(register_tax_tools, "update_tax_setting", api, setting_id="setting-1", reporting_frequency="quarterly")

    assert api.posted() == [{"setting": "vat_status", "values": {"reportingFrequency": "quarterly"}}]
    assert api.writes() == []
    assert answer["openUrl"] == OPEN_URL


def test_update_company_details_proposes_the_tax_details_and_writes_the_rest():
    api = FakeApi()
    answer = call(
        register_company_tools, "update_company_details", api,
        name="Kowalski", tax_id="5260250274", vat_id="PL5260250274", activity_start=date(2025, 2, 1),
        notify_tax_deadlines=False,
    )

    assert api.posted() == [
        {"setting": "nip", "values": {"taxNumber": "5260250274"}},
        {"setting": "activity_start", "values": {"activityStart": "2025-02-01"}},
        {"setting": "reminders", "values": {"isToNotifyTaxDeadlines": False}},
    ]
    assert [(method, body) for method, _, body in api.writes()] == [("PATCH", {"name": "Kowalski"})]
    assert answer["proposals"] == [CARD, CARD, CARD]
    assert OPEN_URL in answer["message"]


def test_update_vat_proportion_proposes():
    api = FakeApi()
    answer = call(register_tax_tools, "update_vat_proportion", api, year=2027, estimated_percent=73)

    assert api.posted() == [{"setting": "vat_proportion", "values": {"year": 2027, "estimatedPercent": 73}}]
    assert api.writes() == []
    assert answer["openUrl"] == OPEN_URL


def test_update_invoice_settings_proposes_the_tax_office_and_writes_the_rest():
    api = FakeApi()
    answer = call(
        register_invoice_management_tools, "update_invoice_settings", api,
        changes=InvoiceSettings(tax_office_code="1435", create_qr=True),
    )

    assert api.posted() == [{"setting": "tax_office", "values": {"taxOfficeCode": "1435"}}]
    assert [(method, body) for method, _, body in api.writes()] == [("PATCH", {"createQr": True})]
    assert answer["proposals"] == [CARD]


# ── Germany stays as it is ───────────────────────────────────────────────────────────────────────────────


def test_a_german_company_still_writes_its_settings_directly():
    api = FakeApi(country="DE")
    call(register_tax_tools, "update_tax_setting", api, setting_id="setting-1", vat_type="kleinunternehmer")
    call(register_company_tools, "update_company_details", api, tax_id="12/345/67890", notify_tax_deadlines=False)
    call(register_invoice_management_tools, "update_invoice_settings", api, changes=InvoiceSettings(create_qr=True))

    assert api.posted() == []
    assert [method for method, _, _ in api.writes()] == ["PATCH", "PATCH", "PATCH"]


def test_a_german_company_has_no_tax_office_to_propose():
    api = FakeApi(country="DE")
    answer = call(
        register_invoice_management_tools, "update_invoice_settings", api,
        changes=InvoiceSettings(tax_office_code="1435"),
    )

    assert answer["code"] == "polish_company_required"
    assert api.posted() == [] and api.writes() == []
