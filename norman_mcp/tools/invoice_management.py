"""Company-scoped invoice editing and design discovery for both MCP servers."""

from urllib.parse import quote, urljoin

from mcp.types import ToolAnnotations

from norman_mcp import config
from norman_mcp.context import Context
from norman_mcp.tools.invoice_schemas import (
    InvoiceChanges,
    InvoiceSettings,
    RecurringChanges,
    input_payload,
)

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
EDIT = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)
SETTINGS = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def _company_api(ctx: Context):
    api = ctx.request_context.lifespan_context["api"]
    if not api.company_id:
        raise ValueError("No company available. Please authenticate first.")
    return api, urljoin(config.api_base_url, f"api/v1/companies/{quote(str(api.company_id), safe='')}/")


def register_invoice_management_tools(mcp, enrich=None):
    """``enrich`` is each server's async invoice-response hook.

    Both servers replace the private ``reportUrl`` with a presigned
    ``downloadUrl`` on create. An edit returns the same invoice body, so it has
    to go through the same hook or the caller gets a link it cannot open.
    """

    async def _result(data: dict, api) -> dict:
        return await enrich(data, api=api, company_id=api.company_id) if enrich else data

    @mcp.tool(title="List Invoice Templates", annotations=READ)
    async def list_invoice_templates(ctx: Context) -> dict:
        """List templates, appearance choices, defaults and the active company's plan access."""
        api, company_url = _company_api(ctx)
        return await api.arequest("GET", company_url + "invoices/document-templates/")

    @mcp.tool(title="Get Invoice Settings", annotations=READ)
    async def get_invoice_settings(ctx: Context) -> dict:
        """Read the active company's logo and defaults for future invoices and quotes."""
        api, company_url = _company_api(ctx)
        return await api.arequest("GET", company_url + "invoices/settings/")

    @mcp.tool(title="Update Invoice Settings", annotations=SETTINGS)
    async def update_invoice_settings(ctx: Context, changes: InvoiceSettings) -> dict:
        """Change company defaults for future invoices and quotes. Existing documents keep their design.

        Supply only changed settings. A partial documentDesign keeps the saved
        controls; changing its template starts from that template's defaults.
        The API enforces paid access.
        """
        patch = input_payload(changes, InvoiceSettings)
        if not patch:
            raise ValueError("Supply at least one invoice setting to change.")
        api, company_url = _company_api(ctx)
        return await api.arequest("PATCH", company_url + "invoices/settings/", json_data=patch)

    @mcp.tool(title="Update Invoice or Quote", annotations=EDIT)
    async def update_invoice(ctx: Context, invoice_id: str, changes: InvoiceChanges) -> dict:
        """Update invoice/quote fields, lines, dates, branding, payment or email settings.

        Only supplied fields change. False disables an option, an empty string
        clears text, and null clears nullable fields such as client or paymentDate.
        Keep existing line IDs when editing lines. Setting isToSend can send email.
        A partial documentDesign keeps the document's saved controls; changing its
        template starts from that template's defaults.
        Changing document content can regenerate its PDF. API plan and status rules apply.
        """
        patch = input_payload(changes, InvoiceChanges)
        if not patch:
            raise ValueError("Supply at least one invoice field to change.")
        api, company_url = _company_api(ctx)
        return await _result(
            await api.arequest(
                "PATCH",
                company_url + f"invoices/{quote(invoice_id, safe='')}/",
                json_data=patch,
            ),
            api,
        )

    @mcp.tool(title="Update Recurring Invoice", annotations=EDIT)
    async def update_recurring_invoice(ctx: Context, recurring_invoice_id: str, changes: RecurringChanges) -> dict:
        """Update a recurring schedule, its lines, branding and future invoice settings.

        Only supplied fields change. Use explicit null to clear end conditions or
        paymentDueDays. isOngoing=true removes end conditions. The API validates
        the schedule and may regenerate pending children; issued children remain.
        A partial documentDesign keeps the schedule's saved controls; changing its
        template starts from that template's defaults.
        """
        patch = input_payload(changes, RecurringChanges)
        if not patch:
            raise ValueError("Supply at least one recurring invoice field to change.")
        api, company_url = _company_api(ctx)
        return await _result(
            await api.arequest(
                "PATCH",
                company_url + f"recurring-invoices/{quote(recurring_invoice_id, safe='')}/",
                json_data=patch,
            ),
            api,
        )
