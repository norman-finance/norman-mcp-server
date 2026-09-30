"""Bound SDK 2 `subscriptions/listen` streams per connection.

SDK 2 serves subscriptions/listen on every server and limits it only
process-wide (1024 streams). Without a per-connection bound, one connected
account could hold every slot open and lock all other users out, while each
idle stream still costs tasks and memory on the single hosted replica.
"""

from collections import Counter
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.shared.exceptions import MCPError

MAX_STREAMS_PER_TOKEN = 4
MAX_STREAMS_TOTAL = 256


class ListenLimits:
    def __init__(
        self, per_token: int = MAX_STREAMS_PER_TOKEN, total: int = MAX_STREAMS_TOTAL
    ) -> None:
        self.per_token = per_token
        self.total = total
        self.active: Counter[str] = Counter()

    async def __call__(self, ctx: Any, call_next: Any) -> Any:
        if ctx.method != "subscriptions/listen":
            return await call_next(ctx)
        access = get_access_token()
        key = f"{access.client_id}:{access.token}" if access else "unauthenticated"
        if sum(self.active.values()) >= self.total or self.active[key] >= self.per_token:
            raise MCPError(-32602, "Too many open subscription streams for this connection.")
        self.active[key] += 1
        try:
            return await call_next(ctx)
        finally:
            self.active[key] -= 1
            if self.active[key] <= 0:
                del self.active[key]
