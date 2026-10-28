"""Exercise calculator boundaries through the SDK, without company or live financial data."""

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from norman_mcp.server import mcp
from norman_mcp.tools import calculators
from tests.mcp_harness import FakeApi, call_tool, structured

CATALOG = json.loads((Path(__file__).parent / "fixtures/calculators.json").read_text())
INPUTS = {"country": "PL", "year": 2026, "amount": 361.13, "from": "gross", "percent": 23}
OUTPUT = {
    "calculator": "pl_vat",
    "country": "PL",
    "year": 2026,
    "currency": "PLN",
    "amountUnit": "major",
    "kind": "estimate",
    "source": "https://norman.finance/pl/kalkulatory/vat",
    "assumptions": ["Arithmetic at the user-confirmed rate."],
    "inputs": INPUTS,
    "result": {"net": 293.6, "vat": 67.53, "gross": 361.13},
}


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state = {
        "requests": [],
        "catalog": copy.deepcopy(CATALOG),
        "output": copy.deepcopy(OUTPUT),
        "status": 200,
    }
    client_type = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        assert str(request.url) == calculators.CALCULATOR_URL
        assert "authorization" not in request.headers
        assert "company-id" not in request.headers
        assert "x-company-id" not in request.headers
        if request.method == "GET":
            return httpx.Response(200, json=state["catalog"])
        return httpx.Response(state["status"], json=state["output"])

    def client(**kwargs: Any) -> httpx.AsyncClient:
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return client_type(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(calculators.httpx, "AsyncClient", client)
    return state


def test_catalog_filter_and_live_schema(invoke: Any, service: dict[str, Any]) -> None:
    result = invoke("list_public_calculators", {"country": "PL"})
    assert [entry["name"] for entry in result["calculators"]] == ["pl_vat"]
    assert "inputSchema" not in result["calculators"][0]
    result = invoke("get_public_calculator", {"calculator": "de_vat"})
    assert (
        result["country"] == "DE"
        and result["inputSchema"]["properties"]["country"]["const"] == "DE"
    )
    assert all(request.method == "GET" for request in service["requests"])


def test_decimal_cents_and_exact_result_are_preserved(invoke: Any, service: dict[str, Any]) -> None:
    result = invoke("calculate_public_estimate", {"calculator": "pl_vat", "inputs": INPUTS})
    assert result == OUTPUT
    requests = service["requests"]
    assert [r.method for r in requests] == ["GET", "POST"]
    assert json.loads(requests[-1].content) == {"calculator": "pl_vat", "inputs": INPUTS}


@pytest.mark.parametrize(
    "changes",
    [
        {"year": 2027},
        {"country": "DE"},
        {"amount": "361.13"},
        {"amount": True},
        {"amount": 1.001},
        {"amount": -1},
        {"amount": float("nan")},
        {"amount": float("inf")},
        {"percent": 19},
        {"name": "SHOULD_NOT_LEAVE_TOOL"},
        {"conversation": "x" * 17000},
    ],
)
def test_invalid_inputs_never_reach_post(
    invoke: Any, service: dict[str, Any], changes: dict[str, Any]
) -> None:
    error = invoke(
        "calculate_public_estimate",
        {"calculator": "pl_vat", "inputs": INPUTS | changes},
        error=True,
    )
    assert "SHOULD_NOT_LEAVE_TOOL" not in error
    assert [r.method for r in service["requests"]] == ["GET"]


def test_missing_input_and_unavailable_calculator(invoke: Any, service: dict[str, Any]) -> None:
    invoke(
        "calculate_public_estimate",
        {"calculator": "pl_vat", "inputs": {"country": "PL"}},
        error=True,
    )
    service["catalog"]["calculators"] = []
    error = invoke(
        "calculate_public_estimate", {"calculator": "pl_vat", "inputs": INPUTS}, error=True
    )
    assert "not available" in error
    assert all(r.method == "GET" for r in service["requests"])


@pytest.mark.parametrize("name", ["unknown", "../companies", "https://elsewhere.test"])
def test_sdk_rejects_unlisted_calculator_before_network(
    invoke: Any, service: dict[str, Any], name: str
) -> None:
    invoke("get_public_calculator", {"calculator": name}, error=True)
    assert service["requests"] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"year": 2027},
        {"country": "DE"},
        {"currency": "EUR"},
        {"kind": "filed"},
        {"source": "https://elsewhere.test"},
        {"calculator": "de_vat"},
        {"amountUnit": "cents"},
        {"assumptions": []},
        {"result": None},
    ],
)
def test_mismatched_scope_never_becomes_success(
    invoke: Any, service: dict[str, Any], changes: dict[str, Any]
) -> None:
    service["output"].update(changes)
    error = invoke(
        "calculate_public_estimate", {"calculator": "pl_vat", "inputs": INPUTS}, error=True
    )
    assert "does not match" in error


@pytest.mark.parametrize("status", [302, 422, 500])
def test_server_error_never_becomes_success(
    invoke: Any, service: dict[str, Any], status: int
) -> None:
    service.update(
        status=status, output={"error": "Calculator unavailable or conditional inputs missing"}
    )
    error = invoke(
        "calculate_public_estimate", {"calculator": "pl_vat", "inputs": INPUTS}, error=True
    )
    assert str(status) in error
    assert len(service["requests"]) == 2


def test_transport_failure_is_explicit(invoke: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(**kwargs: Any) -> None:
        raise httpx.ConnectError("synthetic outage")

    monkeypatch.setattr(calculators.httpx, "AsyncClient", unavailable)
    error = invoke("list_public_calculators", {}, error=True)
    assert "unavailable" in error and "No estimate was calculated" in error


def test_malformed_catalog_is_not_used(invoke: Any, service: dict[str, Any]) -> None:
    service["catalog"]["calculators"][0]["country"] = "DE"
    invoke("list_public_calculators", {}, error=True)
    assert len(service["requests"]) == 1


@pytest.fixture
def invoke():
    api = FakeApi(company_id=None)

    def call(name, args, *, error=False):
        result = call_tool(name, args, api)
        assert api.requests == []
        if error:
            assert result.is_error
            return result.content[0].text
        return structured(result)

    return call


def test_read_annotations_and_initialize_instructions():
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    for name in ("list_public_calculators", "get_public_calculator", "calculate_public_estimate"):
        assert tools[name].annotations.read_only_hint
        assert tools[name].annotations.idempotent_hint
        assert not tools[name].annotations.destructive_hint
    assert "calculate_public_estimate" in mcp.instructions
    assert "generate_polish_document" in mcp.instructions


def test_workflow_is_an_actual_mcp_prompt_and_plugin_copy_matches():
    prompts = asyncio.run(mcp.list_prompts())
    assert "calculators_and_forms" in {p.name for p in prompts}
    result = asyncio.run(
        mcp.get_prompt("calculators_and_forms", {"user_input": "Polish payment request"})
    )
    assert any("generate_polish_document" in m.content.text for m in result.messages)
    root = Path(__file__).resolve().parents[1]
    assert (root / "skills/calculators-and-forms/SKILL.md").read_text() == (
        root / "openai-plugin/skills/calculators-and-forms/SKILL.md"
    ).read_text()
