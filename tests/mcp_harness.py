"""Call tools the way an MCP client does: through the production server.

Most tests call tool functions directly, which skips everything FastMCP does
around them: argument validation, the result guard and, above all, output
validation against the tool's outputSchema -- the step that turned a bare list
from the API into "Input should be a valid dictionary". These helpers drive the
real `tools/call` handler of `norman_mcp.server.mcp` instead.
"""

import asyncio
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from mcp import types
from mcp.server.lowlevel.server import request_ctx
from mcp.shared.context import RequestContext

from norman_mcp.server import mcp as server

Responder = Callable[[str, str, Dict[str, Any]], Any]


class FakeApi:
    """Stands in for NormanAPI; answers every request through `respond`."""

    def __init__(self, respond: Any = None, company_id: Optional[str] = "company-1") -> None:
        self.company_id = company_id
        self.requests: List[Tuple[str, str, Dict[str, Any]]] = []
        self._respond = respond if callable(respond) else (lambda *_: respond)

    def _make_request(self, method: str, url: str, params=None, json_data=None, files=None):  # noqa: ANN001
        kwargs = {"params": params, "json_data": json_data, "files": files}
        self.requests.append((method, url, kwargs))
        return self._respond(method, url, kwargs)

    async def arequest(self, method: str, url: str, params=None, json_data=None, files=None):  # noqa: ANN001
        return self._make_request(method, url, params=params, json_data=json_data, files=files)


def _in_request(api: Any, request: Any) -> Any:
    """Handle one MCP request with `api` as the lifespan's API client."""

    async def run() -> Any:
        token = request_ctx.set(
            RequestContext(request_id=1, meta=None, session=None, lifespan_context={"api": api}),
        )
        try:
            handler = server._mcp_server.request_handlers[type(request)]  # noqa: SLF001
            return (await handler(request)).root
        finally:
            request_ctx.reset(token)

    return asyncio.run(run())


def call_tool(name: str, arguments: Dict[str, Any], api: Any) -> types.CallToolResult:
    """Run one `tools/call` request against the production server."""
    return _in_request(
        api,
        types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=name, arguments=arguments),
        ),
    )


def read_resource(uri: str, api: Any) -> str:
    """Run one `resources/read` request and return the text it produced."""
    result = _in_request(
        api,
        types.ReadResourceRequest(
            method="resources/read",
            params=types.ReadResourceRequestParams(uri=uri),
        ),
    )
    return result.contents[0].text


def structured(result: types.CallToolResult) -> Dict[str, Any]:
    """The tool's object as the client receives it, unwrapped from FastMCP's envelope."""
    assert not result.isError, result.content[0].text
    content = result.structuredContent
    assert content is not None
    # `-> Dict[str, Any]` tools are wrapped as {"result": {...}} by FastMCP.
    return content["result"] if set(content) == {"result"} else content


def error_payload(result: types.CallToolResult) -> Dict[str, Any]:
    """The JSON payload of a failed call (isError: true)."""
    assert result.isError, result
    text = result.content[0].text
    return json.loads(text[text.index("{"):])
