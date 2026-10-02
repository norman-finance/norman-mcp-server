"""Reject explicit tombstones from operational entity reads.

The API owns active-only querysets and pagination. This is a response guard,
not a second query engine: removing rows locally would leave counts and financial
totals incorrect. Historical snapshots and ledger/audit endpoints are untouched.
"""

import re
from typing import Any
from urllib.parse import urlsplit


_UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
_ENTITY_PATH = re.compile(
    r"/api/v1/(?:companies/[^/]+/)?"
    r"(?P<entity>accounting/transactions|invoices|attachments)"
    rf"(?:/(?P<id>{_UUID}))?/?"
)


def is_deleted_record(record: Any, *, invoice: bool = False) -> bool:
    """Recognize explicit API tombstones, never archive or business statuses."""
    if not isinstance(record, dict):
        return False
    if any(record.get(key) is True for key in ("isDeleted", "is_deleted")):
        return True
    if any(
        isinstance(record.get(key), str) and bool(record[key].strip())
        for key in ("deletedAt", "deleted_at")
    ):
        return True
    status = record.get("status")
    return invoice and isinstance(status, str) and status.casefold() == "removed"


def enforce_active_records(method: str, url: str, payload: Any) -> Any:
    """Fail closed for stale operational records without inventing page totals."""
    path = urlsplit(url).path
    match = _ENTITY_PATH.fullmatch(path) if method.upper() == "GET" else None
    preview = method.upper() == "POST" and path.rstrip("/") == "/api/v1/accounting/rules/preview"
    if match is None and not preview:
        return payload

    invoice = match is not None and match.group("entity") == "invoices"
    if match is not None and match.group("id"):
        if is_deleted_record(payload, invoice=invoice):
            return {"error": "Resource not found", "status_code": 404}
        return payload

    rows = payload.get("results") if isinstance(payload, dict) else payload
    if isinstance(rows, list) and any(is_deleted_record(row, invoice=invoice) for row in rows):
        return {
            "error": "Active records could not be verified. This section is unavailable.",
            "status": "unavailable",
        }
    return payload
