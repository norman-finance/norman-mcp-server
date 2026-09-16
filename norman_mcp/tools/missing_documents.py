"""Read all company transactions or return an explicit unavailable result."""

from datetime import date
from typing import Any
from urllib.parse import urljoin
from uuid import UUID

from norman_mcp import config


def _valid_scope(company_id: str, date_from: str | None, date_to: str | None) -> bool:
    try:
        UUID(company_id)
        start = date.fromisoformat(date_from) if date_from else date.min
        end = date.fromisoformat(date_to) if date_to else date.max
    except (ValueError, TypeError, AttributeError):
        return False
    return start <= end


def _page(response: Any, expected: int | None, seen: set[str]) -> tuple[list[dict], int] | None:
    if not isinstance(response, dict) or "error" in response or "errors" in response:
        return None
    rows, count = response.get("results"), response.get("count")
    if not isinstance(rows, list) or not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return None
    if expected is not None and count != expected:
        return None
    for tx in rows:
        if not isinstance(tx, dict):
            return None
        pk = tx.get("publicId", tx.get("public_id"))
        # All three fields are required by TransactionListSerializer. Missing
        # keys mean an incompatible response, not a missing receipt.
        exemption_key = "documentNotRequired" if "documentNotRequired" in tx else "document_not_required"
        if not isinstance(pk, str) or pk in seen or not {"attachment", "invoice", exemption_key} <= tx.keys():
            return None
        seen.add(pk)
    return rows, count


async def missing_document_transactions(
    api: Any,
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict] | dict:
    """Use the ordinary owner/advisor-authorized company route; never switch tenants.

    Build page URLs locally, so upstream next links cannot redirect a credentialed
    request. Errors and incomplete pages must never look like a clean audit.
    """
    if not _valid_scope(company_id, date_from, date_to):
        return {"error": "Provide a valid company ID and date range.", "status": "unavailable"}
    # The API scopes this route by X-Company-Id, not the URL alone.
    if str(api.company_id or "") != company_id:
        return {"error": "Select the requested company before checking its documents.", "status": "unavailable"}

    url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/accounting/transactions/")
    params: dict[str, Any] = {"page_size": 200, "ordering": "public_id"}
    if date_from:
        params["dateFrom"] = date_from
    if date_to:
        params["dateTo"] = date_to
    results, seen = [], set()
    expected = None
    for page_number in range(1, 501):
        try:
            response = await api.arequest("GET", url, params={**params, "page": page_number})
        except Exception:  # noqa: BLE001 - API/transport failure means unavailable, never an empty collection.
            return {
                "error": "Transactions could not be retrieved. Document completeness is unknown.",
                "status": "unavailable",
            }
        parsed = _page(response, expected, seen)
        if parsed is None:
            break
        rows, expected = parsed
        results.extend(rows)
        if len(results) == expected and not response.get("next"):
            return results
        if not rows or len(results) >= expected:
            break
    return {
        "error": "Transaction pages were unavailable, incomplete or changed. Check access and retry.",
        "status": "unavailable",
    }


def needs_document(tx: dict) -> bool:
    exempt = tx.get("documentNotRequired", tx.get("document_not_required"))
    return not tx["attachment"] and not tx["invoice"] and exempt is not True


def category_name(tx: dict) -> str | None:
    category = tx.get("companyCategory", tx.get("company_category")) or tx.get("category") or {}
    return category.get("name") if isinstance(category, dict) else None
