import asyncio
import threading
from types import SimpleNamespace

from mcp.server.mcpserver import MCPServer

from norman_mcp.apps.inbox import INBOX_URI, load_inbox, register_inbox

COMPANY = "11111111-1111-4111-8111-111111111111"
EXECUTION = "22222222-2222-4222-8222-222222222222"
TRANSACTION = "33333333-3333-4333-8333-333333333333"


class Api:
    def __init__(self):
        self.calls = []
        self.failed = False
        self._company = COMPANY
        self.company_threads = []

    @property
    def company_id(self):
        self.company_threads.append(threading.current_thread())
        return self._company

    @company_id.setter
    def company_id(self, value):
        self._company = value

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
        if url.endswith(f"companies/{COMPANY}/autofiling/runs/"):
            return [
                {"publicId": "ustva-09", "status": "ready_for_approval", "periodStart": "2026-09-01", "periodEnd": "2026-09-30"},
                {"publicId": "ustva-08", "status": "submitted"},
            ]
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


# --- Regression tests for the review of #148 ---------------------------------


def test_tax_reviews_come_from_autofiling_runs_not_the_capped_aggregate():
    api = Api()
    data = asyncio.run(load_inbox(api))
    assert [t["key"] for t in data["taxReviews"]] == ["autofiling:ustva-09"]
    assert data["taxReviews"][0]["detail"] == "2026-09-01 - 2026-09-30"
    assert not [c for c in api.calls if c[1].endswith("assistant/approvals/")]


def test_page_past_the_end_serves_the_last_page_instead_of_an_outage():
    class LastItemDecided(Api):
        async def arequest(self, method, url, **kwargs):
            if url.endswith("rule-executions/"):
                self.calls.append((method, url, kwargs))
                if kwargs["params"]["page"] == 2:
                    return {"error": "Resource not found", "status_code": 404}
                return {"count": 20, "results": [{"publicId": EXECUTION}], "next": None}
            return await super().arequest(method, url, **kwargs)

    data = asyncio.run(load_inbox(LastItemDecided(), 2))
    assert data["pagination"] == {"page": 1, "hasNext": False}
    assert data["summary"]["approvals"] == 20
    assert "approvals" not in data["unavailable"]


def test_expired_session_asks_to_reconnect_instead_of_showing_outages():
    class Expired(Api):
        async def arequest(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return {"error": "Your Norman session expired. Please reconnect.", "status_code": 401}

    data = asyncio.run(load_inbox(Expired()))
    assert data == {"error": "Your Norman session expired. Please reconnect.", "reconnect": True}


def test_upstream_error_text_stays_out_of_the_inbox():
    class Broken(Api):
        async def arequest(self, method, url, **kwargs):
            if url.endswith("workflow-runs/"):
                return {"error": "Request failed: 500 for url: https://api.example/secret", "status_code": 500}
            return await super().arequest(method, url, **kwargs)

    data = asyncio.run(load_inbox(Broken()))
    assert data["unavailable"] == ["workflows"]
    assert "https://" not in str(data)


def test_company_lookup_runs_off_the_event_loop():
    api = Api()
    asyncio.run(load_inbox(api))
    assert api.company_threads and threading.main_thread() not in api.company_threads


CATEGORY = "44444444-4444-4444-8444-444444444444"
VENDOR = "55555555-5555-4555-8555-555555555555"
CURRENT_VENDOR = "66666666-6666-4666-8666-666666666666"


def test_approval_review_shows_names_not_ids():
    class Named(Api):
        async def arequest(self, method, url, **kwargs):
            if url.endswith(f"rule-executions/{EXECUTION}/"):
                self.calls.append((method, url, kwargs))
                return {
                    "publicId": EXECUTION,
                    "status": "awaiting_review",
                    "transaction": {"publicId": TRANSACTION, "amount": "-59.49", "valueDate": "2026-09-12"},
                    "actionsPlanned": [
                        {"type": "set_category", "params": {"company_category": CATEGORY}},
                        {"type": "assign_vendor", "params": {"vendor": VENDOR}},
                        {"type": "set_vat_rate", "params": {"vat_rate": 19}},
                    ],
                }
            if url.endswith(f"transactions/{TRANSACTION}/"):
                return {"vendor": CURRENT_VENDOR, "vendorDetails": {"name": "Old Vendor GmbH"}, "vatRate": "7"}
            if url.endswith(f"accounting/company-categories/{CATEGORY}/"):
                return {"code": "4964", "name": "Software subscriptions"}
            if url.endswith(f"accounting/vendors/{VENDOR}/"):
                return {"name": "Adobe Systems"}
            return await super().arequest(method, url, **kwargs)

    mcp = MCPServer("inbox")
    register_inbox(mcp)
    api = Named()
    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))
    result = asyncio.run(mcp._tool_manager._tools["get_norman_approval_data"].fn(ctx, EXECUTION))
    labels = [a.get("labels") for a in result["execution"]["actionsPlanned"]]
    assert labels == [
        {"company_category": "4964 Software subscriptions"},
        {"vendor": "Adobe Systems"},
        None,
    ]
    assert result["before"]["vendorLabel"] == "Old Vendor GmbH"
    assert all(c[0] == "GET" for c in api.calls)
