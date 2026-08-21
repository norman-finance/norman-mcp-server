import logging
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin

from pydantic import Field

from mcp.types import ToolAnnotations
from norman_mcp.context import Context
from norman_mcp import config

logger = logging.getLogger(__name__)

PREVIEW_SAMPLE_SIZE = 10
EXECUTIONS_SAMPLE_SIZE = 15

CONDITION_FIELDS_HELP = (
    'Condition items, each {"field", "operator", "value"}. Fields: description | '
    "cashflow_type | amount | iban. Operators for text fields: contains | not_contains | "
    "equals | not_equals | starts_with | regex; for amount: gt | lt | gte | lte | equals. "
    'cashflow_type uses equals with value "INCOME" or "EXPENSE"; amount values are plain '
    'numbers passed as strings, e.g. "100".'
)


def _rules_url(path: str = "") -> str:
    return urljoin(config.api_base_url, f"api/v1/accounting/rules/{path}")


def _approvals_url() -> str:
    return urljoin(config.api_base_url, "api/v1/assistant/approvals/")


def _agents_url(path: str = "") -> str:
    return urljoin(config.api_base_url, f"api/v1/accounting/agents/{path}")


def _executions_url(path: str = "") -> str:
    return urljoin(config.api_base_url, f"api/v1/accounting/rule-executions/{path}")


def _without_none(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def register_rule_tools(mcp):
    """Register automation-rule tools with the MCP server.

    Automation rules ("Norman Agents") are user-defined IF-conditions
    THEN-set-category rules that run BEFORE the AI on every new and imported
    transaction. First match by priority wins; new rules are appended at the
    end of the priority list.

    Author a rule when the user says things like "always book Telekom to
    Internet costs", "create a rule for this", or keeps correcting the same
    merchant. Flow: preview_rule (show sample matches) -> create_rule -> offer
    apply_rule_to_existing for the uncategorized backlog.

    Categories: freelancer companies use category_id (a child/leaf category
    UUID from the transaction payload or a categorize_transaction suggestion);
    GmbH/UG (SME) companies use company_category_id instead. Never send both.

    Paywall: the free plan includes ONE active automation. An error carrying
    "automation_limit_reached" is not a transient failure — do not retry;
    explain that more automations need a paid plan and offer to save the rule
    as an inactive draft (is_active=false) instead.
    """

    @mcp.tool(
        title="List Automation Rules",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_rules(ctx: Context) -> Dict[str, Any]:
        """
        List the company's automation rules together with usage stats and the
        plan's automation limit.

        Returns:
            Rules ordered by priority (first match wins) and a summary with
            match counts and the `limits` block (activeLimit/activeUsed).
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        rules = api._make_request("GET", _rules_url())
        summary = api._make_request("GET", _rules_url("summary/"))
        return {"rules": rules, "summary": summary}

    @mcp.tool(
        title="Preview Automation Rule",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def preview_rule(
        ctx: Context,
        conditions: List[Dict[str, str]] = Field(description=CONDITION_FIELDS_HELP),
        logic: str = Field(
            default="AND",
            description='How items combine: "AND" (all must match) or "OR" (any matches)',
        ),
    ) -> Dict[str, Any]:
        """
        Dry-run rule conditions against recent transactions BEFORE creating the
        rule. Show the user a few of the returned matches so they can confirm
        the rule catches the right things.

        Returns:
            A sample of matching transactions and the total sampled count.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        matched = api._make_request(
            "POST",
            _rules_url("preview/"),
            json_data={"conditions": {"logic": logic, "items": conditions}},
        )
        if isinstance(matched, list):
            return {"sampleMatches": matched[:PREVIEW_SAMPLE_SIZE], "sampledFrom": len(matched)}
        return matched

    @mcp.tool(
        title="Create Automation Rule",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def create_rule(
        ctx: Context,
        name: str = Field(description="Short human-readable rule name, e.g. 'Telekom -> Internet costs'"),
        conditions: List[Dict[str, str]] = Field(description=CONDITION_FIELDS_HELP),
        logic: str = Field(
            default="AND",
            description='How items combine: "AND" (all must match) or "OR" (any matches)',
        ),
        category_id: Optional[str] = Field(
            default=None,
            description="Freelancer child-category UUID to set on matching transactions",
        ),
        company_category_id: Optional[str] = Field(
            default=None,
            description="SME CompanyCategory UUID to set on matching transactions (GmbH/UG companies)",
        ),
        is_active: bool = Field(default=True, description="Create enabled (true) or as an inactive draft (false)"),
    ) -> Dict[str, Any]:
        """
        Create an automation rule. Preview first with preview_rule. Send exactly
        one of category_id / company_category_id (freelancer vs SME). After
        creating, offer apply_rule_to_existing to also categorize the backlog.

        Returns:
            The created rule.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        payload = _without_none(
            {
                "name": name,
                "conditions": {"logic": logic, "items": conditions},
                "category": category_id,
                "companyCategory": company_category_id,
                "isActive": is_active,
            }
        )
        return api._make_request("POST", _rules_url(), json_data=payload)

    @mcp.tool(
        title="Update Automation Rule",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def update_rule(
        ctx: Context,
        rule_id: str = Field(description="Rule publicId from list_rules"),
        name: Optional[str] = Field(default=None, description="New rule name"),
        conditions: Optional[List[Dict[str, str]]] = Field(default=None, description=CONDITION_FIELDS_HELP),
        logic: str = Field(
            default="AND",
            description='Used only together with conditions: "AND" or "OR"',
        ),
        category_id: Optional[str] = Field(default=None, description="Freelancer child-category UUID"),
        company_category_id: Optional[str] = Field(default=None, description="SME CompanyCategory UUID"),
        is_active: Optional[bool] = Field(default=None, description="Enable (true) or disable (false) the rule"),
    ) -> Dict[str, Any]:
        """
        Update an automation rule. Only the provided fields change.
        Re-activating a rule counts against the plan's automation limit like
        creating one.

        Returns:
            The updated rule.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        payload = _without_none(
            {
                "name": name,
                "conditions": {"logic": logic, "items": conditions} if conditions is not None else None,
                "category": category_id,
                "companyCategory": company_category_id,
                "isActive": is_active,
            }
        )
        return api._make_request("PATCH", _rules_url(f"{rule_id}/"), json_data=payload)

    @mcp.tool(
        title="Delete Automation Rule",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def delete_rule(
        ctx: Context,
        rule_id: str = Field(description="Rule publicId from list_rules"),
    ) -> Dict[str, Any]:
        """
        Delete an automation rule after the user confirms. Prefer disabling
        (update_rule with is_active=false) when the user may want it back.

        Returns:
            Deletion confirmation.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        api._make_request("DELETE", _rules_url(f"{rule_id}/"))
        return {"status": "deleted", "ruleId": rule_id}

    @mcp.tool(
        title="Apply Rule To Existing Transactions",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def apply_rule_to_existing(
        ctx: Context,
        rule_id: str = Field(description="Rule publicId from list_rules or a create_rule response"),
    ) -> Dict[str, Any]:
        """
        Run an existing rule over the company's uncategorized transactions and
        categorize every match now. Use after create_rule when the user also
        wants the backlog cleaned up.

        Returns:
            The number of transactions updated.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        return api._make_request("POST", _rules_url(f"{rule_id}/apply-to-existing/"))

    @mcp.tool(
        title="List Rule Executions",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_rule_executions(
        ctx: Context,
        status: Optional[str] = Field(
            default=None,
            description=(
                "Filter by status: awaiting_review (the review queue) | success | partial | "
                "failed | skipped | dismissed | pending. Omit for everything, newest first."
            ),
        ),
        rule_id: Optional[str] = Field(default=None, description="Filter by rule publicId"),
    ) -> Dict[str, Any]:
        """
        Automation execution log. status=awaiting_review lists the matches a
        review-first rule parked for the user's approval — show each one (rule
        name, transaction/invoice, planned actions) and let the user decide;
        never approve or dismiss without an explicit go-ahead.

        Returns:
            A sample of executions and the total sampled count.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        params: Dict[str, Any] = {}
        if status:
            params["status"] = status
        if rule_id:
            params["rule"] = rule_id
        executions = api._make_request("GET", _executions_url(), params=params)
        if isinstance(executions, list):
            return {"executions": executions[:EXECUTIONS_SAMPLE_SIZE], "sampledFrom": len(executions)}
        return executions

    @mcp.tool(
        title="List Pending Approvals",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_pending_approvals(ctx: Context) -> Dict[str, Any]:
        """
        Everything an agent prepared and is waiting on the user for, in one
        list: review-first automations, a prepared UStVA, an active workflow
        step. Use this for "what needs me?" instead of guessing across
        surfaces.

        Items with an executionId can be decided here (approve_rule_execution
        or dismiss_rule_execution) once the user says so; the rest carry a link
        to the screen that owns the decision.

        Returns:
            items and count.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        return api._make_request("GET", _approvals_url())

    @mcp.tool(
        title="Undo Rule Execution",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def undo_rule_execution(
        ctx: Context,
        execution_id: str = Field(description="Execution publicId from list_rule_executions"),
    ) -> Dict[str, Any]:
        """
        Put back what an automation changed, newest action first, AFTER the
        user asked for it.

        Only a run that changed something can be undone, and only once.
        Actions that left the world outside the books - a notification, a
        queued reminder, a prepared payment - cannot be taken back and come
        back as "not reversible"; say so rather than implying the run was
        fully reverted.

        Returns:
            The execution, stamped revertedAt.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        return api._make_request("POST", _executions_url(f"{execution_id}/undo/"))

    @mcp.tool(
        title="List Agents",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_agents(ctx: Context) -> Dict[str, Any]:
        """
        The prebuilt agents shelf with each card's state and counters: AI
        categorization, auto-enrichment, document reconciliation, invoice
        chasing, bill payments with approval, VAT-return readiness, client
        document chasing, the month-end close, the document collector, plus
        links to Tax Autopilot and recurring invoices.

        Returns:
            cards, each with key, kind, enabled and counters.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        return api._make_request("GET", _agents_url())

    @mcp.tool(
        title="Toggle Agent",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def toggle_agent(
        ctx: Context,
        key: str = Field(description="Card key from list_agents, e.g. vat_readiness"),
        enabled: bool = Field(description="True turns the agent on, False turns it off"),
    ) -> Dict[str, Any]:
        """
        Turn a prebuilt agent on or off after the user asked for it.

        What that means depends on the card: a toggle card flips a pipeline, a
        rule card (invoice chasing, bill payments) materializes or parks a
        review-first rule, and a workflow card starts or abandons its run.
        Turning something on can be refused on a limited plan - relay the
        message instead of retrying.

        Returns:
            The card in its new state.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        return api._make_request("POST", _agents_url(f"{key}/toggle/"), json_data={"enabled": enabled})

    @mcp.tool(
        title="Approve Rule Execution",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def approve_rule_execution(
        ctx: Context,
        execution_id: str = Field(description="Execution publicId from list_rule_executions"),
    ) -> Dict[str, Any]:
        """
        Approve an awaiting-review execution AFTER the user explicitly
        confirmed it: the rule's full action chain runs (category, VAT,
        reminder emails, ...).

        Returns:
            The execution with per-action results.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        return api._make_request("POST", _executions_url(f"{execution_id}/approve/"))

    @mcp.tool(
        title="Dismiss Rule Execution",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def dismiss_rule_execution(
        ctx: Context,
        execution_id: str = Field(description="Execution publicId from list_rule_executions"),
    ) -> Dict[str, Any]:
        """
        Reject an awaiting-review execution after the user said no. The target
        goes back through normal categorization, and this rule never re-claims
        the same target.

        Returns:
            The dismissed execution.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        return api._make_request("POST", _executions_url(f"{execution_id}/dismiss/"))
