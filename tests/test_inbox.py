import asyncio
from types import SimpleNamespace

from mcp.server.mcpserver import MCPServer

from norman_mcp.apps.inbox import INBOX_URI, load_inbox, register_inbox

COMPANY = "11111111-1111-4111-8111-111111111111"
EXECUTION = "22222222-2222-4222-8222-222222222222"
TRANSACTION = "33333333-3333-4333-8333-333333333333"


class Api:
    company_id = COMPANY

    def __init__(self):
        self.calls = []
        self.failed = False

    async def arequest(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("workflow-runs/"):
            return {
                "runs": [
                    {"publicId": "moving", "state": "active", "blockedReason": None},
                    {"publicId": "question", "state": "active", "blockedReason": "user_input"},
                    {"publicId": "cancelled", "state": "cancelled", "blockedReason": "user_input"},
                ]
            }
        if url.endswith("approvals/"):
            return {"items": [{"kind": "workflow_step"}, {"kind": "autofiling", "title": "VAT"}]}
        if url.endswith("rule-executions/"):
            if self.failed:
                return {"error": "forbidden"}
            return {"count": 51, "results": [{"publicId": EXECUTION}], "next": "next-page"}
        if url.endswith(f"rule-executions/{EXECUTION}/"):
            return {
                "publicId": EXECUTION,
                "status": "awaiting_review",
                "transaction": {"publicId": TRANSACTION},
                "actionsPlanned": [{"type": "set_vat_rate", "params": {"vat_rate": 19}}],
            }
        if url.endswith(f"transactions/{TRANSACTION}/"):
            return {"vatRate": "7", "description": "Receipt", "secretField": "private"}
        raise AssertionError(url)


def test_inbox_counts_all_approvals_and_only_actual_blocked_workflows():
    api = Api()
    data = asyncio.run(load_inbox(api, 2))
    assert data["summary"] == {"questions": 1, "approvals": 51, "taxReviewsShown": 1}
    assert [r["publicId"] for r in data["questions"]] == ["question"]
    assert data["pagination"] == {"page": 2, "hasNext": True}
    assert all(call[0] == "GET" for call in api.calls)
    assert api.calls[1][2]["params"]["page"] == 2


def test_failed_section_is_not_an_empty_success():
    api = Api()
    api.failed = True
    data = asyncio.run(load_inbox(api))
    assert data["summary"]["approvals"] is None
    assert data["unavailable"] == ["approvals"]
    assert data["summary"]["questions"] == 1


def test_no_company_does_not_read_another_company():
    api = Api()
    api.company_id = None
    assert "error" in asyncio.run(load_inbox(api))
    assert api.calls == []


def test_entrypoints_and_approval_review_are_read_only():
    mcp = MCPServer("inbox")
    register_inbox(mcp)
    tools = mcp._tool_manager._tools
    assert tools["open_norman_inbox"].meta["openai/ui"]["entrypoints"] == [
        {"type": "global"},
        {"type": "thread"},
    ]
    assert tools["open_norman_inbox"].meta["ui"]["resourceUri"] == INBOX_URI
    assert all(t.annotations.read_only_hint for t in tools.values())
    api = Api()
    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))
    result = asyncio.run(tools["get_norman_approval_data"].fn(ctx, EXECUTION))
    assert result["before"]["vatRate"] == "7"
    assert "secretField" not in result["before"]
    assert result["execution"]["actionsPlanned"][0]["params"]["vat_rate"] == 19
    assert result["canApprove"] is True
    assert all(call[0] == "GET" for call in api.calls)
    api.calls.clear()
    assert "error" in asyncio.run(tools["get_norman_approval_data"].fn(ctx, "../other-company"))
    assert api.calls == []
