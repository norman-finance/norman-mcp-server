from typing import Annotated, Any
from urllib.parse import urljoin
from uuid import UUID

from mcp.types import ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context


def register_integration_tools(mcp: Any) -> None:
    @mcp.tool(
        title="List Integrations",
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False,
        ),
    )
    async def list_integrations(ctx: Context) -> dict[str, Any]:
        """List connections for the selected company and their import status.

        Stripe bookkeeping (`stripe_bookkeeping`) reads accounting data through
        the marketplace app. Its daily imports stay off until the user enables
        them in Norman. Stripe (`stripe`) is the separate Connect connection
        used to accept customer payments. Neither is a Stripe MCP Source.
        To connect bookkeeping, direct the user to the authenticated Norman
        page /integrations/stripe/install. Do not ask for Stripe credentials.
        """
        api = ctx.request_context.lifespan_context["api"]
        return await api.arequest("GET", urljoin(config.api_base_url, "api/v1/integrations/"))

    @mcp.tool(
        title="Import Integration Records",
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True,
        ),
    )
    async def sync_integration(
        ctx: Context,
        integration_id: Annotated[UUID, Field(description="The connection's publicId from list_integrations")],
    ) -> dict[str, Any]:
        """Import new records once when the user requests a sync.

        This does not enable daily imports. A started response confirms that
        Norman queued the import, not that the import finished. Read the
        connection status and lastSyncedAt afterwards. Report lastSyncSkipped
        once when finalized or locked records were skipped.
        """
        api = ctx.request_context.lifespan_context["api"]
        return await api.arequest(
            "POST",
            urljoin(config.api_base_url, f"api/v1/integrations/{integration_id}/sync/"),
            json_data={},
        )

    @mcp.tool(
        title="Disconnect Integration",
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True,
        ),
    )
    async def disconnect_integration(
        ctx: Context,
        integration_id: Annotated[UUID, Field(description="The connection's publicId from list_integrations")],
    ) -> dict[str, Any]:
        """Disconnect only the connection the user explicitly asked to remove.

        Read list_integrations first. Distinguish Stripe bookkeeping imports
        from Stripe customer payments. Imported accounting records remain.
        Disconnecting the bookkeeping app deletes its saved credentials in
        Norman. The user can also uninstall it in Stripe's Installed Apps.
        """
        api = ctx.request_context.lifespan_context["api"]
        return await api.arequest(
            "POST",
            urljoin(config.api_base_url, f"api/v1/integrations/{integration_id}/revoke/"),
            json_data={},
        )
