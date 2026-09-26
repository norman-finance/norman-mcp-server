"""Keep structured tool results objects, whatever the Norman API returned.

FastMCP validates the structured output of a tool against its return
annotation. Tools declared ``-> Dict[str, Any]`` therefore fail with "Input
should be a valid dictionary" when the API answers with a bare JSON list (the
chart templates, the SKR lookup and AI suggestion) or a bare string (the tax
number check), although the call itself succeeded.
"""

from typing import Any, Dict, Optional


def as_object(value: Any) -> Dict[str, Any]:
    """Return ``value`` as a JSON object.

    Lists come back as ``{"results": [...]}``, the key a paginated API response
    uses; strings as ``{"message": ...}``. Objects, including error payloads,
    pass through unchanged.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        return {"results": list(value)}
    if isinstance(value, str):
        return {"message": value}
    if value is None:
        return {}
    return {"result": value}


def first_text(detail: Any) -> Optional[str]:
    """The first human-readable string in a DRF error body (str, list or dict)."""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, (list, tuple)):
        for item in detail:
            text = first_text(item)
            if text:
                return text
    if isinstance(detail, dict):
        for value in detail.values():
            text = first_text(value)
            if text:
                return text
    return None
