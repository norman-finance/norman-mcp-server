"""Thin adapters for the API-owned Polish form catalog and document generators."""

import json
from typing import Any, Literal
from urllib.parse import urljoin

from mcp.types import ToolAnnotations
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context

FormId = Literal["payment-request", "handover-protocol", "zaw-fa", "upl-1", "vat-r", "zus-dra"]
READ = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
PREPARE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)


def _url(suffix: str = "") -> str:
    return urljoin(config.api_base_url, f"api/v1/toolkits/forms/{suffix}")


def _checked(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ToolError("Unexpected forms API response")
    if result.get("error"):
        raise ToolError(json.dumps(result, ensure_ascii=False))
    return result


def register_form_tools(mcp):
    @mcp.tool(title="Find Polish forms", annotations=READ)
    async def list_polish_forms(
        ctx: Context,
        query: str = Field(default="", max_length=100, description="Form name, code or purpose"),
        locale: Literal["pl", "en", "ru", "uk"] = "pl",
    ) -> dict[str, Any]:
        """Find Polish forms and generators: wezwanie do zapłaty, payment requests and handover protocols.

        Also: formularze, protokół przekazania, UPL-1, ZAW-FA, VAT-R, ZUS DRA. No company data is read.

        Returns current official sources, localized instructions and whether generation is supported.
        A catalog entry is not proof that the form is required for the user's circumstances.
        """
        api = ctx.request_context.lifespan_context["api"]
        return _checked(await api.arequest("GET", _url(), params={"q": query, "locale": locale}))

    @mcp.tool(title="Get Polish form fields", annotations=READ)
    async def get_polish_form(ctx: Context, form_id: FormId) -> dict[str, Any]:
        """Get a form's current version, required fields, limits, instructions and official source.

        Read this before generation. Ask only for missing fields. Do not request PESEL, passwords,
        tax portal credentials or personal government identifiers. Official tax forms in this
        catalog link to the authority's form; they cannot be generated or filed by these tools.
        """
        api = ctx.request_context.lifespan_context["api"]
        return _checked(await api.arequest("GET", _url(f"{form_id}/")))

    @mcp.tool(title="Prepare Polish document", annotations=PREPARE)
    async def generate_polish_document(
        ctx: Context,
        form_id: Literal["payment-request", "handover-protocol"],
        version: str = Field(
            description="Exact version returned by get_polish_form", max_length=40
        ),
        fields: dict[str, str] = Field(
            description="Only the field keys and plain-text values from get_polish_form"
        ),
        output_format: Literal["pdf", "docx"] = "pdf",
    ) -> dict[str, Any]:
        """Prepare a Polish document at the user's request. Never send, sign, file or pay anything.

        Get the current schema first; never invent names, amounts or dates. For a payment request,
        use only the verified outstanding principal; no interest or collection fees are calculated.
        Return previewText and a download link, explain that the user must review and sign.
        The link is accessible to anyone holding it and expires after 10 minutes; generate again
        if expired. Files are temporary and are not saved to the company's records.
        """
        api = ctx.request_context.lifespan_context["api"]
        return _checked(
            await api.arequest(
                "POST",
                _url(f"{form_id}/generate/"),
                json_data={
                    "version": version,
                    "format": output_format,
                    "fields": fields,
                },
            )
        )
