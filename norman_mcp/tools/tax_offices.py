from typing import Any
from urllib.parse import urljoin

from mcp.types import ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context
from norman_mcp.tools.results import as_object

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False)


def _offices_url(path: str = "") -> str:
    return urljoin(config.api_base_url, f"api/v1/tax-registration/tax-offices/{path}")


def register_tax_office_tools(mcp):
    """Register the Finanzamt finder, backed by the BZSt directory of German tax offices."""

    @mcp.tool(annotations=READ_ONLY)
    async def get_tax_offices(
        ctx: Context,
        search_term: str | None = Field(
            default=None,
            description="Name, town or postcode of the tax office; omit it for the full list",
        ),
    ) -> dict[str, Any]:
        """Search German tax offices (Finanzämter) by name, town or postcode.

        Returns `tax_offices` with the 4-digit BuFa number (`value`) and the office name
        (`label`). For an address, prefer suggest_tax_office.
        """
        api = ctx.request_context.lifespan_context.get("api")
        offices = api._make_request("GET", _offices_url())
        if not isinstance(offices, list):
            return as_object(offices)
        if search_term and search_term.strip():
            found = api._make_request("GET", _offices_url(), params={"q": search_term.strip()})
            if not isinstance(found, dict) or "matches" not in found:
                return as_object(found)
            matches = set(found["matches"])
            offices = [office for office in offices if office["value"] in matches]
        return {"tax_offices": offices}

    @mcp.tool(annotations=READ_ONLY)
    async def suggest_tax_office(
        ctx: Context,
        postcode: str = Field(description="5-digit postcode"),
        city: str | None = Field(default=None),
        street: str | None = Field(default=None),
        house_number: str | None = Field(default=None),
    ) -> dict[str, Any]:
        """Find the Finanzamt responsible for an address.

        Use the home address for a self-employed person and the management address
        (Geschäftsleitung) for a GmbH/UG. `suggested` is set only when exactly one office
        fits; otherwise let the user choose from `candidates`. Each office has its 4-digit
        BuFa number (`value`) and name (`label`).
        """
        api = ctx.request_context.lifespan_context.get("api")
        params = {"postcode": postcode, "city": city, "street": street, "house_number": house_number}
        result = api._make_request(
            "GET",
            _offices_url("suggest/"),
            params={key: value for key, value in params.items() if value},
        )
        if not isinstance(result, dict) or "candidates" not in result:
            return as_object(result)
        offices = api._make_request("GET", _offices_url())
        labels = {office["value"]: office["label"] for office in offices} if isinstance(offices, list) else {}

        def office(code: str) -> dict[str, str]:
            return {"value": code, "label": labels.get(code, code)}

        return {
            "suggested": office(result["suggested"]) if result.get("suggested") else None,
            "candidates": [office(code) for code in result["candidates"]],
        }
