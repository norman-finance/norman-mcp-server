"""A tool call must not freeze the whole MCP server.

Tools are `async def`, but most bodies called the blocking `requests` client
straight on the event loop. Production runs one uvicorn process with a 200 s API
timeout, so one slow Norman API call stalled every connected user, and
list_attachments chained one blocking download-link call per row.
"""

import asyncio
import pathlib
import time

import norman_mcp
from norman_mcp.api.client import NormanAPI
from norman_mcp.tools._concurrency import gather_bounded

BLOCKING_CALL_SECONDS = 0.2
# One blocking call's worth of headroom: enough for a loaded CI box, far too
# little for two serialized calls.
CONCURRENT_BUDGET_SECONDS = BLOCKING_CALL_SECONDS * 1.8


def test_arequest_keeps_the_event_loop_running_during_a_blocking_call():
    api = NormanAPI(access_token="token", authenticate_on_init=False)
    api._make_request = lambda *args, **kwargs: (time.sleep(BLOCKING_CALL_SECONDS) or {"ok": True})  # noqa: SLF001

    async def scenario():  # noqa: ANN202
        ticks = 0
        stop = False

        async def tick() -> None:
            nonlocal ticks
            while not stop:
                ticks += 1
                await asyncio.sleep(0.005)

        ticker = asyncio.ensure_future(tick())
        results = await asyncio.gather(
            api.arequest("GET", "https://api.norman.finance/api/v1/a/"),
            api.arequest("GET", "https://api.norman.finance/api/v1/b/"),
        )
        stop = True
        await ticker
        return results, ticks

    started = time.monotonic()
    results, ticks = asyncio.run(scenario())
    elapsed = time.monotonic() - started

    assert results == [{"ok": True}, {"ok": True}]
    assert elapsed < CONCURRENT_BUDGET_SECONDS, f"calls were serialized ({elapsed:.2f}s)"
    assert ticks > 1


def test_no_tool_or_resource_calls_the_blocking_client_directly():
    """The whole point of `arequest` is that nothing on the event loop bypasses it."""
    package = pathlib.Path(norman_mcp.__file__).parent
    offenders = [
        f"{path.relative_to(package.parent)}:{number}"
        for path in sorted([*package.glob("tools/*.py"), *package.glob("resources/*.py"), *package.glob("apps/*.py")])
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if "_make_request(" in line or "requests.get(" in line or "requests.post(" in line
    ]

    assert offenders == [], f"blocking client called straight from the event loop: {offenders}"


def test_gather_bounded_limits_concurrency_keeps_order_and_isolates_failures():
    in_flight = 0
    peak = 0

    async def job(index: int) -> int:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        if index == 3:
            raise RuntimeError("row failed")
        return index

    results = asyncio.run(gather_bounded((job(index) for index in range(10)), max_concurrency=4))

    assert peak == 4
    assert results[:3] == [0, 1, 2]
    assert isinstance(results[3], RuntimeError)
    assert results[4:] == [4, 5, 6, 7, 8, 9]
