"""Company-scoped Inbox views. The API owns all decisions and mutations."""

import asyncio
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from uuid import UUID

from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context, set_api_company_id

INBOX_URI = "ui://norman/inbox-v1.html"
READ = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


PAGE_SIZE = 20
UNAVAILABLE = "This section is currently unavailable."
# Tax Autopilot runs that wait on the user (see the API's autofiling models).
TAX_REVIEW_STATUSES = {"ready_for_approval", "needs_input"}
# Where a planned action's id resolves to a name the user can recognise.
ENTITY_PATHS = {
    "category": "accounting/categories/{id}/",
    "companyCategory": "accounting/company-categories/{id}/",
    "vendor": "accounting/vendors/{id}/",
    "client": "companies/{company}/clients/{id}/",
}
PARAM_ENTITIES = {
    "category": "category",
    "company_category": "companyCategory",
    "companyCategory": "companyCategory",
    "vendor": "vendor",
    "client": "client",
}


def endpoint(path: str) -> str:
    base_url: str = config.api_base_url
    return urljoin(base_url, f"api/v1/{path}")


def _failure(result: Any) -> dict[str, Any]:
    # Upstream text stays out of the UI, except the reconnect instruction for an
    # expired session, which is the only thing the user can act on.
    status = result.get("status_code") if isinstance(result, dict) else None
    failure: dict[str, Any] = {
        "error": result["error"] if status == 401 and result.get("error") else UNAVAILABLE
    }
    if status:
        failure["status_code"] = status
    return failure


async def read(api: Any, path: str, **kwargs: Any) -> dict[str, Any]:
    try:
        result = await api.arequest("GET", endpoint(path), **kwargs)
    except Exception:
        return {"error": UNAVAILABLE}
    if not isinstance(result, dict) or result.get("error"):
        return _failure(result)
    return result


async def read_list(api: Any, path: str, **kwargs: Any) -> list[Any] | dict[str, Any]:
    try:
        result = await api.arequest("GET", endpoint(path), **kwargs)
    except Exception:
        return {"error": UNAVAILABLE}
    return result if isinstance(result, list) else _failure(result)


async def resolve_company(api: Any) -> str | None:
    """The selected company, looked up off the event loop.

    `api.company_id` can fall back to a blocking /companies/ request; on the
    event loop that stalls every other user's request on the single replica.
    """
    company = await asyncio.to_thread(lambda: api.company_id)
    if company and getattr(api, "token_source", None) == "oauth":
        set_api_company_id(company)  # the thread's copy of the context is discarded
    return company


def tax_review(run: dict[str, Any]) -> dict[str, Any]:
    needs_input = run.get("status") == "needs_input"
    start, end = run.get("periodStart"), run.get("periodEnd")
    return {
        "key": f"autofiling:{run.get('publicId')}",
        "kind": "autofiling",
        "title": "Tax Autopilot needs your input" if needs_input else "UStVA prepared — waiting for you",
        "detail": f"{start} - {end}" if start and end else "",
        "planned": "",
        "createdAt": run.get("created"),
        "executionId": None,
        "link": "/taxes",
        "prompt": "Show me the prepared UStVA and what I am approving.",
    }


async def load_inbox(api: Any, page: int = 1) -> dict[str, Any]:
    company = await resolve_company(api)
    if not company:
        return {"error": "Please connect Norman and select a company."}

    def executions_page(number: int) -> Any:
        return read(
            api,
            "accounting/rule-executions/",
            params={"status": "awaiting_review", "page": number, "page_size": PAGE_SIZE},
        )

    runs, executions, tax_runs = await asyncio.gather(
        read(api, "assistant/workflow-runs/"),
        executions_page(page),
        # The dedicated runs list, not the approvals aggregate: that one is
        # capped at 50 items across all collectors, so newer rule approvals
        # could hide every prepared UStVA.
        read_list(api, f"companies/{company}/autofiling/runs/"),
    )
    if page > 1 and executions.get("status_code") == 404:
        # Deciding the last item on the last page empties that page and the API
        # answers 404 for it. Serve the last page that still exists instead.
        first = await executions_page(1)
        last = max(1, math.ceil((first.get("count") or 0) / PAGE_SIZE)) if not first.get("error") else 1
        page = min(page - 1, last)
        executions = first if page == 1 else await executions_page(page)
    for data in (runs, executions, tax_runs):
        if isinstance(data, dict) and data.get("status_code") == 401:
            return {"error": data["error"], "reconnect": True}
    # Active workflows are NOT necessarily waiting on the user. The old
    # approvals aggregate includes active steps; use authoritative blocking state.
    active = runs.get("runs", [])
    questions = [r for r in active if r.get("blockedReason") and r.get("state") == "active"]
    reviews = executions.get("results", [])
    tax_failed = isinstance(tax_runs, dict)
    tax = (
        []
        if tax_failed
        else [tax_review(r) for r in tax_runs if isinstance(r, dict) and r.get("status") in TAX_REVIEW_STATUSES]
    )
    return {
        "view": "inbox",
        "companyId": str(company),
        "asOf": datetime.now(timezone.utc).isoformat(),
        "questions": questions,
        "runs": active,
        "approvals": reviews,
        "taxReviews": tax,
        "summary": {
            "questions": None if runs.get("error") else len(questions),
            "approvals": None if executions.get("error") else executions.get("count"),
            "taxReviewsShown": None if tax_failed else len(tax),
        },
        "pagination": {"page": page, "hasNext": bool(executions.get("next"))},
        "unavailable": [
            name
            for name, failed in (
                ("workflows", bool(runs.get("error"))),
                ("approvals", bool(executions.get("error"))),
                ("tax reviews", tax_failed),
            )
            if failed
        ],
    }


def entity_label(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    name = data.get("name") or data.get("title")
    code = data.get("code") or data.get("accountNumber")
    if name and code:
        return f"{code} {name}"
    return str(name) if name else None


async def entity_labels(api: Any, company: str, wanted: set[tuple[str, str]]) -> dict[tuple[str, str], str]:
    async def one(kind: str, ident: str) -> str | None:
        try:
            ident = str(UUID(ident))
        except ValueError:
            return None
        return entity_label(await read(api, ENTITY_PATHS[kind].format(id=ident, company=company)))

    keys = sorted(wanted)
    names = await asyncio.gather(*(one(kind, ident) for kind, ident in keys))
    return {key: name for key, name in zip(keys, names) if name}


def register_inbox(mcp: Any) -> None:
    @mcp.resource(
        INBOX_URI,
        name="norman-inbox",
        title="Norman Inbox",
        mime_type="text/html;profile=mcp-app",
        meta={"ui": {"prefersBorder": False, "csp": {"connectDomains": [], "resourceDomains": []}}},
    )
    async def inbox_resource() -> str:
        return Path(__file__).with_name("inbox.html").read_text(encoding="utf-8")

    @mcp.tool(title="Get Norman Inbox", annotations=READ)
    async def get_norman_inbox_data(
        ctx: Context, page: int = Field(default=1, ge=1)
    ) -> dict[str, Any]:
        """Read questions blocking workflows, pending automation approvals and tax reviews.
        Approval count comes from the paginated source, not visible rows. Tax reviews are the
        company's recent Tax Autopilot runs waiting on the user. Missing sections are
        unavailable, never zero.
        This tool never starts a workflow, changes the books, sends a message or files taxes.
        """
        return await load_inbox(ctx.request_context.lifespan_context["api"], page)

    @mcp.tool(
        title="Open Norman Inbox",
        annotations=READ,
        meta={
            "ui": {"resourceUri": INBOX_URI},
            "openai/outputTemplate": INBOX_URI,
            "openai/ui": {"entrypoints": [{"type": "global"}, {"type": "thread"}]},
        },
    )
    async def open_norman_inbox(ctx: Context) -> CallToolResult:
        """Open Norman's Inbox beside the conversation or from the sidebar.
        Load the selected company's current state. Rendering never approves anything.
        """
        data = await load_inbox(ctx.request_context.lifespan_context["api"])
        summary = data.get("summary", {})
        counts = {
            key: "unavailable" if value is None else str(value) for key, value in summary.items()
        }
        text = data.get("error") or (
            f"Norman Inbox: {counts['questions']} workflows awaiting your answer; "
            f"{counts['approvals']} pending automation approvals; "
            f"{counts['taxReviewsShown']} tax reviews."
        )
        if data.get("unavailable"):
            text += " Unavailable sections: " + ", ".join(data["unavailable"]) + "."
        if not data.get("error"):
            text += (
                " Compatible clients render the attached Inbox view; do not claim that a "
                "screen opened unless the client actually displayed it."
            )
        return CallToolResult(
            structured_content=data,
            content=[TextContent(type="text", text=text)],
        )

    @mcp.tool(title="Review Automation Approval", annotations=READ)
    async def get_norman_approval_data(ctx: Context, execution_id: str) -> dict[str, Any]:
        """Read one execution and its current transaction before the user decides.
        Show every planned action, including external effects. No inferred changes or
        automatic approval. Refresh after approve/dismiss/undo to report actual status.
        """
        try:
            execution_id = str(UUID(execution_id))
        except ValueError:
            return {"error": "A valid execution UUID is required."}
        api = ctx.request_context.lifespan_context["api"]
        company = await resolve_company(api)
        if not company:
            return {"error": "Please connect Norman and select a company."}
        execution = await read(api, f"accounting/rule-executions/{execution_id}/")
        if execution.get("error"):
            return execution
        transaction = execution.get("transaction") or {}
        current = None
        transaction_id = transaction.get("publicId")
        if transaction_id:
            try:
                transaction_id = str(UUID(str(transaction_id)))
            except ValueError:
                return {"error": "Invalid transaction reference in approval."}
            current = await read(
                api, f"companies/{company}/accounting/transactions/{transaction_id}/"
            )
        # Only forward current fields useful to a review, not the whole financial record.
        before = (
            None
            if current is None or current.get("error")
            else {
                key: current.get(key)
                for key in (
                    "category",
                    "companyCategory",
                    "vatRate",
                    "vendor",
                    "client",
                    "paymentType",
                    "userStatus",
                )
            }
        )
        # Planned actions and the current record reference ids; resolve them to
        # names so the user never approves an opaque UUID.
        wanted: set[tuple[str, str]] = set()
        if before is not None:
            for field in ENTITY_PATHS:
                value = before.get(field)
                if isinstance(value, str) and value and not entity_label(current.get(f"{field}Details")):
                    wanted.add((field, value))
        actions = [a for a in execution.get("actionsPlanned") or [] if isinstance(a, dict)]
        for action in actions:
            for key, value in (action.get("params") or {}).items():
                if key in PARAM_ENTITIES and isinstance(value, str):
                    wanted.add((PARAM_ENTITIES[key], value))
        names = await entity_labels(api, str(company), wanted) if wanted else {}
        if before is not None:
            for field in ENTITY_PATHS:
                value = before.get(field)
                label = (
                    entity_label(value)
                    or entity_label(current.get(f"{field}Details"))
                    or names.get((field, str(value)))
                )
                if label:
                    before[f"{field}Label"] = label
        for action in actions:
            labels = {
                key: names[(PARAM_ENTITIES[key], value)]
                for key, value in (action.get("params") or {}).items()
                if key in PARAM_ENTITIES and (PARAM_ENTITIES[key], value) in names
            }
            if labels:
                action["labels"] = labels
        return {
            "view": "approval",
            "companyId": str(company),
            "execution": execution,
            "before": before,
            "currentUnavailable": before is None,
            "canApprove": execution.get("status") == "awaiting_review",
        }
