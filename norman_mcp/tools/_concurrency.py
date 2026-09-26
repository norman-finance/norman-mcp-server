"""Bounded fan-out for the per-row API calls tools make while enriching a list."""

import asyncio
from typing import Any, Awaitable, Iterable, List

# One page of rows at a time is plenty: it turns a page-sized chain of round
# trips into a couple of waves without opening a connection per row against our
# own API.
DEFAULT_MAX_CONCURRENCY = 8


async def gather_bounded(
    awaitables: Iterable[Awaitable[Any]],
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
) -> List[Any]:
    """Await everything with at most `max_concurrency` in flight.

    Results keep the order they were passed in. Exceptions are returned rather
    than raised: every caller treats a failed row as "no extra field on that
    row", and one bad row must not lose the whole response.
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _run(awaitable: Awaitable[Any]) -> Any:
        async with semaphore:
            return await awaitable

    tasks = [_run(awaitable) for awaitable in awaitables]
    if not tasks:
        return []
    return await asyncio.gather(*tasks, return_exceptions=True)
