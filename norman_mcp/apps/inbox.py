"""Company-scoped Inbox views. The API owns all decisions and mutations."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from uuid import UUID

from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context

INBOX_URI = "ui://norman/inbox-v1.html"
READ = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


def endpoint(path: str) -> str:
    return urljoin(config.api_base_url, f"api/v1/{path}")


async def read(api: Any, path: str, **kwargs: Any) -> dict[str, Any]:
    try:
        result = await api.arequest("GET", endpoint(path), **kwargs)
        if not isinstance(result, dict) or result.get("error"):
            return {"error": "This section is currently unavailable."}
        return result
    except Exception:
        return {"error": "This section is currently unavailable."}


async def load_inbox(api: Any, page: int = 1) -> dict[str, Any]:
    company = api.company_id
    if not company:
        return {"error": "Please connect Norman and select a company."}
    runs, executions, approvals = await asyncio.gather(
        read(api, "assistant/workflow-runs/"),
        read(
            api,
            "accounting/rule-executions/",
            params={"status": "awaiting_review", "page": page, "page_size": 20},
        ),
        read(api, "assistant/approvals/"),
    )
    # Active workflows are NOT necessarily waiting on the user. The old
    # approvals aggregate includes active steps; use authoritative blocking state.
    active = runs.get("runs", [])
    questions = [r for r in active if r.get("blockedReason") and r.get("state") == "active"]
    reviews = executions.get("results", [])
    tax = [item for item in approvals.get("items", []) if item.get("kind") == "autofiling"]
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
            # The existing approvals source is capped at 50 across collectors.
            "taxReviewsShown": None if approvals.get("error") else len(tax),
        },
        "pagination": {"page": page, "hasNext": bool(executions.get("next"))},
        "unavailable": [
            name
            for name, data in (
                ("workflows", runs),
                ("approvals", executions),
                ("tax reviews", approvals),
            )
            if data.get("error")
        ],
    }


def register_inbox(mcp: Any) -> None:
    @mcp.resource(
        INBOX_URI,
        name="norman-inbox",
        title="Norman Inbox",
        mime_type="text/html;profile=mcp-app",
        meta={"ui": {"prefersBorder": False, "csp": {"connectDomains": [], "resourceDomains": []}}},
    )
    async def inbox_resource() -> str:
        return Path(__file__).with_name("inbox.html").read_text()

    @mcp.tool(title="Get Norman Inbox", annotations=READ)
    async def get_norman_inbox_data(
        ctx: Context, page: int = Field(default=1, ge=1)
    ) -> dict[str, Any]:
        """Read questions blocking workflows, pending automation approvals and tax reviews.
        Approval count comes from the paginated source, not visible rows. Tax reviews are a
        bounded list, not a complete count. Missing sections are unavailable, never zero.
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
        return CallToolResult(
            structured_content=data,
            content=[
                TextContent(
                    type="text",
                    text="Norman Inbox data loaded." if not data.get("error") else data["error"],
                )
            ],
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
        company = api.company_id
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
        return {
            "view": "approval",
            "companyId": str(company),
            "execution": execution,
            "before": before,
            "currentUnavailable": before is None,
            "canApprove": execution.get("status") == "awaiting_review",
        }
