"""Distribution metadata shared with third-party MCP clients."""

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
PUBLIC_MCP_URL = "https://mcp.norman.finance/mcp"


def test_gemini_extension_uses_remote_streamable_http_server():
    manifest = json.loads((ROOT / "gemini-extension.json").read_text())

    assert manifest["name"] == "norman-finance"
    assert manifest["mcpServers"]["norman-finance"] == {
        "httpUrl": PUBLIC_MCP_URL,
    }
    assert (ROOT / manifest["contextFileName"]).is_file()


def test_client_manifests_share_the_public_mcp_url():
    generic_manifest = json.loads((ROOT / ".mcp.json").read_text())
    registry_manifest = json.loads((ROOT / "server.json").read_text())

    assert generic_manifest["mcpServers"]["norman-finance"]["url"] == PUBLIC_MCP_URL
    assert any(
        remote.get("type") == "streamable-http" and remote.get("url") == PUBLIC_MCP_URL
        for remote in registry_manifest["remotes"]
    )
