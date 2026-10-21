"""Distribution metadata shared with third-party MCP clients."""

import json
import re
from pathlib import Path

from norman_mcp import __version__


ROOT = Path(__file__).parents[1]
PUBLIC_MCP_URL = "https://mcp.norman.finance/mcp"


def test_python_registry_and_lockfile_versions_agree():
    project = (ROOT / "pyproject.toml").read_text()
    package_version = re.search(r'^version = "([^"]+)"$', project, re.MULTILINE).group(1)
    manifest = json.loads((ROOT / "server.json").read_text())
    locked = re.search(
        r'name = "norman-mcp-server"\nversion = "([^"]+)"',
        (ROOT / "uv.lock").read_text(),
    ).group(1)

    assert __version__ == package_version == manifest["version"] == locked
    packages = [p for p in manifest["packages"] if p["identifier"] == "norman-mcp-server"]
    assert packages
    assert all(p["version"] == package_version for p in packages)


def test_gemini_extension_uses_remote_streamable_http_server():
    manifest = json.loads((ROOT / "gemini-extension.json").read_text())

    assert manifest["name"] == "norman-finance"
    assert manifest["mcpServers"]["norman-finance"] == {
        "httpUrl": PUBLIC_MCP_URL,
    }
    assert (ROOT / manifest["contextFileName"]).is_file()


def test_registry_copy_fits_its_schema_and_keeps_european_and_polish_scope():
    manifest = json.loads((ROOT / "server.json").read_text())
    # The registry's 2025-12-11 schema caps this field at 100 characters.
    assert 1 <= len(manifest["description"]) <= 100
    assert all(term in manifest["description"] for term in ("European", "Polish", "KPiR", "JPK"))


def test_client_manifests_share_the_public_mcp_url():
    generic_manifest = json.loads((ROOT / ".mcp.json").read_text())
    registry_manifest = json.loads((ROOT / "server.json").read_text())

    assert generic_manifest["mcpServers"]["norman-finance"]["url"] == PUBLIC_MCP_URL
    assert any(
        remote.get("type") == "streamable-http" and remote.get("url") == PUBLIC_MCP_URL
        for remote in registry_manifest["remotes"]
    )
