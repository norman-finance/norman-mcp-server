"""Concurrency isolation tests for the Norman API client.

Regression coverage for the data-isolation bug where a shared ``NormanAPI``
singleton + module-global ``_api_token`` would let one user's Norman token leak
into another user's in-flight request. The fix resolves the token per-request
from a ContextVar / the MCP auth context instead of shared instance state.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from norman_mcp.api.client import NormanAPI
from norman_mcp.context import set_api_token, set_api_company_id


@pytest.fixture(autouse=True)
def _reset_ctx():
    """Keep request-scoped ContextVars from leaking between tests."""
    set_api_token(None)
    set_api_company_id(None)
    yield
    set_api_token(None)
    set_api_company_id(None)


def _fake_response(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.content = b"{}"
    resp.headers = {"content-type": "application/json"}
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=payload)
    return resp


def _echo_auth_request(**kwargs):
    """Mock requests.request that echoes back the Authorization header it saw."""
    return _fake_response({"auth": kwargs["headers"]["Authorization"]})


def test_make_request_uses_contextvar_token_not_instance_state():
    """The per-request token must win over whatever is on the shared instance."""
    api = NormanAPI(authenticate_on_init=False)
    # Simulate the dangerous shared-state value a previous user might have left.
    api.access_token = "instance_token_from_another_user"

    set_api_token("request_scoped_token")
    with patch("norman_mcp.api.client.requests.request", side_effect=_echo_auth_request):
        result = api._make_request("GET", "https://api.norman.finance/api/v1/ping/")

    assert result["auth"] == "Bearer request_scoped_token"


def test_two_concurrent_tasks_do_not_leak_tokens():
    """Two concurrent tasks with different tokens must each send their own."""
    api = NormanAPI(authenticate_on_init=False)

    async def do_request(token):
        set_api_token(token)
        await asyncio.sleep(0)  # force interleaving with the sibling task
        return api._make_request("GET", "https://api.norman.finance/api/v1/ping/")

    async def main():
        with patch("norman_mcp.api.client.requests.request", side_effect=_echo_auth_request):
            return await asyncio.gather(
                do_request("token_alice"),
                do_request("token_bob"),
            )

    results = asyncio.run(main())
    assert {r["auth"] for r in results} == {"Bearer token_alice", "Bearer token_bob"}


def test_child_task_token_does_not_leak_into_parent():
    """A token set inside a child task must not bleed into the parent context."""
    api = NormanAPI(authenticate_on_init=False)
    set_api_token("parent_token")

    async def child():
        set_api_token("child_token")
        await asyncio.sleep(0)
        return api._make_request("GET", "https://api.norman.finance/api/v1/ping/")

    async def main():
        with patch("norman_mcp.api.client.requests.request", side_effect=_echo_auth_request):
            child_result = await asyncio.create_task(child())
            parent_result = api._make_request("GET", "https://api.norman.finance/api/v1/ping/")
            return child_result, parent_result

    child_result, parent_result = asyncio.run(main())
    assert child_result["auth"] == "Bearer child_token"
    assert parent_result["auth"] == "Bearer parent_token"
