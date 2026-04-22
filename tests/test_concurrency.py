"""Concurrency isolation tests for the Norman API client.

Regression coverage for the data-isolation bug where a shared
``NormanAPI`` singleton + module-global ``_api_token`` would let one
user's Norman token leak into another user's in-flight request.
"""

import asyncio

import pytest
from unittest.mock import MagicMock, patch

from norman_mcp.api.client import NormanAPI
from norman_mcp.context import (
    get_api_company_id,
    get_api_token,
    reset_request_state,
    set_api_company_id,
    set_api_token,
)


@pytest.fixture(autouse=True)
def reset_context():
    """Clear per-request ContextVars between tests."""
    reset_request_state()
    yield
    reset_request_state()


def _run(coro):
    """Run `coro` on a fresh event loop (keeps tests pytest-asyncio-free)."""
    return asyncio.new_event_loop().run_until_complete(coro)


def _fake_ok_response(capture):
    """Build a side_effect that captures Authorization + companyId per call."""

    def _side_effect(method, url, **kwargs):
        headers = kwargs.get("headers") or {}
        params = kwargs.get("params") or {}
        capture.append(
            {
                "auth": headers.get("Authorization"),
                "company": params.get("companyId"),
            }
        )
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"{}"
        resp.json.return_value = {}
        resp.headers = {"content-type": "application/json"}
        resp.raise_for_status = MagicMock()
        return resp

    return _side_effect


def test_two_concurrent_tasks_do_not_leak_tokens():
    """Two concurrent tasks with different tokens must each send their own."""
    api = NormanAPI(authenticate_on_init=False)
    captured: list[dict] = []

    async def do_request(token: str, company_id: str) -> dict:
        set_api_token(token)
        set_api_company_id(company_id)
        # Yield so the sibling task also gets to set its ContextVars before
        # either one reaches the sync _make_request call.
        await asyncio.sleep(0)
        result = api._make_request(
            "GET", "https://api.norman.finance/api/v1/ping/"
        )
        await asyncio.sleep(0)
        return {
            "token_after": get_api_token(),
            "company_after": get_api_company_id(),
            "result": result,
        }

    async def main():
        with patch(
            "norman_mcp.api.client.requests.request",
            side_effect=_fake_ok_response(captured),
        ):
            return await asyncio.gather(
                do_request("token_alice", "company_alice"),
                do_request("token_bob", "company_bob"),
            )

    alice, bob = _run(main())

    # Each task still sees its own values after the concurrent run.
    assert alice["token_after"] == "token_alice"
    assert alice["company_after"] == "company_alice"
    assert bob["token_after"] == "token_bob"
    assert bob["company_after"] == "company_bob"

    # And the wire-level request from each task carried that task's pair —
    # no cross-contamination where Alice's token is sent with Bob's company.
    by_company = {entry["company"]: entry["auth"] for entry in captured}
    assert by_company == {
        "company_alice": "Bearer token_alice",
        "company_bob": "Bearer token_bob",
    }


def test_contextvars_do_not_leak_into_parent_task():
    """A child task's set() must not mutate the parent task's ContextVars."""
    set_api_token("parent_token")
    set_api_company_id("parent_company")

    async def child():
        set_api_token("child_token")
        set_api_company_id("child_company")
        return get_api_token(), get_api_company_id()

    async def main():
        child_values = await asyncio.create_task(child())
        return child_values, (get_api_token(), get_api_company_id())

    child_values, parent_values = _run(main())

    assert child_values == ("child_token", "child_company")
    assert parent_values == ("parent_token", "parent_company")


def test_make_request_uses_contextvar_token_not_instance_state():
    """A stale instance attribute must not override the per-request ContextVar."""
    api = NormanAPI(authenticate_on_init=False)
    captured: list[dict] = []

    # Seed a ContextVar as a request-scoped token would be on the wire.
    set_api_token("request_scoped_token")
    set_api_company_id("request_scoped_company")

    # Simulate a stale singleton attribute write from a prior user — on the
    # pre-refactor code this would win; post-refactor the property writes
    # back into the ContextVar rather than onto the instance, so it's safe.
    api.access_token = "legacy_override"

    # Expected behaviour: access_token is a ContextVar property, so the write
    # above clobbered the ContextVar, not a hidden instance attribute. Restore
    # the request-scoped value to prove _make_request reads live ContextVar.
    set_api_token("request_scoped_token")

    with patch(
        "norman_mcp.api.client.requests.request",
        side_effect=_fake_ok_response(captured),
    ):
        api._make_request(
            "GET", "https://api.norman.finance/api/v1/ping/"
        )

    assert captured == [
        {"auth": "Bearer request_scoped_token", "company": "request_scoped_company"}
    ]
