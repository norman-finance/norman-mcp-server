"""Validate the discovery contract clients see, without authenticating or calling a live API."""

import asyncio

from jsonschema import Draft202012Validator

from norman_mcp.server import mcp
from tests.test_polish_parity import CASES


def test_polish_tools_have_valid_input_output_schemas_and_explicit_hints():
    listed = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    expected = {case[0] for case in CASES} | {
        "propose_tax_setting_change", "get_ksef_status", "search_polish_tax_offices",
    }
    assert expected <= listed.keys()
    for name in expected:
        tool = listed[name]
        assert tool.description, name
        assert tool.input_schema["type"] == "object", name
        Draft202012Validator.check_schema(tool.input_schema)
        assert tool.output_schema and tool.output_schema["type"] == "object", name
        Draft202012Validator.check_schema(tool.output_schema)
        hints = tool.annotations
        assert hints is not None, name
        assert all(type(value) is bool for value in (
            hints.read_only_hint, hints.destructive_hint, hints.open_world_hint,
        )), name
