"""E-Bilanz account assignments and cutover account preparation.

GmbH/UG users could not clear "no E-Bilanz taxonomy mapping" or "Review and
prepare accounts" blockers in preview_accounting_cutover through MCP: the tools
had no way to assign an E-Bilanz position or to prepare the reviewed accounts.
"""

import asyncio
import json

import pytest
from mcp.server.fastmcp import FastMCP

from norman_mcp.tools import accounting
from norman_mcp.tools.accounting import register_accounting_tools

BASE = "https://api.norman.finance/api/v1/"
COMPANY = {"publicId": "company-1", "chartOfAccounts": {"publicId": "coa-1", "name": "SKR 04", "code": "skr04"}}
POSITION = "bs.ass.currAss.receiv.other.other"


class FakeApi:
    company_id = "company-1"

    def __init__(self, company=COMPANY):  # noqa: ANN001
        self.company = company
        self.requests = []

    async def arequest(self, method, url, params=None, json_data=None, files=None):  # noqa: ANN001, ANN201
        self.requests.append((method, url, params, json_data))
        if method == "GET" and url.endswith("/companies/company-1/"):
            return self.company
        return {"ok": True}


@pytest.fixture
def api(monkeypatch):  # noqa: ANN001, ANN201
    fake = FakeApi()
    monkeypatch.setattr(accounting, "_api_and_company", lambda ctx: (fake, fake.company_id, None))
    return fake


@pytest.fixture
def server():  # noqa: ANN201
    mcp = FastMCP("cutover accounts test")
    register_accounting_tools(mcp)
    return mcp


def call(server, name, arguments):  # noqa: ANN001, ANN201
    """Through FastMCP, so argument validation and defaults apply as for a client."""
    content, structured = asyncio.run(server.call_tool(name, arguments))
    return structured["result"]


def test_new_account_is_created_with_its_manual_assignment(server, api):  # noqa: ANN001
    call(
        server,
        "create_chart_of_accounts_account",
        {
            "code": "1375",
            "name": "Clearing Shopify",
            "account_type": "ASSET",
            "ebilanz_assignment": {"fiscal_year": 2025, "mode": "MANUAL", "position": POSITION},
        },
    )

    method, url, _params, payload = api.requests[-1]
    assert method == "POST"
    assert url == BASE + "accounting/company-categories/"
    # chartCode is required and read from the company when not given.
    assert payload["ebilanzAssignment"] == {
        "chartCode": "skr04",
        "fiscalYear": 2025,
        "mode": "MANUAL",
        "position": POSITION,
    }
    assert payload["cashflowType"] == "ASSET"


def test_an_explicit_chart_code_is_sent_without_a_company_lookup(server, api):  # noqa: ANN001
    call(
        server,
        "update_chart_of_accounts_account",
        {
            "account_id": "acc-1",
            "ebilanz_assignment": {"fiscal_year": 2026, "mode": "DEFERRED", "chart_code": "skr03"},
        },
    )

    assert [request[0] for request in api.requests] == ["PATCH"]
    method, url, _params, payload = api.requests[-1]
    assert url == BASE + "accounting/company-categories/acc-1/"
    assert payload == {
        "ebilanzAssignment": {"chartCode": "skr03", "fiscalYear": 2026, "mode": "DEFERRED", "position": ""},
    }


def test_accounts_without_an_assignment_are_unchanged(server, api):  # noqa: ANN001
    call(server, "update_chart_of_accounts_account", {"account_id": "acc-1", "name": "Renamed"})

    assert api.requests[-1][3] == {"name": "Renamed"}


@pytest.mark.parametrize(
    ("assignment", "message"),
    [
        ({"fiscal_year": 2025, "mode": "MANUAL"}, "needs a position"),
        ({"fiscal_year": 2025, "mode": "AUTOMATIC", "position": POSITION}, "Only a MANUAL"),
    ],
)
def test_inconsistent_assignments_are_refused_before_writing(server, api, assignment, message):  # noqa: ANN001
    result = call(server, "update_chart_of_accounts_account", {"account_id": "acc-1", "ebilanz_assignment": assignment})

    assert message in result["error"]
    assert not [request for request in api.requests if request[0] == "PATCH"]


def test_a_company_without_skr_gets_an_explanation(server, api):  # noqa: ANN001
    api.company = {"publicId": "company-1", "chartOfAccounts": None}

    result = call(
        server,
        "update_chart_of_accounts_account",
        {"account_id": "acc-1", "ebilanz_assignment": {"fiscal_year": 2025, "mode": "AUTOMATIC"}},
    )

    assert "SKR03 or SKR04" in result["error"]
    assert [request[0] for request in api.requests] == ["GET"]


@pytest.mark.parametrize(
    "assignment",
    [
        {"fiscal_year": 2023, "mode": "AUTOMATIC"},
        {"fiscal_year": 2027, "mode": "AUTOMATIC"},
        {"fiscal_year": 2025, "mode": "LATER"},
        {"fiscal_year": 2025, "mode": "AUTOMATIC", "chart_code": "PL_FULL"},
    ],
)
def test_unsupported_years_modes_and_charts_are_rejected_by_the_schema(server, api, assignment):  # noqa: ANN001
    with pytest.raises(Exception, match="validation error"):
        call(server, "update_chart_of_accounts_account", {"account_id": "acc-1", "ebilanz_assignment": assignment})

    assert api.requests == []


def test_positions_are_listed_for_a_type_and_year(server, api):  # noqa: ANN001
    call(server, "get_ebilanz_positions", {"fiscal_year": 2025, "account_type": "EXPENSE", "code": "6815"})

    method, url, params, _payload = api.requests[-1]
    assert method == "GET"
    assert url == BASE + "accounting/company-categories/ebilanz-options/"
    assert params == {"fiscalYear": 2025, "accountType": "EXPENSE", "code": "6815"}


def test_chart_listing_can_include_each_accounts_assignment(server, api):  # noqa: ANN001
    call(server, "list_chart_of_accounts", {"fiscal_year": 2025, "status": "INACTIVE"})

    params = api.requests[-1][2]
    assert params["fiscalYear"] == 2025
    assert params["includeInactive"] is True


def test_the_listing_explains_rows_hidden_by_a_chart_switch(server):  # noqa: ANN001
    tool = server._tool_manager._tools["list_chart_of_accounts"]  # noqa: SLF001

    assert "chart switch" in tool.description
    assert "sourceTemplate" in tool.description


ACCOUNTS = [
    {"code": "1375", "name": "Clearing Shopify", "account_type": "ASSET", "mode": "MANUAL", "position": POSITION},
    {"code": "4400", "name": "Erlöse 19 % USt", "account_type": "INCOME", "mode": "AUTOMATIC"},
    {"code": "8999", "name": "Sonstiges", "account_type": "EXPENSE", "mode": "DEFERRED", "position": "ignored"},
]


def test_preparing_accounts_requires_confirmation(server, api):  # noqa: ANN001
    result = call(server, "prepare_accounting_cutover_accounts", {"review_token": "signed", "accounts": ACCOUNTS})

    assert result["confirmationRequired"] is True
    assert api.requests == []


def test_prepared_accounts_are_sent_as_the_api_expects(server, api):  # noqa: ANN001
    call(
        server,
        "prepare_accounting_cutover_accounts",
        {"review_token": "signed", "accounts": ACCOUNTS, "confirmed": True},
    )

    method, url, _params, payload = api.requests[-1]
    assert method == "POST"
    assert url == BASE + "companies/company-1/accounting/cutover/prepare-accounts/"
    assert payload == {
        "reviewToken": "signed",
        "confirmed": True,
        "accounts": [
            {"code": "1375", "name": "Clearing Shopify", "accountType": "ASSET", "mode": "MANUAL", "position": POSITION},
            {"code": "4400", "name": "Erlöse 19 % USt", "accountType": "INCOME", "mode": "AUTOMATIC", "position": ""},
            {"code": "8999", "name": "Sonstiges", "accountType": "EXPENSE", "mode": "DEFERRED", "position": ""},
        ],
    }


@pytest.mark.parametrize(
    "account",
    [
        {"code": "13a5", "name": "x", "account_type": "ASSET", "mode": "DEFERRED"},
        {"code": "1375", "name": "", "account_type": "ASSET", "mode": "DEFERRED"},
        {"code": "1375", "name": "x", "account_type": "PARTY", "mode": "DEFERRED"},
    ],
)
def test_malformed_review_rows_are_rejected_by_the_schema(server, api, account):  # noqa: ANN001
    with pytest.raises(Exception, match="validation error"):
        call(server, "prepare_accounting_cutover_accounts", {"review_token": "t", "accounts": [account], "confirmed": True})

    assert api.requests == []


def test_preview_description_points_to_the_account_review(server):  # noqa: ANN001
    description = server._tool_manager._tools["preview_accounting_cutover"].description  # noqa: SLF001

    assert "accountReview" in description
    assert "prepare_accounting_cutover_accounts" in description


def test_assignment_schema_documents_the_constraints(server):  # noqa: ANN001
    schema = json.dumps(server._tool_manager._tools["create_chart_of_accounts_account"].parameters)  # noqa: SLF001

    for fact in ("GmbH/UG", "SKR03 or SKR04", "2024, 2025 or 2026", "get_ebilanz_positions"):
        assert fact in schema
