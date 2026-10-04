import logging
from typing import Any, Dict
from urllib.parse import urljoin

from pydantic import Field

from mcp.types import ToolAnnotations
from norman_mcp.context import Context
from norman_mcp import config

logger = logging.getLogger(__name__)

NO_COMPANY = {"error": "No company available. Please authenticate first."}


def _runs_url(path: str = "") -> str:
    return urljoin(config.api_base_url, f"api/v1/assistant/workflow-runs/{path}")


def _manifests_url() -> str:
    return urljoin(config.api_base_url, "api/v1/assistant/workflow-manifests/")


def _routines_url() -> str:
    return urljoin(config.api_base_url, "api/v1/assistant/routines/")


def _digest_url() -> str:
    return urljoin(config.api_base_url, "api/v1/assistant/agent-digest/")


def _explained(result: Dict[str, Any]) -> Dict[str, Any]:
    """Turn the two refusals a user can act on into words the assistant can
    relay. The generic client reports a 429 as a rate limit, but here it
    means the month's AI messages are used up."""
    if not isinstance(result, dict) or "error" not in result:
        return result
    if result.get("status_code") == 429:
        return {
            "error": (
                "This month's AI messages are used up, so Norman cannot continue the "
                "workflow now. It can continue when the messages renew next month."
            ),
            "code": "chat_limit_reached",
        }
    if "automation_paid_feature" in str(result.get("detail", "")):
        return {
            "error": (
                "Running a workflow by itself is part of a paid Norman plan. Running it "
                "by hand stays free."
            ),
            "code": "automation_paid_feature",
        }
    return result


def register_workflow_tools(mcp):
    """Register Norman workflow tools with the MCP server.

    A workflow is a checklist Norman runs on its own servers, step after
    step: monthly reconciliation, closing the month, getting ready for the
    VAT return, invoice to payment, client document requests. Starting one
    returns immediately; the run continues in the background and stops only
    when a step needs the user: a question (answer_workflow_question), a
    manual step (complete_workflow_step), a bank or source to connect, or
    the month's AI messages running out. The step list belongs to the
    server — read it with get_workflow_run, never track progress yourself.
    """

    @mcp.tool(
        title="List Workflows",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_workflows(ctx: Context) -> Dict[str, Any]:
        """
        The workflows this company can run, each with its steps, its default
        period and its schedule if it runs by itself, plus the runs that are
        active now and the latest run of each workflow.

        Use it for "what can Norman do for me?" and to find a run that is
        waiting on the user: a run whose blockedReason is user_input has a
        question in blockedDetail.

        Returns:
            workflows, activeRuns and latestRuns.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return NO_COMPANY

        manifests = api._make_request("GET", _manifests_url())
        if "error" in manifests:
            return manifests
        runs = api._make_request("GET", _runs_url())
        if "error" in runs:
            return runs
        routines = api._make_request("GET", _routines_url())
        schedules = {
            routine.get("key"): routine
            for routine in ([] if "error" in routines else routines.get("routines", []))
            if routine.get("kind") == "monthly_workflow" and routine.get("status") == "confirmed"
        }
        return {
            "workflows": [
                {**manifest, "schedule": schedules.get(manifest.get("key"))}
                for manifest in manifests.get("available", [])
            ],
            "activeRuns": runs.get("runs", []),
            "latestRuns": runs.get("latestRuns", []),
        }

    @mcp.tool(
        title="Get Workflow Run",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_workflow_run(
        ctx: Context,
        run_id: str = Field(description="Workflow run publicId from list_workflows or start_workflow"),
    ) -> Dict[str, Any]:
        """
        One workflow run with its steps: which are done, which is active,
        each step's summary, and why the run is waiting (blockedReason:
        user_input, manual_step, source_required, ai_limit, step_failed).

        A run keeps going in the background after start_workflow; check it
        again later rather than in a tight loop.

        Returns:
            The run.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return NO_COMPANY

        return api._make_request("GET", _runs_url(f"{run_id}/"))

    @mcp.tool(
        title="Start Workflow",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    async def start_workflow(
        ctx: Context,
        workflow_key: str = Field(description="Workflow key from list_workflows, e.g. month-end-close"),
        period_start: str = Field(
            default="",
            description="Inclusive ISO date for a period workflow, e.g. 2026-08-01. Empty = its default period",
        ),
        period_end: str = Field(
            default="",
            description="Inclusive ISO date for a period workflow, e.g. 2026-08-31. Empty = its default period",
        ),
    ) -> Dict[str, Any]:
        """
        Start a workflow when the user asks for it; an active run of the same
        workflow is resumed instead of starting a second one. Norman then
        works through the steps on its servers.

        Before starting, tell the user what it will do (the steps from
        list_workflows). Most steps change only the books: categorizing,
        matching documents, checks. Invoice to payment and client document
        requests send to clients only when the user asked for sending; the
        VAT readiness workflow emails the company owner when it is done.

        Returns:
            The run; follow it with get_workflow_run.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return NO_COMPANY

        payload: Dict[str, Any] = {"workflowKey": workflow_key}
        if period_start or period_end:
            payload["scope"] = {"periodStart": period_start, "periodEnd": period_end}
        return _explained(api._make_request("POST", _runs_url(), json_data=payload))

    @mcp.tool(
        title="Answer Workflow Question",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def answer_workflow_question(
        ctx: Context,
        run_id: str = Field(description="publicId of a run whose blockedReason is user_input"),
        answer: str = Field(description="The user's answer, in their words"),
    ) -> Dict[str, Any]:
        """
        Give a waiting workflow the user's answer to its question
        (blockedDetail). Norman stores it on the step and continues the run
        on its servers.

        Relay only what the user actually said — never answer on their
        behalf, and ask them first if the question needs a decision. Only
        the person who started the run can answer it. Each answer uses one
        of the month's AI messages.

        Returns:
            The run, no longer blocked.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return NO_COMPANY

        result = _explained(
            api._make_request("POST", _runs_url(f"{run_id}/reply/"), json_data={"message": answer})
        )
        return result.get("run", result) if "error" not in result else result

    @mcp.tool(
        title="Complete Workflow Step",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    async def complete_workflow_step(
        ctx: Context,
        run_id: str = Field(description="Workflow run publicId"),
        step: str = Field(description="Key of the run's active manual step"),
        skipped: bool = Field(default=False, description="True skips the step instead of marking it done"),
    ) -> Dict[str, Any]:
        """
        Mark a manual step (blockedReason manual_step) done — or skipped —
        after the user says they did it or want to skip it, and let the run
        continue. Not for questions: those take answer_workflow_question.

        Returns:
            The run.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return NO_COMPANY

        run = api._make_request(
            "POST",
            _runs_url(f"{run_id}/step/"),
            json_data={"step": step, "done": True, "skipped": skipped},
        )
        if "error" in run or run.get("state") != "active":
            return run
        advanced = _explained(api._make_request("POST", _runs_url(f"{run_id}/advance/")))
        if "error" in advanced:
            return advanced
        return advanced.get("run", run)

    @mcp.tool(
        title="Continue Workflow",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    async def continue_workflow(
        ctx: Context,
        run_id: str = Field(description="Workflow run publicId"),
    ) -> Dict[str, Any]:
        """
        Try the current step again after it stopped (blockedReason
        step_failed), or after the user connected the missing source. Tell
        the user what stopped it first — the reason is in blockedDetail.

        Returns:
            The run.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return NO_COMPANY

        result = _explained(api._make_request("POST", _runs_url(f"{run_id}/advance/")))
        return result.get("run", result) if "error" not in result else result

    @mcp.tool(
        title="Stop Workflow",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def stop_workflow(
        ctx: Context,
        run_id: str = Field(description="Workflow run publicId"),
    ) -> Dict[str, Any]:
        """
        Stop an active run when the user no longer wants it. Steps not yet
        started will not run; a step in progress may finish first. Completed
        work stays, and the workflow can be run again later.

        Returns:
            The run, cancelling or cancelled.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return NO_COMPANY

        return api._make_request("POST", _runs_url(f"{run_id}/step/"), json_data={"abandon": True})

    @mcp.tool(
        title="Schedule Workflow",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    async def schedule_workflow(
        ctx: Context,
        workflow_key: str = Field(description="Workflow key from list_workflows"),
        cadence: str = Field(
            default="day_of_month",
            description=(
                "day_of_month: every month, covering the month that just ended. "
                "before_vat_deadline: lead_days before each open VAT return is due (vat-readiness)"
            ),
        ),
        day_of_month: int = Field(default=1, description="Day of the month, 1-28, for day_of_month"),
        lead_days: int = Field(default=5, description="Days before the VAT deadline, for before_vat_deadline"),
    ) -> Dict[str, Any]:
        """
        Let Norman start a workflow by itself, after the user asked for it.
        Calling it again changes the timing. Norman asks the user only when a
        step needs them.

        Good defaults: month-end-close on day 3, monthly-reconciliation on
        day 5, vat-readiness 5 days before the VAT deadline. Refused with
        code automation_paid_feature on a plan without automatic runs — say
        so instead of retrying.

        Returns:
            The schedule with nextRunOn.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return NO_COMPANY

        return _explained(
            api._make_request(
                "POST",
                _routines_url(),
                json_data={
                    "action": "schedule_workflow",
                    "workflowKey": workflow_key,
                    "cadence": cadence,
                    "dayOfMonth": day_of_month,
                    "leadDays": lead_days,
                },
            )
        )

    @mcp.tool(
        title="Unschedule Workflow",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def unschedule_workflow(
        ctx: Context,
        workflow_key: str = Field(description="Key of a workflow that runs by itself"),
    ) -> Dict[str, Any]:
        """
        Stop starting a workflow by itself when the user asks. A run already
        started is not affected, and the workflow can still be run by hand.

        Returns:
            The schedule, dismissed.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return NO_COMPANY

        return api._make_request(
            "POST",
            _routines_url(),
            json_data={"action": "unschedule_workflow", "workflowKey": workflow_key},
        )

    @mcp.tool(
        title="Get Agent Week",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_agent_week(ctx: Context) -> Dict[str, Any]:
        """
        What Norman's agents did for this company in the last seven days —
        the numbers of the weekly email: bookings by the user's rules,
        transactions categorized, payment reminders sent, workflows completed,
        how many things wait for the user, and minutes saved.

        Use it for "what have you done for me this week?". Quote the numbers;
        do not estimate.

        Returns:
            periodStart, periodEnd, done counts, doneTotal, waiting,
            minutesSaved and emailEnabled.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return NO_COMPANY

        return api._make_request("GET", _digest_url())
