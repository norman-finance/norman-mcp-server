"""Read-only MCP Apps for Norman's public connector.

The tools in this module deliberately reuse Norman's existing REST API.  The
API remains authoritative; the embedded UI only presents compact, normalized
read models.  Data tools stay useful in hosts without MCP Apps support, while
the matching render tools progressively enhance the result in compatible
hosts such as ChatGPT and Claude.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urljoin

from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context

APP_RESOURCE_URI = "ui://norman/accounting-workbench-v3.html"
APP_MIME_TYPE = "text/html;profile=mcp-app"

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def _api_and_company(ctx: Context) -> tuple[Any, Optional[str], Optional[Dict[str, Any]]]:
    api = ctx.request_context.lifespan_context["api"]
    company_id = api.company_id
    if not company_id:
        return (
            api,
            None,
            {"error": "No company available. Please authenticate and select a company first."},
        )
    return api, company_id, None


def _company_url(company_id: str, suffix: str) -> str:
    return urljoin(
        config.api_base_url,
        f"api/v1/companies/{company_id}/{suffix.lstrip('/')}",
    )


def _items(payload: Any) -> list[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        rows = payload.get("results")
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    return []


def _first(item: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return value
    return default


def _name(value: Any) -> str:
    if isinstance(value, dict):
        return str(_first(value, "name", "nameEn", "name_en", "nameDe", "name_de", default=""))
    return str(value or "")


def _currency(value: Any) -> str:
    if isinstance(value, dict):
        return str(_first(value, "code", "symbol", "name", default="EUR"))
    return str(value or "EUR")


def _limited(rows: Iterable[Dict[str, Any]], limit: int) -> list[Dict[str, Any]]:
    return list(rows)[:limit]


def _document_row(item: Dict[str, Any]) -> Dict[str, Any]:
    transactions = _first(item, "transactions", default=[])
    transactions = transactions if isinstance(transactions, list) else []
    linked = bool(transactions)
    return {
        "id": str(_first(item, "public_id", "publicId", "pk", default="")),
        "fileName": str(
            _first(item, "file_name", "fileName", default="")
            or str(_first(item, "file", default="")).rsplit("/", 1)[-1]
        ),
        "type": str(_first(item, "attachment_type", "attachmentType", default="other")),
        "brand": str(_first(item, "brand_name", "brandName", default="")),
        "number": str(_first(item, "attachment_number", "attachmentNumber", default="")),
        "date": str(_first(item, "value_date", "valueDate", "created", default="")),
        "amount": _first(item, "amount", default=None),
        "currency": _currency(_first(item, "currency", default="EUR")),
        "vatRate": _first(item, "vat_rate", "vatRate", default=None),
        "description": str(_first(item, "description", default="")),
        "linked": linked,
        "transactionIds": [str(value) for value in transactions],
        "status": "Linked" if linked else "Needs match",
    }


def _category(item: Dict[str, Any]) -> tuple[str, str]:
    value = _first(item, "company_category", "companyCategory", "category", default=None)
    if not isinstance(value, dict):
        return "", _name(value)
    code = str(_first(value, "code", "accountNumber", "account_number", default=""))
    return code, _name(value)


def _transaction_row(item: Dict[str, Any]) -> Dict[str, Any]:
    category_code, category_name = _category(item)
    attachment = _first(item, "attachment", default=None)
    extras = _first(item, "additional_attachments", "additionalAttachments", default=[])
    document_not_required = bool(
        _first(item, "document_not_required", "documentNotRequired", default=False)
    )
    has_document = bool(attachment) or bool(extras) or document_not_required
    user_status = str(_first(item, "user_status", "userStatus", "status", default=""))
    categorization_status = str(
        _first(item, "categorization_status", "categorizationStatus", default="")
    )
    uses_previous_skr = bool(
        _first(item, "uses_previous_skr_account", "usesPreviousSkrAccount", default=False)
    )
    issues: list[str] = []
    if not has_document:
        issues.append("Missing document")
    if not category_code and not category_name:
        issues.append("Uncategorized")
    if user_status.upper() not in {"VERIFIED", "FINALIZED"}:
        issues.append("Needs review")
    if categorization_status.lower() in {"failed", "pending", "needs_review"}:
        issues.append("Categorization pending")
    if uses_previous_skr:
        issues.append("Previous SKR")

    return {
        "id": str(_first(item, "public_id", "publicId", "pk", default="")),
        "date": str(_first(item, "value_date", "valueDate", default="")),
        "description": str(_first(item, "description", default="")),
        "amount": _first(item, "amount", default=None),
        "currency": _currency(_first(item, "currency", default="EUR")),
        "cashflowType": str(_first(item, "cashflow_type", "cashflowType", default="")),
        "categoryCode": category_code,
        "categoryName": category_name,
        "userStatus": user_status,
        "locked": bool(_first(item, "is_locked", "isLocked", default=False)),
        "hasDocument": has_document,
        "documentNotRequired": document_not_required,
        "issues": issues,
    }


def _account_row(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "code": str(_first(item, "code", "account", default="")),
        "name": str(_first(item, "name", default="")),
        "debit": _first(item, "debit_total", "debitTotal", "debit", default="0"),
        "credit": _first(item, "credit_total", "creditTotal", "credit", default="0"),
        "balance": _first(item, "saldo", "balance", "running_saldo", default="0"),
    }


def _posting_row(item: Dict[str, Any]) -> Dict[str, Any]:
    origin = _first(item, "origin", default={})
    origin_label = (
        _name(origin) or str(_first(origin, "label", "type", default=""))
        if isinstance(origin, dict)
        else str(origin or "")
    )
    return {
        "id": str(_first(item, "public_id", "publicId", default="")),
        "entryNo": str(_first(item, "entry_no", "entryNo", default="")),
        "date": str(_first(item, "booking_date", "bookingDate", default="")),
        "debitCode": str(_first(item, "debit_code", "debitCode", default="")),
        "creditCode": str(_first(item, "credit_code", "creditCode", default="")),
        "amount": _first(item, "amount", default="0"),
        "signedAmount": _first(item, "signed_amount", "signedAmount", default="0"),
        "runningBalance": _first(item, "running_saldo", "runningSaldo", default="0"),
        "memo": str(_first(item, "memo", default="")),
        "source": str(_first(item, "source", default="")),
        "origin": origin_label,
        "taxTreatment": str(_first(item, "tax_treatment", "taxTreatment", default="")),
        "locked": bool(_first(item, "locked_at", "lockedAt", default=False)),
    }


def _error_view(view: str, title: str, error: Any) -> Dict[str, Any]:
    return {"view": view, "title": title, "error": str(error), "items": [], "summary": {}}


def _render_result(view: str, title: str, payload: Dict[str, Any]) -> CallToolResult:
    data = dict(payload)
    data["view"] = view
    data["title"] = title
    count = len(data.get("items", [])) if isinstance(data.get("items"), list) else 0
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=(
                    f"{title} data is ready with {count} visible "
                    f"row{'s' if count != 1 else ''}. Compatible clients render the attached "
                    "interactive view; do not claim that a screen opened unless the client "
                    "actually displayed it."
                ),
            )
        ],
        structuredContent=data,
        _meta={"norman/view": view},
    )


def _render_meta(invoking: str, invoked: str) -> Dict[str, Any]:
    return {
        "ui": {"resourceUri": APP_RESOURCE_URI},
        "openai/outputTemplate": APP_RESOURCE_URI,
        "openai/toolInvocation/invoking": invoking,
        "openai/toolInvocation/invoked": invoked,
    }


def register_public_apps(mcp: Any) -> None:
    """Register the public connector's portable accounting workbench."""

    @mcp.resource(
        APP_RESOURCE_URI,
        name="norman-accounting-workbench",
        title="Norman Accounting Workbench",
        description="Interactive document, reconciliation and Ledger views.",
        mime_type=APP_MIME_TYPE,
        meta={
            "ui": {
                "prefersBorder": True,
                "csp": {"connectDomains": [], "resourceDomains": []},
            },
            "openai/widgetDescription": (
                "A read-only Norman accounting workbench for reviewing documents, "
                "reconciliation issues and Ledger account postings."
            ),
            "openai/widgetPrefersBorder": True,
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            },
        },
    )
    async def accounting_workbench() -> str:
        return (Path(__file__).with_name("accounting_workbench.html")).read_text(encoding="utf-8")

    @mcp.tool(title="Get Document Review Data", annotations=READ_ONLY)
    async def get_document_review_data(
        ctx: Context,
        search: Optional[str] = Field(
            default=None, description="File name, supplier, description or document number"
        ),
        date_from: Optional[str] = Field(default=None, description="YYYY-MM-DD"),
        date_to: Optional[str] = Field(default=None, description="YYYY-MM-DD"),
        linked: Optional[bool] = Field(
            default=None,
            description="True for linked documents, false for documents needing a match",
        ),
        limit: int = Field(default=30, ge=1, le=100),
    ) -> Dict[str, Any]:
        """Use this when reviewing extracted documents or finding unmatched receipts."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return _error_view("documents", "Document Review", error["error"])
        response = await api.arequest(
            "GET",
            _company_url(company_id, "attachments/"),
            params={
                key: value
                for key, value in {
                    "search": search,
                    "date_from": date_from,
                    "date_to": date_to,
                    "ordering": "-created",
                    "pageSize": limit,
                }.items()
                if value is not None
            },
        )
        if isinstance(response, dict) and response.get("error"):
            return _error_view("documents", "Document Review", response["error"])
        rows = [_document_row(item) for item in _items(response)]
        if linked is not None:
            rows = [row for row in rows if row["linked"] is linked]
        rows = _limited(rows, limit)
        return {
            "view": "documents",
            "title": "Document Review",
            "items": rows,
            "summary": {
                "total": len(rows),
                "linked": sum(1 for row in rows if row["linked"]),
                "needsMatch": sum(1 for row in rows if not row["linked"]),
            },
            "filters": {
                "search": search or "",
                "dateFrom": date_from or "",
                "dateTo": date_to or "",
                "linked": linked,
            },
        }

    @mcp.tool(
        title="Render Document Review",
        description=(
            "Render the interactive Document Review. Always call get_document_review_data "
            "first and pass its complete result as payload."
        ),
        annotations=READ_ONLY,
        meta=_render_meta("Opening document review…", "Document review ready"),
    )
    async def render_document_review(
        ctx: Context,
        payload: Dict[str, Any] = Field(
            description="Complete result returned by get_document_review_data"
        ),
    ) -> CallToolResult:
        del ctx
        return _render_result("documents", "Document Review", payload)

    @mcp.tool(title="Get Reconciliation Cockpit Data", annotations=READ_ONLY)
    async def get_reconciliation_cockpit_data(
        ctx: Context,
        date_from: Optional[str] = Field(default=None, description="YYYY-MM-DD"),
        date_to: Optional[str] = Field(default=None, description="YYYY-MM-DD"),
        limit: int = Field(default=50, ge=1, le=100),
    ) -> Dict[str, Any]:
        """Use this when checking transactions that need documents, categories or review."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return _error_view("reconciliation", "Reconciliation Cockpit", error["error"])
        response = await api.arequest(
            "GET",
            _company_url(company_id, "accounting/transactions/"),
            params={
                key: value
                for key, value in {
                    "dateFrom": date_from,
                    "dateTo": date_to,
                    "limit": limit,
                }.items()
                if value is not None
            },
        )
        if isinstance(response, dict) and response.get("error"):
            return _error_view("reconciliation", "Reconciliation Cockpit", response["error"])
        rows = _limited((_transaction_row(item) for item in _items(response)), limit)
        return {
            "view": "reconciliation",
            "title": "Reconciliation Cockpit",
            "items": rows,
            "summary": {
                "total": len(rows),
                "needsAttention": sum(1 for row in rows if row["issues"]),
                "missingDocuments": sum(1 for row in rows if "Missing document" in row["issues"]),
                "uncategorized": sum(1 for row in rows if "Uncategorized" in row["issues"]),
                "previousSkr": sum(1 for row in rows if "Previous SKR" in row["issues"]),
            },
            "filters": {"dateFrom": date_from or "", "dateTo": date_to or ""},
        }

    @mcp.tool(
        title="Render Reconciliation Cockpit",
        description=(
            "Render the interactive Reconciliation Cockpit. Always call "
            "get_reconciliation_cockpit_data first and pass its complete result as payload."
        ),
        annotations=READ_ONLY,
        meta=_render_meta("Opening reconciliation…", "Reconciliation ready"),
    )
    async def render_reconciliation_cockpit(
        ctx: Context,
        payload: Dict[str, Any] = Field(
            description="Complete result returned by get_reconciliation_cockpit_data"
        ),
    ) -> CallToolResult:
        del ctx
        return _render_result("reconciliation", "Reconciliation Cockpit", payload)

    @mcp.tool(title="Get Ledger Explorer Data", annotations=READ_ONLY)
    async def get_ledger_explorer_data(
        ctx: Context,
        date_from: Optional[str] = Field(default=None, description="YYYY-MM-DD"),
        date_to: Optional[str] = Field(default=None, description="YYYY-MM-DD"),
        account_code: Optional[str] = Field(
            default=None,
            description="Account code to expand into its Kontenblatt; omit for the SuSa",
        ),
    ) -> Dict[str, Any]:
        """Use this when exploring account balances and drilling into Ledger postings."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return _error_view("ledger", "Ledger Explorer", error["error"])
        endpoint = "accounting/ledger/accounts/"
        if account_code:
            endpoint = f"accounting/ledger/accounts/{account_code}/"
        response = await api.arequest(
            "GET",
            _company_url(company_id, endpoint),
            params={
                key: value
                for key, value in {"dateFrom": date_from, "dateTo": date_to}.items()
                if value is not None
            },
        )
        if isinstance(response, dict) and response.get("error"):
            return _error_view("ledger", "Ledger Explorer", response["error"])

        if account_code:
            rows = [_posting_row(item) for item in _items(response)]
            return {
                "view": "ledger",
                "title": "Ledger Explorer",
                "mode": "account",
                "account": {
                    "code": account_code,
                    "debit": _first(response, "debit_total", "debitTotal", default="0"),
                    "credit": _first(response, "credit_total", "creditTotal", default="0"),
                    "balance": _first(response, "saldo", "balance", default="0"),
                },
                "items": rows,
                "summary": {"postings": len(rows)},
                "filters": {"dateFrom": date_from or "", "dateTo": date_to or ""},
            }

        rows = [_account_row(item) for item in _items(response)]
        return {
            "view": "ledger",
            "title": "Ledger Explorer",
            "mode": "accounts",
            "items": rows,
            "summary": {"accounts": len(rows)},
            "filters": {"dateFrom": date_from or "", "dateTo": date_to or ""},
        }

    @mcp.tool(
        title="Render Ledger Explorer",
        description=(
            "Render the interactive Ledger Explorer. Always call get_ledger_explorer_data "
            "first and pass its complete result as payload."
        ),
        annotations=READ_ONLY,
        meta=_render_meta("Opening Ledger…", "Ledger Explorer ready"),
    )
    async def render_ledger_explorer(
        ctx: Context,
        payload: Dict[str, Any] = Field(
            description="Complete result returned by get_ledger_explorer_data"
        ),
    ) -> CallToolResult:
        del ctx
        return _render_result("ledger", "Ledger Explorer", payload)
