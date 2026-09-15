"""Review-specific tool surface; the general MCP connector keeps its capabilities.

The ChatGPT endpoint uses the existing OAuth provider and request-scoped identity.
This is a product surface, not a replacement for backend authorization.
"""

import json
from typing import Any, Literal
from urllib.parse import urljoin

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from norman_mcp import config
from norman_mcp.apps.public import register_public_apps
from norman_mcp.context import Context

CHATGPT_MCP_PATH = "/chatgpt/mcp"
CHATGPT_WIDGET_DOMAIN = "https://mcp.norman.finance"
READ_ONLY = ToolAnnotations(
    readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True
)
REGISTRATION_MODULES = frozenset(
    {
        "norman_mcp.tools.incorporation",
        "norman_mcp.tools.gewerbe_registration",
        "norman_mcp.tools.corporate_tax_registration",
    }
)
PAYMENT_CAPABLE_TOOLS = frozenset(
    {
        "pay_bill",
        "toggle_agent",
        "approve_rule_execution",
        "apply_rule_to_existing",
        "update_rule",
    }
)
_RESTRICTED_KEYS = frozenset(
    {
        "taxid",
        "personaltaxid",
        "steuerid",
        "steueridentifikationsnummer",
        "ssn",
        "socialsecuritynumber",
        "passportnumber",
        "passportid",
        "nationalid",
        "nationalidentitynumber",
        "dob",
        "dateofbirth",
        "ownerdob",
        "ownerbirthname",
        "ownerplaceofbirth",
        "ownercountryofbirth",
    }
)
_WORKSPACE_PATHS = {
    "incorporation": "",  # Authenticated dashboard includes the formation roadmap.
    "gewerbe": "gewerbe-registration",
    "corporate_tax": "corporate-tax-registration",
    "bills": "bills",  # Opens the list, never creates/prefills a payment order.
}
_STATUSES = frozenset(
    {
        "data_collection",
        "data_complete",
        "documents_generated",
        "notary_requested",
        "handed_off",
        "notarized",
        "capital_deposited",
        "registered",
        "completed",
        "submitted",
    }
)


def _key(value: str) -> str:
    return value.replace("_", "").replace("-", "").lower()


def _contains_restricted_fields(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            _key(str(k)) in _RESTRICTED_KEYS or _contains_restricted_fields(v)
            for k, v in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_restricted_fields(v) for v in value)
    return False


def _safe_result(value: Any) -> Any:
    """Remove known identity fields from structured data and its text duplicate.

    This deliberately is not a content classifier for arbitrary documents or prose.
    Registration inputs and identity-document tools are not registered at all.
    """
    if isinstance(value, CallToolResult):
        return value.model_copy(
            update={
                "content": [_safe_result(v) for v in value.content],
                "structuredContent": _safe_result(value.structuredContent),
                "meta": _safe_result(value.meta),
            }
        )
    if isinstance(value, TextContent):
        try:
            parsed = json.loads(value.text)
        except (ValueError, TypeError):
            return value
        return value.model_copy(
            update={"text": json.dumps(_safe_result(parsed), ensure_ascii=False)}
        )
    if isinstance(value, dict):
        return {
            k: _safe_result(v) for k, v in value.items() if _key(str(k)) not in _RESTRICTED_KEYS
        }
    if isinstance(value, tuple):
        return tuple(_safe_result(v) for v in value)
    if isinstance(value, list):
        return [_safe_result(v) for v in value]
    return value


class ChatGPTMCP(FastMCP):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        checked = arguments
        if name == "update_company_details":
            # This legacy argument is the BUSINESS Steuernummer, not personal IdNr.
            checked = {k: v for k, v in arguments.items() if k != "tax_id"}
        if _contains_restricted_fields(checked):
            raise ValueError(
                "Enter personal identity details only in the authenticated Norman workspace."
            )
        return _safe_result(await super().call_tool(name, arguments))


def workspace_link(workflow: str) -> str:
    origin = (
        "https://app.norman.finance/"
        if config.NORMAN_ENVIRONMENT.lower() == "production"
        else "https://dev.norman.finance/"
    )
    return urljoin(origin, _WORKSPACE_PATHS[workflow])


async def _registration_status(ctx: Context, endpoint: str, workflow: str) -> dict[str, Any]:
    api = ctx.request_context.lifespan_context["api"]
    result = await api.arequest("GET", urljoin(config.api_base_url, f"api/v1/{endpoint}/my/"))
    handoff = {
        "workspaceUrl": workspace_link(workflow),
        "nextStep": "Continue in Norman to review or enter personal details; do not provide identity details in chat.",
    }
    if isinstance(result, dict) and result.get("status_code") == 404:
        return {"exists": False, "status": "not_started", **handoff}
    if not isinstance(result, dict) or result.get("error"):
        return {
            "error": "Registration status could not be loaded; retry or open Norman.",
            **handoff,
        }
    status = result.get("status")
    return {
        "exists": True,
        "status": status if isinstance(status, str) and status in _STATUSES else "unknown",
        **handoff,
    }


def register_chatgpt_handoffs(mcp: FastMCP) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def get_incorporation(ctx: Context) -> dict[str, Any]:
        """Use this to check whether a GmbH/UG formation exists and retrieve its status.

        Returns only status and an authenticated Norman workspace link; no founder
        records or identity documents. If none exists, say so and offer the link.
        Collect founder questionnaires and personal identifiers only in Norman.
        """
        return await _registration_status(ctx, "incorporations", "incorporation")

    @mcp.tool(annotations=READ_ONLY)
    async def get_gewerbe_registration(ctx: Context) -> dict[str, Any]:
        """Use this to check trade-registration status without retrieving owner identity data.

        Continue the questionnaire in the returned authenticated Norman form, not in chat.
        """
        return await _registration_status(ctx, "gewerbe-registrations", "gewerbe")

    @mcp.tool(annotations=READ_ONLY)
    async def get_corporate_tax_registration(ctx: Context) -> dict[str, Any]:
        """Use this to check corporate tax-registration status without personal tax IDs.

        Enter representatives/shareholders and review the form only in Norman.
        Never request personal Steuer-ID, birth details or identity documents in chat.
        """
        return await _registration_status(ctx, "corporate-tax-registrations", "corporate_tax")

    @mcp.tool(annotations=READ_ONLY)
    async def get_norman_workspace(
        workflow: Literal["incorporation", "gewerbe", "corporate_tax", "bills"],
    ) -> dict[str, Any]:
        """Use this to find the authenticated Norman workspace for a registration or bills.

        Returns a static navigation link only. Does not start a questionnaire, collect
        identity data, create a payment order, contact a bank, or transfer money.
        Payment initiation is unavailable in ChatGPT; users manage bills independently in Norman.
        """
        return {"workspaceUrl": workspace_link(workflow), "actionPerformed": False}


def create_chatgpt_server(primary: FastMCP) -> ChatGPTMCP:
    server = ChatGPTMCP(
        "Norman",
        instructions=(
            "Accounting and tax workspace for an existing Norman account. "
            "Use returned data and show empty states honestly. "
            "Never request personal government IDs, founder birth details, credentials, "
            "or payment-card details. Registration questionnaires and payment initiation "
            "take place independently in the authenticated Norman workspace. "
            "Do not initiate payments or infer permission to send invoices or file taxes."
        ),
        lifespan=primary.settings.lifespan,
        auth_server_provider=primary._auth_server_provider,
        auth=primary.settings.auth,
        host=primary.settings.host,
        port=primary.settings.port,
        stateless_http=primary.settings.stateless_http,
        json_response=primary.settings.json_response,
        streamable_http_path=CHATGPT_MCP_PATH,
        transport_security=primary.settings.transport_security,
    )
    server._transport = getattr(primary, "_transport", "streamable-http")
    for tool in primary._tool_manager.list_tools():
        if (
            tool.fn.__module__ in REGISTRATION_MODULES
            or tool.fn.__module__ == "norman_mcp.apps.public"
            or tool.name in PAYMENT_CAPABLE_TOOLS
        ):
            continue
        description = tool.description
        if tool.name == "create_rule":
            description = "Create a category-only automation rule after preview_rule and user confirmation; provide exactly one category_id or company_category_id. Editing existing rules and applying their action chains are available only in Norman."
        if tool.name == "list_pending_approvals":
            description = "List the user's pending approvals without performing them; open Norman to approve automation execution or payment preparation."
        server.add_tool(
            tool.fn,
            name=tool.name,
            title=tool.title,
            description=description,
            annotations=tool.annotations,
            icons=tool.icons,
            meta=tool.meta,
        )
    register_chatgpt_handoffs(server)
    register_public_apps(server, widget_domain=CHATGPT_WIDGET_DOMAIN)
    return server
