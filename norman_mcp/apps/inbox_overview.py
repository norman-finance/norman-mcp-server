"""Bounded, company-scoped reads for the Inbox's financial status and actions.

Counts come from filtered API pagination, never the returned page length. The
transaction-total period is the previous and current calendar months. Unfinalized
transactions and unmatched documents deliberately cover all history.
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, urljoin

from norman_mcp import config

UNAVAILABLE = "This section is currently unavailable."
RECONNECT = "Your Norman session expired. Please reconnect."
PAGE = {"page": 1, "page_size": 1}


def _period(now: datetime | None) -> dict[str, str]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    first = current.date().replace(day=1)
    previous_first = (first - timedelta(days=1)).replace(day=1)
    next_first = (
        first.replace(year=first.year + 1, month=1)
        if first.month == 12
        else first.replace(month=first.month + 1)
    )
    return {"from": previous_first.isoformat(), "to": (next_first - timedelta(days=1)).isoformat()}


async def _read(api: Any, path: str, **kwargs: Any) -> dict[str, Any]:
    try:
        result = await api.arequest("GET", urljoin(config.api_base_url, "api/v1/" + path), **kwargs)
    except Exception:
        return {"error": UNAVAILABLE}
    if not isinstance(result, dict):
        return {"error": UNAVAILABLE}
    status = result.get("status_code")
    if result.get("error") or (isinstance(status, int) and status >= 400):
        failure: dict[str, Any] = {"error": UNAVAILABLE}
        if isinstance(status, int) and not isinstance(status, bool):
            failure["status_code"] = status
        return failure
    return result


def _count(result: dict[str, Any]) -> int | None:
    if result.get("error"):
        return None
    count = result.get("count")
    return count if isinstance(count, int) and not isinstance(count, bool) and count >= 0 else None


def _balances(result: dict[str, Any]) -> dict[str, Any]:
    unavailable = {"status": "unavailable", "values": []}
    if result.get("error"):
        return unavailable
    accounts, rows = result.get("bankAccounts"), result.get("sumsByCurrency")
    if not isinstance(accounts, list) or not isinstance(rows, list):
        return unavailable
    if not accounts or not rows:
        return {"status": "no_data", "values": [], **({"partial": True} if accounts else {})}
    amounts: dict[str, Decimal] = {}
    for row in rows:
        if not isinstance(row, dict):
            return unavailable
        currency, amount = row.get("currency"), row.get("sumAmount")
        if (
            not isinstance(currency, str)
            or not re.fullmatch(r"[A-Z]{3}", currency)
            or isinstance(amount, bool)
            or not isinstance(amount, (str, int, float, Decimal))
        ):
            return unavailable
        try:
            precise = Decimal(str(amount))
        except InvalidOperation:
            return unavailable
        if not precise.is_finite():
            return unavailable
        amounts[currency] = amounts.get(currency, Decimal(0)) + precise
    return {
        "status": "available",
        "values": [
            {"currency": currency, "amount": format(amounts[currency], "f")}
            for currency in sorted(amounts)
        ],
        # Each source row is one account snapshot, even when several rows share
        # a currency. Aggregating currencies must not hide missing accounts.
        **({"partial": True} if len(rows) < len(accounts) else {}),
    }


async def load_overview(api: Any, company: str, now: datetime | None = None) -> dict[str, Any]:
    """Read six bounded GET sources without exposing rows or performing mutations.

    The caller has resolved and pinned the company/grant. This helper leaves the
    API object's selection untouched and never resolves ambient credentials itself.
    """
    period = _period(now)
    company_path = "companies/" + quote(str(company), safe="") + "/"
    dates = {"date_from": period["from"], "date_to": period["to"]}
    balance, transactions, overdue, receipts, invoices, unreviewed = await asyncio.gather(
        _read(api, company_path + "balance/"),
        _read(api, "accounting/transactions/", params={**PAGE, **dates}),
        _read(
            api,
            company_path + "invoices/",
            params={**PAGE, "status": "overdue", "paid_status": "unpaid", "type": "invoice"},
        ),
        _read(
            api,
            company_path + "attachments/",
            params={**PAGE, "linked": True, "has_type": "receipt"},
        ),
        _read(
            api,
            company_path + "attachments/",
            params={**PAGE, "linked": True, "has_type": "invoice"},
        ),
        _read(
            api,
            "accounting/transactions/",
            params={**PAGE, "status": "UNVERIFIED"},
        ),
    )
    if any(
        source.get("status_code") == 401
        for source in (
            balance,
            transactions,
            overdue,
            receipts,
            invoices,
            unreviewed,
        )
    ):
        return {"error": RECONNECT, "status_code": 401}
    receipt_count, invoice_count = _count(receipts), _count(invoices)
    actions = {
        "overdueInvoices": _count(overdue),
        "unmatchedDocuments": (
            receipt_count + invoice_count
            if receipt_count is not None and invoice_count is not None
            else None
        ),
        "unreviewedTransactions": _count(unreviewed),
    }
    bank_balances, transaction_count = _balances(balance), _count(transactions)
    return {
        "period": period,
        "transactionsCount": transaction_count,
        "bankBalances": bank_balances,
        "actions": actions,
        "sourceAvailability": {
            "bankBalances": bank_balances["status"] != "unavailable",
            "transactionsCount": transaction_count is not None,
            **{key: value is not None for key, value in actions.items()},
        },
    }
