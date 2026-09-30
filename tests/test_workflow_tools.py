"""Workflow tools: Norman runs the steps on its servers; the tools start,
answer, schedule and read runs through the production tools/call handler."""

import pytest

from norman_mcp.server import mcp
from tests.mcp_harness import FakeApi, call_tool, structured

WAITING_RUN = {
    "publicId": "run-1",
    "workflowKey": "month-end-close",
    "state": "active",
    "blockedReason": "user_input",
    "blockedDetail": "Is Revolut your only bank?",
}


def _by_url(answers):  # noqa: ANN001, ANN202
    """Answer each request by the first URL fragment it ends with."""

    def respond(_method, url, _kwargs):  # noqa: ANN001, ANN202
        for fragment, answer in answers.items():
            if url.endswith(fragment):
                return answer
        raise AssertionError(f"unexpected request {url}")

    return FakeApi(respond)


def test_the_catalog_carries_each_schedule_and_the_active_runs():
    api = _by_url(
        {
            "workflow-manifests/": {
                "available": [
                    {"key": "month-end-close", "title": "Close the month"},
                    {"key": "vat-readiness", "title": "Get ready for the VAT return"},
                ]
            },
            "workflow-runs/": {"runs": [WAITING_RUN], "latestRuns": [WAITING_RUN]},
            "routines/": {
                "routines": [
                    {"kind": "monthly_workflow", "key": "month-end-close", "status": "confirmed", "dayOfMonth": 3},
                    {"kind": "monthly_workflow", "key": "vat-readiness", "status": "dismissed", "dayOfMonth": 1},
                    {"kind": "monthly_invoice", "key": "vat-readiness", "status": "confirmed", "dayOfMonth": 9},
                ]
            },
        }
    )

    data = structured(call_tool("list_workflows", {}, api))

    close, vat = data["workflows"]
    assert close["schedule"]["dayOfMonth"] == 3
    # A dismissed schedule, or a routine of another kind, is not a schedule.
    assert vat["schedule"] is None
    assert data["activeRuns"] == [WAITING_RUN]


def test_the_catalog_still_lists_workflows_when_schedules_do_not_load():
    api = _by_url(
        {
            "workflow-manifests/": {"available": [{"key": "month-end-close"}]},
            "workflow-runs/": {"runs": [], "latestRuns": []},
            "routines/": {"error": "Request failed", "status_code": 500},
        }
    )

    data = structured(call_tool("list_workflows", {}, api))

    assert data["workflows"] == [{"key": "month-end-close", "schedule": None}]


def test_start_sends_the_period_only_when_one_is_given():
    api = FakeApi({"publicId": "run-1", "state": "active"})

    structured(call_tool("start_workflow", {"workflow_key": "month-end-close"}, api))
    structured(
        call_tool(
            "start_workflow",
            {"workflow_key": "month-end-close", "period_start": "2026-08-01", "period_end": "2026-08-31"},
            api,
        )
    )

    (method, url, first), (_, _, second) = api.requests
    assert method == "POST"
    assert url.endswith("api/v1/assistant/workflow-runs/")
    assert first["json_data"] == {"workflowKey": "month-end-close"}
    assert second["json_data"] == {
        "workflowKey": "month-end-close",
        "scope": {"periodStart": "2026-08-01", "periodEnd": "2026-08-31"},
    }


def test_an_answer_goes_to_the_run_and_the_run_comes_back():
    api = FakeApi({"run": {**WAITING_RUN, "blockedReason": None}})

    data = structured(call_tool("answer_workflow_question", {"run_id": "run-1", "answer": "Yes, only Revolut."}, api))

    method, url, kwargs = api.requests[0]
    assert method == "POST"
    assert url.endswith("workflow-runs/run-1/reply/")
    assert kwargs["json_data"] == {"message": "Yes, only Revolut."}
    assert data["publicId"] == "run-1"
    assert data["blockedReason"] is None


def test_an_answer_without_ai_messages_left_says_so():
    api = FakeApi({"error": "Rate limit exceeded. Please try again later.", "status_code": 429})

    data = structured(call_tool("answer_workflow_question", {"run_id": "run-1", "answer": "Yes"}, api))

    assert data["code"] == "chat_limit_reached"
    assert "AI messages" in data["error"]


def test_a_schedule_carries_its_cadence():
    api = FakeApi({"key": "vat-readiness", "status": "confirmed", "nextRunOn": "2026-10-05"})

    structured(
        call_tool(
            "schedule_workflow",
            {"workflow_key": "vat-readiness", "cadence": "before_vat_deadline", "lead_days": 5},
            api,
        )
    )

    method, url, kwargs = api.requests[0]
    assert method == "POST"
    assert url.endswith("api/v1/assistant/routines/")
    assert kwargs["json_data"] == {
        "action": "schedule_workflow",
        "workflowKey": "vat-readiness",
        "cadence": "before_vat_deadline",
        "dayOfMonth": 1,
        "leadDays": 5,
    }


def test_a_schedule_on_a_plan_without_automatic_runs_is_explained():
    api = FakeApi(
        {
            "error": "Request failed: 400 Client Error",
            "status_code": 400,
            "detail": {"detail": "Automatic workflow runs are part of a paid plan.", "code": "automation_paid_feature"},
        }
    )

    data = structured(call_tool("schedule_workflow", {"workflow_key": "month-end-close", "day_of_month": 3}, api))

    assert data["code"] == "automation_paid_feature"
    assert "by hand stays free" in data["error"]


def test_a_schedule_can_be_stopped():
    api = FakeApi({"key": "month-end-close", "status": "dismissed"})

    structured(call_tool("unschedule_workflow", {"workflow_key": "month-end-close"}, api))

    assert api.requests[0][2]["json_data"] == {"action": "unschedule_workflow", "workflowKey": "month-end-close"}


def test_a_done_manual_step_lets_the_run_continue():
    def respond(_method, url, _kwargs):  # noqa: ANN001, ANN202
        if url.endswith("/step/"):
            return {"publicId": "run-1", "state": "active"}
        return {"run": {"publicId": "run-1", "state": "active", "isRunning": True}}

    api = FakeApi(respond)

    data = structured(call_tool("complete_workflow_step", {"run_id": "run-1", "step": "review", "skipped": True}, api))

    (_, step_url, step), (_, advance_url, _) = api.requests
    assert step_url.endswith("workflow-runs/run-1/step/")
    assert step["json_data"] == {"step": "review", "done": True, "skipped": True}
    assert advance_url.endswith("workflow-runs/run-1/advance/")
    assert data["isRunning"] is True


def test_the_last_manual_step_finishes_the_run_without_advancing():
    api = FakeApi({"publicId": "run-1", "state": "done"})

    data = structured(call_tool("complete_workflow_step", {"run_id": "run-1", "step": "review"}, api))

    assert len(api.requests) == 1
    assert data["state"] == "done"


def test_continue_and_stop_hit_their_run_actions():
    api = FakeApi({"run": {"publicId": "run-1", "state": "active"}})

    continued = structured(call_tool("continue_workflow", {"run_id": "run-1"}, api))
    structured(call_tool("stop_workflow", {"run_id": "run-1"}, api))

    assert continued["publicId"] == "run-1"
    (_, advance_url, _), (_, stop_url, stop) = api.requests
    assert advance_url.endswith("workflow-runs/run-1/advance/")
    assert stop_url.endswith("workflow-runs/run-1/step/")
    assert stop["json_data"] == {"abandon": True}


def test_the_week_comes_from_the_digest():
    api = FakeApi({"doneTotal": 17, "minutesSaved": 95})

    data = structured(call_tool("get_agent_week", {}, api))

    assert data == {"doneTotal": 17, "minutesSaved": 95}
    assert api.requests[0][1].endswith("api/v1/assistant/agent-digest/")


@pytest.mark.parametrize("tool", ["list_workflows", "get_agent_week"])
def test_nothing_is_read_without_a_company(tool):  # noqa: ANN001
    api = FakeApi({}, company_id=None)

    data = structured(call_tool(tool, {}, api))

    assert "No company" in data["error"]
    assert api.requests == []


def test_annotations_tell_reads_from_runs_that_can_reach_clients():
    tools = mcp._tool_manager._tools  # noqa: SLF001
    reads = ["list_workflows", "get_workflow_run", "get_agent_week"]
    reaching_out = ["start_workflow", "answer_workflow_question", "complete_workflow_step", "continue_workflow"]
    settings = ["stop_workflow", "schedule_workflow", "unschedule_workflow"]

    for name in reads:
        assert tools[name].annotations.read_only_hint is True, name
    for name in reaching_out:
        assert tools[name].annotations.read_only_hint is False, name
        assert tools[name].annotations.open_world_hint is True, name
    for name in reaching_out + settings:
        assert tools[name].annotations.destructive_hint is False, name
    for name in settings:
        assert tools[name].annotations.open_world_hint is False, name
