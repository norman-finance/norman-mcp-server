"""Use authoritative API shapes to verify Inbox overview scope and failures."""

import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest

from norman_mcp.apps.inbox_overview import RECONNECT, load_overview

COMPANY = "11111111-1111-4111-8111-111111111111"
NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)


def page(count):
    return {
        "count": count,
        "next": "another-page" if isinstance(count, int) and count > 1 else None,
        "previous": None,
        "results": (
            [{"publicId": "private-row", "description": "private financial row"}] if count else []
        ),
    }


class API:
    def __init__(self):
        self.calls = []
        self.company_id = COMPANY
        self.responses = {
            "balance": {
                "balance": "999999.99",  # Never substitute the converted aggregate.
                "balanceUnit": 99999999,
                "bankAccounts": ["eur-bank", "usd-bank", "other-eur-bank"],
                "sumsByCurrency": [
                    {"currency": "EUR", "sumAmount": "10.10", "sumAmountUnit": 1010},
                    {"currency": "USD", "sumAmount": "-4.25", "sumAmountUnit": -425},
                    {"currency": "EUR", "sumAmount": "0.20", "sumAmountUnit": 20},
                ],
                "taxReport": "private tax data",
            },
            "transactions": page(125),
            "overdue": page(107),
            "receipts": page(12),
            "invoices": page(3),
            "unreviewed": page(89),
        }

    async def arequest(self, method, url, **kwargs):
        assert method == "GET"
        self.calls.append((method, url, kwargs))
        path, params = urlsplit(url).path, kwargs.get("params", {})
        if path.endswith("balance/"):
            key = "balance"
        elif path.endswith("transactions/"):
            key = "unreviewed" if params.get("status") == "UNVERIFIED" else "transactions"
        elif path.endswith("attachments/"):
            key = "receipts" if params["has_type"] == "receipt" else "invoices"
        elif path.endswith("invoices/"):
            key = "overdue"
        else:
            raise AssertionError(url)
        result = self.responses[key]
        if isinstance(result, Exception):
            raise result
        return copy.deepcopy(result)


def load(api, now=NOW, company=COMPANY):
    return asyncio.run(load_overview(api, company, now))


def test_overview_counts_filtered_totals_and_sums_original_currency_snapshots():
    api = API()
    data = load(api)
    assert data == {
        "period": {"from": "2026-09-01", "to": "2026-10-31"},
        "transactionsCount": 125,
        "bankBalances": {
            "status": "available",
            "values": [
                {"currency": "EUR", "amount": "10.30"},
                {"currency": "USD", "amount": "-4.25"},
            ],
        },
        "actions": {
            "overdueInvoices": 107,
            "unmatchedDocuments": 15,
            "unreviewedTransactions": 89,
        },
        "sourceAvailability": {
            "bankBalances": True,
            "transactionsCount": True,
            "overdueInvoices": True,
            "unmatchedDocuments": True,
            "unreviewedTransactions": True,
        },
    }
    serialized = json.dumps(data)
    assert "private" not in serialized and "taxReport" not in serialized
    assert "999999" not in serialized and "publicId" not in serialized


def test_exact_company_scopes_read_only_methods_filters_and_bounded_pages():
    api = API()
    load(api)
    assert len(api.calls) == 6
    dates = {"date_from": "2026-09-01", "date_to": "2026-10-31"}
    paginated = {"page": 1, "page_size": 1}
    assert api.company_id == COMPANY
    expected = [
        ("GET", f"/api/v1/companies/{COMPANY}/balance/", {}),
        ("GET", "/api/v1/accounting/transactions/", {"params": {**paginated, **dates}}),
        (
            "GET",
            f"/api/v1/companies/{COMPANY}/invoices/",
            {
                "params": {
                    **paginated,
                    "status": "overdue",
                    "paid_status": "unpaid",
                    "type": "invoice",
                }
            },
        ),
        (
            "GET",
            f"/api/v1/companies/{COMPANY}/attachments/",
            {"params": {**paginated, "linked": True, "has_type": "receipt"}},
        ),
        (
            "GET",
            f"/api/v1/companies/{COMPANY}/attachments/",
            {"params": {**paginated, "linked": True, "has_type": "invoice"}},
        ),
        (
            "GET",
            "/api/v1/accounting/transactions/",
            {"params": {**paginated, "status": "UNVERIFIED"}},
        ),
    ]
    assert [(method, urlsplit(url).path, kwargs) for method, url, kwargs in api.calls] == expected


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 1, 1), {"from": "2025-12-01", "to": "2026-01-31"}),
        (datetime(2024, 2, 29, tzinfo=timezone.utc), {"from": "2024-01-01", "to": "2024-02-29"}),
        (datetime(2026, 12, 31, tzinfo=timezone.utc), {"from": "2026-11-01", "to": "2026-12-31"}),
        (
            datetime(2026, 10, 1, 0, tzinfo=timezone(timedelta(hours=2))),
            {"from": "2026-08-01", "to": "2026-09-30"},
        ),
    ],
)
def test_period_rollovers_and_timezone_are_utc(now, expected):
    assert load(API(), now)["period"] == expected


@pytest.mark.parametrize("count", [None, True, False, -1, "5", 1.5])
def test_invalid_counts_remain_unknown(count):
    api = API()
    api.responses["transactions"]["count"] = count
    api.responses["overdue"]["count"] = count
    data = load(api)
    assert data["transactionsCount"] is None
    assert data["actions"]["overdueInvoices"] is None
    assert data["sourceAvailability"]["transactionsCount"] is False
    assert data["sourceAvailability"]["overdueInvoices"] is False
    assert data["actions"]["unreviewedTransactions"] == 89


def test_one_document_type_failure_does_not_present_a_partial_total():
    api = API()
    api.responses["invoices"] = {"error": "private upstream detail", "status_code": 500}
    data = load(api)
    assert data["actions"]["unmatchedDocuments"] is None
    assert data["sourceAvailability"]["unmatchedDocuments"] is False
    assert data["actions"]["overdueInvoices"] == 107
    assert "private" not in json.dumps(data)


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("private exception"),
        [],
        None,
        {"error": "private detail"},
        {"status_code": 503},
    ],
)
def test_failed_or_malformed_source_remains_unavailable(failure):
    api = API()
    api.responses["unreviewed"] = failure
    data = load(api)
    assert data["actions"]["unreviewedTransactions"] is None
    assert data["sourceAvailability"]["unreviewedTransactions"] is False
    assert data["transactionsCount"] == 125
    assert "private" not in json.dumps(data)


@pytest.mark.parametrize("key", ["balance", "transactions", "unreviewed"])
def test_401_returns_only_generic_reconnect_without_financial_data(key):
    api = API()
    api.responses[key] = {"error": "private url and token", "status_code": 401}
    assert load(api) == {"error": RECONNECT, "status_code": 401}


def test_403_keeps_full_schema_and_unavailable_section_without_raw_error():
    api = API()
    api.responses["unreviewed"] = {"error": "private permission details", "status_code": 403}
    data = load(api)
    assert "error" not in data and "status_code" not in data
    assert data["actions"]["unreviewedTransactions"] is None
    assert data["sourceAvailability"]["unreviewedTransactions"] is False
    assert data["actions"]["overdueInvoices"] == 107


@pytest.mark.parametrize(
    ("accounts", "rows"),
    [([], []), (["connected"], []), ([], [{"currency": "EUR", "sumAmount": "123.00"}])],
)
def test_absent_bank_data_has_no_invented_zero(accounts, rows):
    api = API()
    api.responses["balance"]["bankAccounts"] = accounts
    api.responses["balance"]["sumsByCurrency"] = rows
    data = load(api)
    assert data["bankBalances"] == {
        "status": "no_data",
        "values": [],
        **({"partial": True} if accounts else {}),
    }
    assert data["sourceAvailability"]["bankBalances"] is True


def test_missing_account_snapshot_is_explicitly_partial_without_invented_balance():
    api = API()
    api.responses["balance"]["bankAccounts"] = ["known-account", "missing-account"]
    api.responses["balance"]["sumsByCurrency"] = [
        {"currency": "EUR", "sumAmount": "123.40", "sumAmountUnit": 12340}
    ]
    data = load(api)
    assert data["bankBalances"] == {
        "status": "available",
        "values": [{"currency": "EUR", "amount": "123.40"}],
        "partial": True,
    }
    assert data["sourceAvailability"]["bankBalances"] is True


@pytest.mark.parametrize(
    "row",
    [
        {"currency": "EUR", "sumAmount": "NaN"},
        {"currency": "EUR", "sumAmount": "Infinity"},
        {"currency": "EUR", "sumAmount": True},
        {"currency": "EUR", "sumAmount": None},
        {"currency": "EUR", "sumAmount": "invalid"},
        {"currency": "private currency", "sumAmount": "1.00"},
        {"currency": "EUR", "sumAmountUnit": 100},
        None,
    ],
)
def test_malformed_bank_snapshot_invalidates_total_instead_of_hiding_row(row):
    api = API()
    api.responses["balance"]["sumsByCurrency"].append(row)
    data = load(api)
    assert data["bankBalances"] == {"status": "unavailable", "values": []}
    assert data["sourceAvailability"]["bankBalances"] is False


def test_explicit_zero_and_negative_snapshots_are_valid_amounts():
    api = API()
    api.responses["balance"]["bankAccounts"] = ["known-account"]
    api.responses["balance"]["sumsByCurrency"] = [{"currency": "EUR", "sumAmount": "0.00"}]
    api.responses["transactions"] = page(0)
    api.responses["unreviewed"] = page(0)
    data = load(api)
    assert data["bankBalances"] == {
        "status": "available",
        "values": [{"currency": "EUR", "amount": "0.00"}],
    }
    assert data["transactionsCount"] == data["actions"]["unreviewedTransactions"] == 0
    assert all(data["sourceAvailability"].values())
