"""Real Norman MCP registrations over stdio, backed only by an offline API fixture."""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["NORMAN_MCP_EVENTS_DB"] = ""
os.environ["NORMAN_MCP_EVENTS_KEY"] = ""
os.environ["NORMAN_OAUTH_CLIENT_ID"] = ""

# These imports must follow the isolated environment and source-path setup.
from norman_mcp.context import set_api_client  # isort: skip
from norman_mcp.server import mcp  # isort: skip


class OfflineAPI:
    company_id = "company-compat-fixture"

    def _make_request(self, method, url, **kwargs):
        assert method == "GET", "Compatibility tests must never mutate data"
        return {"publicId": self.company_id, "name": "Compatibility Fixture", "isSme": False}

    async def arequest(self, method, url, **kwargs):
        return self._make_request(method, url, **kwargs)


@asynccontextmanager
async def offline_lifespan(_):
    api = OfflineAPI()
    set_api_client(api)
    yield {"api": api}


mcp._lowlevel_server.lifespan = offline_lifespan
mcp.run(transport="stdio")
