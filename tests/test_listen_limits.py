"""subscriptions/listen is bounded per connection, not only process-wide."""

import anyio
import pytest
from mcp.shared.exceptions import MCPError

import norman_mcp.security.listen_limits as limits_module
from norman_mcp.security.listen_limits import ListenLimits


class Ctx:
    def __init__(self, method="subscriptions/listen"):
        self.method = method


class Access:
    def __init__(self, token, client_id="client"):
        self.token = token
        self.client_id = client_id


def use_token(monkeypatch, token):
    monkeypatch.setattr(limits_module, "get_access_token", lambda: Access(token))


def test_one_connection_cannot_take_every_stream(monkeypatch):
    limits = ListenLimits(per_token=2, total=10)
    release = anyio.Event()

    async def hold(ctx):
        await release.wait()
        return "closed"

    async def scenario():
        use_token(monkeypatch, "mallory")
        async with anyio.create_task_group() as group:
            group.start_soon(limits, Ctx(), hold)
            group.start_soon(limits, Ctx(), hold)
            await anyio.wait_all_tasks_blocked()
            with pytest.raises(MCPError):
                await limits(Ctx(), hold)

            use_token(monkeypatch, "bob")  # another connection still gets a stream
            group.start_soon(limits, Ctx(), hold)
            await anyio.wait_all_tasks_blocked()
            assert limits.active == {"client:mallory": 2, "client:bob": 1}
            release.set()
        assert not limits.active  # every exit path releases its slot

    anyio.run(scenario)


def test_total_cap_and_other_methods_pass_through(monkeypatch):
    limits = ListenLimits(per_token=5, total=1)

    async def scenario():
        use_token(monkeypatch, "alice")
        release = anyio.Event()

        async def hold(ctx):
            await release.wait()

        async def answer(ctx):
            return "tools"

        async with anyio.create_task_group() as group:
            group.start_soon(limits, Ctx(), hold)
            await anyio.wait_all_tasks_blocked()
            use_token(monkeypatch, "bob")
            with pytest.raises(MCPError):
                await limits(Ctx(), hold)
            assert await limits(Ctx("tools/list"), answer) == "tools"
            release.set()

    anyio.run(scenario)


def test_slot_is_released_when_the_stream_fails(monkeypatch):
    limits = ListenLimits(per_token=1, total=5)
    use_token(monkeypatch, "alice")

    async def broken(ctx):
        raise RuntimeError("stream dropped")

    async def scenario():
        with pytest.raises(RuntimeError):
            await limits(Ctx(), broken)
        assert not limits.active

    anyio.run(scenario)


def test_refreshed_tokens_of_one_grant_share_the_allowance(monkeypatch):
    limits = ListenLimits(per_token=2, total=10)
    grants = {"first-token": "grant-1", "refreshed-token": "grant-1", "other": "grant-2"}
    monkeypatch.setattr(
        limits_module,
        "get_oauth_provider",
        lambda: type("P", (), {"grant_for_token": staticmethod(lambda t: grants.get(t, t))})(),
    )
    release = anyio.Event()

    async def hold(ctx):
        await release.wait()

    async def scenario():
        async with anyio.create_task_group() as group:
            use_token(monkeypatch, "first-token")
            group.start_soon(limits, Ctx(), hold)
            await anyio.wait_all_tasks_blocked()
            use_token(monkeypatch, "refreshed-token")
            group.start_soon(limits, Ctx(), hold)
            await anyio.wait_all_tasks_blocked()
            with pytest.raises(MCPError):
                await limits(Ctx(), hold)
            use_token(monkeypatch, "other")
            group.start_soon(limits, Ctx(), hold)
            await anyio.wait_all_tasks_blocked()
            assert limits.active == {"client:grant-1": 2, "client:grant-2": 1}
            release.set()

    anyio.run(scenario)
