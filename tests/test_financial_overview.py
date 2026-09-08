import asyncio
from contextvars import ContextVar
from types import SimpleNamespace
from unittest.mock import AsyncMock

from norman_mcp.tools.company import register_company_tools


class Registry:
    def __init__(self):
        self.tools, self.annotations = {}, {}

    def tool(self, **kwargs):
        def register(fn):
            self.tools[fn.__name__] = fn
            self.annotations[fn.__name__] = kwargs.get("annotations")
            return fn

        return register


def setup(api):
    registry = Registry()
    register_company_tools(registry)
    return registry, SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))


def test_overview_runs_five_reads_concurrently_and_keeps_source_periods_distinct():
    async def run():
        started, requests = 0, []
        ready, release = asyncio.Event(), asyncio.Event()

        async def request(method, url, params=None):
            nonlocal started
            requests.append((method, url, params))
            started += 1
            if started == 5:
                ready.set()
            await release.wait()
            if "bwa" in url:
                return {
                    "currency": "EUR",
                    "period": "July",
                    "lines": {"totalRevenue": {"amount": 100, "children": [{"private": "detail"}]}},
                }
            if "balance" in url:
                return {
                    "sumsByCurrency": [
                        {"currency": "EUR", "sumAmount": "20.00"},
                        {"currency": "USD", "sumAmount": "30.00"},
                    ]
                }
            return {
                "name": "Example",
                "datePeriodStart": "2026-08-01",
                "nextDeadlineDate": "2026-09-10",
            }

        registry, ctx = setup(SimpleNamespace(company_id="company-1", arequest=request))
        task = asyncio.create_task(
            registry.tools["get_financial_overview"](ctx, "2026-07-01", "2026-07-31")
        )
        await asyncio.wait_for(ready.wait(), timeout=2)
        assert not task.done()  # Every independent read started before any completed.
        release.set()
        result = await task
        assert len(requests) == 5 and all(
            method == "GET" and "/companies/company-1/" in url for method, url, _ in requests
        )
        assert next(params for _, url, params in requests if "bwa" in url) == {
            "date_from": "2026-07-01",
            "date_to": "2026-07-31",
            "period_type": "month",
        }
        assert result["period"] == {"from": "2026-07-01", "to": "2026-07-31"}
        assert not result["partial"]
        assert len(result["sections"]["balance"]["data"]["sumsByCurrency"]) == 2
        assert result["sections"]["profit_and_loss"]["data"]["lines"]["totalRevenue"] == {
            "amount": 100
        }
        assert result["sections"]["next_vat"]["data"]["datePeriodStart"] == "2026-08-01"
        assert registry.annotations["get_financial_overview"].readOnlyHint is True

    asyncio.run(run())


def test_failed_section_is_unavailable_not_zero_and_other_sections_survive():
    async def request(method, url, params=None):
        if "bwa" in url:
            raise TimeoutError("Do not expose raw errors")
        if "company-tax" in url:
            return {"error": "Unavailable"}
        return {"name": "Example", "amount": "42.00"}

    registry, ctx = setup(SimpleNamespace(company_id="company-1", arequest=request))
    result = asyncio.run(registry.tools["get_financial_overview"](ctx))
    assert result["partial"]
    assert result["sections"]["profit_and_loss"]["status"] == "unavailable"
    assert "data" not in result["sections"]["tax_estimates"]
    assert result["sections"]["balance"]["data"]["amount"] == "42.00"
    assert "Do not expose" not in str(result)


def test_bad_period_or_missing_company_never_issues_requests():
    api = SimpleNamespace(company_id=None, arequest=AsyncMock())
    registry, ctx = setup(api)
    tool = registry.tools["get_financial_overview"]
    assert "error" in asyncio.run(tool(ctx))
    api.company_id = "company-1"
    for dates in [
        ("2026-01-01", None),
        ("wrong", "2026-01-01"),
        ("2026-07-01", "2026-06-01"),
        ("2024-01-01", "2026-01-01"),
    ]:
        assert "error" in asyncio.run(tool(ctx, *dates))
    api.arequest.assert_not_awaited()


def test_concurrent_users_keep_their_company_context_in_worker_threads():
    from norman_mcp.api.client import NormanAPI

    active = ContextVar("overview_test_company")

    class Api:
        arequest = NormanAPI.arequest

        @property
        def company_id(self):
            return active.get()

        def _make_request(self, method, url, *args):
            assert f"/companies/{active.get()}/" in url
            return {"name": active.get(), "company": active.get()}

    async def run():
        registry, ctx = setup(Api())

        async def overview(company):
            token = active.set(company)
            try:
                return await registry.tools["get_financial_overview"](ctx)
            finally:
                active.reset(token)

        a, b = await asyncio.gather(overview("a"), overview("b"))
        assert a["company_id"] == "a" and b["company_id"] == "b"
        assert a["sections"]["balance"]["data"]["company"] == "a"
        assert b["sections"]["balance"]["data"]["company"] == "b"

    asyncio.run(run())
