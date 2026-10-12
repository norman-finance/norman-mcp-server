"""A white-label connector builds its own server on this code.

A tax advisory firm's own MCP imports norman_mcp.server for the OAuth hardening
patches, gives the server its own name and instructions, and keeps a curated set
of tools. Importing must not also build the default server.
"""

import subprocess
import sys

import pytest

from norman_mcp.server import DEFAULT_SERVER_NAME, create_app, prune_tools


@pytest.fixture(autouse=True)
def isolated_oauth_state(tmp_path, monkeypatch):
    monkeypatch.setattr("norman_mcp.auth.provider._STATE_FILE", str(tmp_path / "oauth_state.json"))


def test_importing_the_server_module_builds_no_default_server():
    code = "import norman_mcp.server as module; print('mcp' in vars(module))"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    assert result.stdout.strip().splitlines()[-1] == "False"


def test_default_server_is_built_once_on_first_use():
    import norman_mcp.server as module

    assert module.mcp is module.mcp
    assert module.mcp.name == DEFAULT_SERVER_NAME


def test_a_connector_brings_its_own_name_instructions_and_tools():
    keep = {"get_company_details", "update_company_details"}

    server = create_app(
        transport="streamable-http",
        name="Suat MCP",
        instructions="Your tax advisor's workspace.",
        website_url="https://suat.norman.finance",
        tool_filter=keep.__contains__,
    )

    assert server.name == "Suat MCP"
    assert server.instructions == "Your tax advisor's workspace."
    assert set(server._tool_manager._tools) == keep


def test_without_a_filter_every_tool_stays():
    server = create_app(transport="streamable-http")

    assert server.name == DEFAULT_SERVER_NAME
    assert {"pay_bill", "get_company_details", "start_workflow"} <= set(server._tool_manager._tools)


def test_prune_tools_returns_the_removed_names():
    server = create_app(transport="streamable-http")
    before = set(server._tool_manager._tools)

    removed = prune_tools(server, lambda name: name != "pay_bill")

    assert removed == ["pay_bill"]
    assert set(server._tool_manager._tools) == before - {"pay_bill"}
