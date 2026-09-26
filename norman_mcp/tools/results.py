"""The shape of every tool result, whatever the Norman API returned.

``NormanFastMCP`` (norman_mcp/server.py) applies two rules to every tool it
registers:

1. A tool declared to return an object always returns one. FastMCP validates
   structured output against the return annotation, so a bare JSON list or
   string from the API -- the SKR lookup, the chart templates, the tax-number
   check -- failed with "Input should be a valid dictionary" although the call
   had succeeded. Lists come back as ``{"results": [...]}``, the key a
   paginated API response uses, and strings as ``{"message": ...}``.

2. A failed call is reported as a failed call. A result with a top-level
   ``error`` becomes an MCP tool error (``isError: true``) whose text is the
   whole payload as JSON, so nothing the API said is lost and clients no
   longer show a failure as a successful result. MCP App view payloads (with
   a ``view`` key) are exempt: they carry their error for the widget to render.
"""

import functools
import inspect
import json
import typing
from typing import Any, Callable, Dict

from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult


def as_object(value: Any) -> Dict[str, Any]:
    """Return ``value`` as a JSON object (rule 1)."""
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        return {"results": list(value)}
    if isinstance(value, str):
        return {"message": value}
    if value is None:
        return {}
    return {"result": value}


def is_failure(value: Any) -> bool:
    """Whether a tool result reports that the call failed (rule 2)."""
    return isinstance(value, dict) and bool(value.get("error")) and "view" not in value


def _declares_object(fn: Callable[..., Any]) -> bool:
    try:
        annotation = typing.get_type_hints(fn).get("return")
    except Exception:  # noqa: BLE001 - an unresolvable annotation is simply not an object
        return False
    return annotation is dict or typing.get_origin(annotation) is dict


def _finish(result: Any, returns_object: bool) -> Any:
    if isinstance(result, CallToolResult):
        return result
    if returns_object and not isinstance(result, dict):
        result = as_object(result)
    if is_failure(result):
        raise ToolError(json.dumps(result, ensure_ascii=False, default=str))
    return result


def guard_tool_result(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a tool function so its result follows both rules.

    ``functools.wraps`` keeps the signature, docstring and annotations that
    FastMCP reads to build the tool's input and output schemas.
    """
    returns_object = _declares_object(fn)

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def guarded_async(*args: Any, **kwargs: Any) -> Any:
            return _finish(await fn(*args, **kwargs), returns_object)

        return guarded_async

    @functools.wraps(fn)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        return _finish(fn(*args, **kwargs), returns_object)

    return guarded
