"""Production tools/call handlers, including SDK argument/result validation; synthetic API."""

import base64
from datetime import date
from uuid import UUID

import pytest

from tests.mcp_harness import FakeApi, call_tool, error_payload, structured
from tests.test_polish_parity import CASES


def is_error(result):
    return result.is_error


def tool_payload(result):
    return error_payload(result) if result.is_error else structured(result)


def responder(chart="PL_KPIR", country="PL"):
    def respond(method, url, kwargs):
        if url.endswith("/companies/company-1/"):
            return {
                "publicId": "company-1",
                "name": "Synthetic studio",
                "country": country,
                "currency": "PLN" if country == "PL" else "EUR",
                "chartOfAccounts": {"code": chart},
                "isSme": chart in {"PL_FULL", "skr04"},
                "usesCompanyChart": True,
            }
        if method == "GET" and "/transactions/" in url:
            return {"cashflowType": "INCOME", "amount": "100.00"}
        return {"results": [], "next": "page-2"}

    return respond


def wire_args(args):
    return {
        key: str(value) if isinstance(value, (date, UUID)) else value
        for key, value in args.items()
    }


@pytest.mark.parametrize("name,args,chart,suffix,method", CASES)
def test_new_tools_pass_protocol_input_and_output_validation(
    name, args, chart, suffix, method
):
    api = FakeApi(responder(chart))
    assert structured(call_tool(name, wire_args(args), api)) == {
        "results": [],
        "next": "page-2",
    }
    assert api.requests[-1][0] == method
    assert api.requests[-1][1].endswith("/companies/company-1/" + suffix)


@pytest.mark.parametrize("args", [{"year": 2026, "month": 13}, {"year": 0}])
def test_invalid_period_is_rejected_before_api(args):
    api = FakeApi(responder())
    result = call_tool("get_polish_tax_book", args, api)
    assert is_error(result)
    assert api.requests == []


@pytest.mark.parametrize("vat_code", ["23", "8", "5", "0", "np", "zw", "oo", ""])
def test_invoice_and_transaction_vat_code_through_mcp(vat_code):
    api = FakeApi(responder())
    rate = int(vat_code) if vat_code.isdigit() else 0
    structured(
        call_tool(
            "create_invoice",
            {
                "client_id": "synthetic-client",
                "issued": "2026-10-01",
                "items": [
                    {
                        "name": "Synthetic service",
                        "quantity": 1,
                        "rate": 10000,
                        "vat_rate": rate,
                        "vat_code": vat_code,
                    }
                ],
            },
            api,
        )
    )
    assert api.requests[-1][2]["json_data"]["invoicedItems"][0]["vatCode"] == vat_code
    structured(
        call_tool(
            "create_transaction",
            {
                "amount": 100,
                "description": "Synthetic service",
                "cashflow_type": "INCOME",
                "supplier_country": "PL",
                "currency": "PLN",
                "vat_code": vat_code,
                "vat_rate": rate,
            },
            api,
        )
    )
    assert api.requests[-1][2]["json_data"]["vatCode"] == vat_code
    structured(
        call_tool(
            "update_transaction",
            {"transaction_id": "operation-1", "vat_code": vat_code},
            api,
        )
    )
    assert api.requests[-1][2]["json_data"]["vatCode"] == vat_code


def test_asset_create_and_update_preserve_polish_tax_details():
    api = FakeApi(responder())
    tax = {
        "kind": "computer",
        "entry_date": "2026-10-01",
        "annual_rate": "30.00",
        "method": "linear",
        "vat_rate": 23,
        "vat_recovery": 100,
        "scope_confirmed": True,
        "classification_confirmed": True,
    }
    structured(
        call_tool(
            "create_asset",
            {
                "name": "Synthetic computer",
                "asset_type": "tangible",
                "acquisition_date": "2026-09-20",
                "depreciation_basis": 12000,
                "useful_lifetime_months": 40,
                "gross_purchase_price": 14760,
                "polish_tax": tax,
                "opening_date": "2027-01-01",
                "opening_book_value": 11100,
                "bill_id": "bill-1",
            },
            api,
        )
    )
    payload = api.requests[-1][2]["json_data"]
    assert payload["polishTax"]["entryDate"] == "2026-10-01"
    assert payload["polishTax"]["annualRate"] == "30.00"
    assert "eligibilityConfirmed" not in payload["polishTax"]
    assert payload["openingDate"] == "2027-01-01" and payload["bill"] == "bill-1"
    structured(
        call_tool(
            "update_asset",
            {"asset_id": "asset-1", "polish_tax": tax, "opening_book_value": 11000},
            api,
        )
    )
    assert api.requests[-1][2]["json_data"]["polishTax"] == payload["polishTax"]
    assert api.requests[-1][2]["json_data"]["openingBookValue"] == 11000


def test_api_validation_and_missing_company_are_not_hidden():
    api = FakeApi(
        lambda method, url, kwargs: responder()(method, url, kwargs)
        if url.endswith("/companies/company-1/")
        else {
            "error": "Invalid period",
            "status_code": 400,
            "details": {"date_from": ["Invalid"]},
        }
    )
    payload = tool_payload(
        call_tool(
            "get_polish_jpk_register",
            {"report_id": "11111111-1111-4111-8111-111111111111"},
            api,
        )
    )
    assert payload["error"] == "Invalid period" and payload["status_code"] == 400
    api = FakeApi(responder(), company_id=None)
    assert "error" in tool_payload(
        call_tool("get_polish_tax_book", {"year": 2026}, api)
    )
    assert api.requests == []


def test_jdg_category_visibility_tool_uses_the_polish_chart():
    api = FakeApi(responder())
    structured(
        call_tool(
            "set_company_categories_visibility",
            {"action": "hide", "chart_template": "PL_KPIR", "dry_run": True},
            api,
        )
    )
    assert api.requests[-1][2]["json_data"]["chartTemplate"] == "PL_KPIR"
    assert api.requests[-1][2]["json_data"]["dryRun"] is True


@pytest.mark.parametrize(
    "currency,converted,supplier",
    [
        (None, None, "PL"),
        ("PLN", "PLN", "PL"),
        ("USD", "PLN", "OUTSIDE_EU"),
        ("EUR", "EUR", "DE"),
    ],
)
def test_document_currency_is_never_assumed(currency, converted, supplier):
    api = FakeApi(responder())
    args = {
        "file_content_base64": base64.b64encode(b"Synthetic receipt").decode(),
        "file_name": "fixture.txt",
        "supplier_country": supplier,
    }
    if currency:
        args.update(currency=currency, currency_exchanged=converted)
    structured(call_tool("create_attachment", args, api))
    body = api.requests[-1][2]["json_data"]
    assert (
        body.get("currency") == currency and body.get("currency_exchanged") == converted
    )
    assert body["supplier_country"] == supplier
    if currency is None:
        assert "currency" not in body and "currency_exchanged" not in body
    assert api.requests[-1][2]["files"]["file"].closed


@pytest.mark.parametrize(
    "tool,args",
    [
        ("submit_tax_report", {"report_id": "report-1"}),
        ("generate_finanzamt_preview", {"report_id": "report-1"}),
        ("get_ebilanz_positions", {"fiscal_year": 2026, "account_type": "ASSET"}),
    ],
)
def test_german_tools_block_poland_but_keep_german_requests(tool, args):
    api = FakeApi(responder())
    assert tool_payload(call_tool(tool, args, api))["code"] == "german_company_required"
    assert len(api.requests) == 1 and api.requests[0][0] == "GET"
    api = FakeApi(responder("skr04", "DE"))
    result = call_tool(tool, args, api)
    if tool != "generate_finanzamt_preview":
        structured(result)
    assert len(api.requests) >= 2


def test_resource_changes_with_selected_company_country():
    from tests.mcp_harness import read_resource

    for country, chart in [("PL", "PL_KPIR"), ("PL", "PL_FULL"), ("DE", "skr04")]:
        text = read_resource("company://current", FakeApi(responder(chart, country)))
        assert chart in text
        assert ("DATEV" in text) is (country == "DE")


def test_vat_proportion_preserves_zero_and_explicit_clear():
    api = FakeApi(responder())
    structured(call_tool("get_vat_proportion", {}, api))
    assert api.requests[-1][1].endswith("/companies/company-1/taxes/vat-proportion/")
    structured(
        call_tool(
            "update_vat_proportion",
            {
                "year": 2026,
                "estimated_percent": 0,
                "round_to_whole": False,
                "previous_taxed_turnover": "1000.00",
                "previous_exempt_turnover": "500.00",
                "fixed_asset_correction": "-12.30",
            },
            api,
        )
    )
    # A Polish company's choices are proposed for the owner to apply in Norman (tests/test_polish_settings_tools.py).
    assert api.requests[-1][0] == "POST"
    assert api.requests[-1][1].endswith("/companies/company-1/tax-setting-proposals/")
    assert api.requests[-1][2]["json_data"] == {
        "setting": "vat_proportion",
        "values": {
            "year": 2026,
            "estimatedPercent": 0,
            "roundToWhole": False,
            "previousTaxedTurnover": "1000.00",
            "previousExemptTurnover": "500.00",
            "fixedAssetCorrection": "-12.30",
        },
    }
    structured(
        call_tool("update_vat_proportion", {"year": 2026, "clear_estimate": True}, api)
    )
    assert api.requests[-1][2]["json_data"]["values"] == {"year": 2026, "estimatedPercent": None}


def test_a_polish_company_previews_its_opening_balance_through_the_migration_tools():
    """The accounting migration serves a PL_FULL sp. z o.o. too (the API's polish_opening)."""
    api = FakeApi(responder("PL_FULL"))
    args = {"manual_balances": [{"account_code": "130", "debit": "100"}], "account_mapping": {"130": "130"}}
    call_tool("preview_accounting_cutover", args, api)
    method, url, kwargs = api.requests[-1]
    assert (method, url.rsplit("/api/v1/", 1)[1]) == ("POST", "companies/company-1/accounting/cutover/preview/")
    assert kwargs["json_data"] == {
        "manual_balances": [{"account_code": "130", "debit": "100"}],
        "account_mapping": {"130": "130"},
    }
    assert "confirmationRequired" in structured(call_tool("apply_accounting_cutover", args, api))
