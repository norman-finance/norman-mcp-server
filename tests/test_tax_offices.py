"""The Finanzamt finder names every office it returns and passes API errors on."""

import asyncio
from types import SimpleNamespace

import pytest
from mcp.server.mcpserver import MCPServer

from norman_mcp.tools.tax_offices import register_tax_office_tools

OFFICES = [
    {"value": "1113", "label": "Berlin Charlottenburg"},
    {"value": "1114", "label": "Berlin Kreuzberg"},
    {"value": "9181", "label": "München"},
]


class FakeApi:
    def __init__(self, offices=OFFICES, matches=(), suggestion=None):
        self.offices, self.matches, self.suggestion = offices, list(matches), suggestion
        self.calls = []

    def _make_request(self, method, url, params=None, json_data=None):
        self.calls.append((url.rsplit("tax-offices/", 1)[1], params))
        if url.endswith("suggest/"):
            return self.suggestion
        return {"matches": self.matches} if params else self.offices


def call(name, api, **kwargs):
    server = MCPServer()
    register_tax_office_tools(server)
    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))
    return asyncio.run(server._tool_manager._tools[name].fn(ctx, **kwargs))  # noqa: SLF001


def test_a_search_returns_the_matching_offices_with_their_names():
    result = call("get_tax_offices", FakeApi(matches=["1113", "1114"]), search_term=" Berlin ")

    assert result == {"tax_offices": OFFICES[:2]}


@pytest.mark.parametrize(
    ("suggestion", "expected"),
    [
        pytest.param(
            {"suggested": "9181", "candidates": ["9181"]},
            {"suggested": OFFICES[2], "candidates": [OFFICES[2]]},
            id="one-office",
        ),
        pytest.param(
            {"suggested": None, "candidates": ["1113", "1114"]},
            {"suggested": None, "candidates": OFFICES[:2]},
            id="several-offices",
        ),
    ],
)
def test_a_suggestion_names_the_offices(suggestion, expected):
    api = FakeApi(suggestion=suggestion)

    result = call("suggest_tax_office", api, postcode="10115", city="Berlin", street=None, house_number=None)

    assert result == expected
    assert api.calls[0] == ("suggest/", {"postcode": "10115", "city": "Berlin"})


@pytest.mark.parametrize("name", ["get_tax_offices", "suggest_tax_office"])
def test_an_api_error_reaches_the_caller(name):
    error = {"error": "Not found."}
    api = FakeApi(offices=error, suggestion=error)
    kwargs = {"search_term": None} if name == "get_tax_offices" else {
        "postcode": "10115", "city": None, "street": None, "house_number": None,
    }

    assert call(name, api, **kwargs) == error
