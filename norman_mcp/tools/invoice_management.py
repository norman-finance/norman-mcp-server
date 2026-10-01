"""Company-scoped invoice editing, corrections and design discovery for both MCP servers."""

from typing import Literal

from urllib.parse import quote, urljoin

from mcp.types import ToolAnnotations

from norman_mcp import config
from mcp.server.mcpserver.exceptions import ToolError
from norman_mcp.context import Context
from norman_mcp.tools.invoice_schemas import (
    EmailSettings,
    EmailTemplate,
    InvoiceChanges,
    InvoiceItem,
    InvoiceSettings,
    RecurringChanges,
    input_payload,
    item_payloads,
)

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
EDIT = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)
SETTINGS = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
REPLACE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
EMAIL_LANGUAGE = Literal["de", "en", "pl", "it", "es"]


def _company_api(ctx: Context):
    api = ctx.request_context.lifespan_context["api"]
    if not api.company_id:
        raise ToolError("No company available. Please authenticate first.")
    return api, urljoin(config.api_base_url, f"api/v1/companies/{quote(str(api.company_id), safe='')}/")


def _derivation_payload(
    *,
    status: str | None = None,
    items: list[InvoiceItem] | None = None,
    issued: str | None = None,
    message: str | None = None,
    delivery_date: str | None = None,
) -> dict:
    """Only what the caller decided; the API copies everything else from the source document."""
    payload: dict = {}
    if status is not None:
        payload["status"] = status
    if items is not None:
        payload["invoicedItems"] = item_payloads(items)
    if issued is not None:
        payload["issued"] = issued
    if message is not None:
        payload["message"] = message
    if delivery_date is not None:
        payload["deliveryDate"] = delivery_date
    return payload


def _register_email_tools(mcp):  # noqa: ANN001, ANN202
    """The emails to clients: what went out, the reminder rule and the company's wording."""

    @mcp.tool(title="List Invoice Emails", annotations=READ)
    async def list_invoice_emails(ctx: Context, invoice_id: str) -> dict:
        """List every email to the client about an invoice or quote, newest first.

        Each email has its kind (document or reminder), level, recipients (to, cc),
        status (scheduled, queued, sent, delivered, delayed, bounced, complained,
        failed, cancelled).
        nextReminder is what the company's reminder rule sends next, or null. The invoice's
        remindersActive says whether Norman reminds by itself at all right now.
        viewUrl is the page the client opens. Check this before sending a reminder
        by hand, so the client does not get two.
        """
        api, company_url = _company_api(ctx)
        return await api.arequest("GET", company_url + f"invoices/{quote(invoice_id, safe='')}/emails/")

    @mcp.tool(title="Skip Planned Invoice Reminder", annotations=REPLACE)
    async def skip_invoice_reminder(ctx: Context, invoice_id: str, email_id: str) -> dict:
        """Stop a planned reminder: an email with status "scheduled" from list_invoice_emails.

        The reminder is not sent and automatic reminders pause for this invoice.
        Resume them with update_invoice and remindersPaused false. A reminder that
        already went out cannot be stopped.
        """
        api, company_url = _company_api(ctx)
        return await api.arequest(
            "POST",
            company_url + f"invoices/{quote(invoice_id, safe='')}/emails/{quote(email_id, safe='')}/skip/",
        )

    @mcp.tool(title="Get Invoice Email Settings", annotations=READ)
    async def get_invoice_email_settings(ctx: Context) -> dict:
        """Read the company's reminder rule (steps, days, fees) and whether it gets a copy of client emails."""
        api, company_url = _company_api(ctx)
        return await api.arequest("GET", company_url + "invoices/email-settings/")

    @mcp.tool(title="Update Invoice Email Settings", annotations=SETTINGS)
    async def update_invoice_email_settings(ctx: Context, changes: EmailSettings) -> dict:
        """Change the company's reminder rule or its own copy of client emails.

        The rule only reminds for invoices with autoReminders true; set that per
        invoice with create_invoice or update_invoice, also after it was issued.
        Reminders go out on working days and stop once the invoice is paid or
        cancelled. Supply reminderSteps as all four levels; read them first and
        change only what the user asked for. Automatic reminders need a paid plan.
        A step's fee is shown in the reminder and paid by bank transfer; an email
        with a fee has no online payment button.
        """
        patch = input_payload(changes, EmailSettings)
        if not patch:
            raise ValueError("Supply at least one email setting to change.")
        api, company_url = _company_api(ctx)
        return await api.arequest("PATCH", company_url + "invoices/email-settings/", json_data=patch)

    @mcp.tool(title="List Invoice Email Templates", annotations=READ)
    async def list_invoice_email_templates(ctx: Context, language: EMAIL_LANGUAGE = "de") -> dict:
        """List the email wording for each document type and reminder step in one language.

        source is "company" for the company's saved wording and "norman" for the
        default text. An email uses the template in the document's language.
        """
        api, company_url = _company_api(ctx)
        templates = await api.arequest(
            "GET", company_url + "invoices/email-templates/", params={"language": language},
        )
        return {"templates": templates} if isinstance(templates, list) else templates

    @mcp.tool(title="Save Invoice Email Template", annotations=SETTINGS)
    async def save_invoice_email_template(ctx: Context, template: EmailTemplate) -> dict:
        """Save the company's wording for one kind of email in one language.

        Later emails of that kind start from it, reminders included. Keep the
        {variables}; the API fills them per document. Emails already sent stay as they are.
        """
        api, company_url = _company_api(ctx)
        return await api.arequest(
            "PUT", company_url + "invoices/email-templates/", json_data=input_payload(template, EmailTemplate),
        )

    @mcp.tool(title="Reset Invoice Email Template", annotations=REPLACE)
    async def reset_invoice_email_template(ctx: Context, key: str, language: EMAIL_LANGUAGE) -> dict:
        """Delete the company's wording for one email and go back to Norman's default text."""
        api, company_url = _company_api(ctx)
        return await api.arequest(
            "DELETE", company_url + "invoices/email-templates/", params={"key": key, "language": language},
        )


def register_invoice_management_tools(mcp, enrich=None):
    """``enrich`` is each server's async invoice-response hook.

    Both servers replace the private ``reportUrl`` with a presigned
    ``downloadUrl`` on create. An edit returns the same invoice body, so it has
    to go through the same hook or the caller gets a link it cannot open.
    """

    async def _result(data: dict, api) -> dict:
        return await enrich(data, api=api, company_id=api.company_id) if enrich else data

    _register_email_tools(mcp)

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
            raise ToolError("Supply at least one invoice setting to change.")
        api, company_url = _company_api(ctx)
        return await api.arequest("PATCH", company_url + "invoices/settings/", json_data=patch)

    @mcp.tool(title="Update Invoice or Quote", annotations=EDIT)
    async def update_invoice(ctx: Context, invoice_id: str, changes: InvoiceChanges) -> dict:
        """Update invoice/quote fields, lines, dates, branding, payment or email settings.

        Only supplied fields change. False disables an option, an empty string
        clears text, and null clears nullable fields such as client or paymentDate.
        Keep existing line IDs when editing lines. Setting isToSend can send email,
        but a draft is never emailed. Status "saved" issues a draft; it takes the next
        free number if its own is taken. An issued document never returns to draft or
        changes type. A draft cannot be marked paid. An issued, sent or overdue invoice
        can be edited; a paid or cancelled invoice and an issued correction cannot, so
        correct a paid invoice with cancel_invoice or create_credit_note.
        A partial documentDesign keeps the document's saved controls; changing its
        template starts from that template's defaults.
        Changing document content can regenerate its PDF. API plan and status rules apply.
        """
        patch = input_payload(changes, InvoiceChanges)
        if not patch:
            raise ToolError("Supply at least one invoice field to change.")
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
        """Update a recurring invoice: its template, its rule or its mode.

        Only supplied fields change. Use explicit null to remove endsOn or endsAfter;
        with neither, the series runs until it is ended. Changes apply to the invoices
        still to come; invoices already made stay as they are. An ended series cannot
        change. A partial documentDesign keeps the series' saved controls; changing its
        template starts from that template's defaults.
        """
        patch = input_payload(changes, RecurringChanges)
        if not patch:
            raise ToolError("Supply at least one recurring invoice field to change.")
        api, company_url = _company_api(ctx)
        return await _result(
            await api.arequest(
                "PATCH",
                company_url + f"recurring-invoices/{quote(recurring_invoice_id, safe='')}/",
                json_data=patch,
            ),
            api,
        )

    async def _derive(ctx: Context, document_id: str, action: str, payload: dict) -> dict:
        api, company_url = _company_api(ctx)
        return await _result(
            await api.arequest(
                "POST",
                company_url + f"invoices/{quote(document_id, safe='')}/{action}/",
                json_data=payload,
            ),
            api,
        )

    @mcp.tool(title="Duplicate Invoice or Quote", annotations=EDIT)
    async def duplicate_invoice(ctx: Context, document_id: str) -> dict:
        """Copy an invoice or a quote into a new draft of the same kind.

        The copy keeps client, lines, terms and appearance, is dated today with
        the payment term carried over, takes the next number of its sequence and
        does not refer to the original. Finish it with update_invoice: adjust the
        service or delivery dates and set status "saved" to issue it.
        """
        return await _derive(ctx, document_id, "duplicate", {})

    @mcp.tool(title="Cancel Invoice", annotations=EDIT)
    async def cancel_invoice(
        ctx: Context,
        invoice_id: str,
        issued: str | None = None,
        message: str | None = None,
    ) -> dict:
        """Reverse an issued invoice with a cancellation invoice (Stornorechnung).

        Creates the cancellation with the invoice's lines, the next invoice number
        and a reference to the invoice, then marks the invoice "cancelled": it is
        no longer edited, reminded about or matched to payments. Only an issued
        invoice (saved, sent, overdue, paid or uncollectible) can be cancelled, and only once.
        To correct part of an invoice use create_credit_note instead. Edit a
        draft directly. issued (YYYY-MM-DD) defaults to today.
        """
        return await _derive(ctx, invoice_id, "cancel", _derivation_payload(issued=issued, message=message))

    @mcp.tool(title="Create Credit Note", annotations=EDIT)
    async def create_credit_note(
        ctx: Context,
        invoice_id: str,
        items: list[InvoiceItem] | None = None,
        status: Literal["draft", "saved"] = "saved",
        issued: str | None = None,
        message: str | None = None,
    ) -> dict:
        """Credit part or all of an issued invoice with a credit note (Rechnungskorrektur).

        Without items every line of the invoice is credited. Pass items (with the
        quantities and rates to credit, in minor currency units) to correct part
        of it. The invoice itself stays in force. The credit note refers to the
        invoice on the PDF and in the e-invoice XML. status "draft" leaves it
        editable; "saved" issues it at once. issued (YYYY-MM-DD) defaults to today.
        """
        return await _derive(
            ctx,
            invoice_id,
            "credit-note",
            _derivation_payload(status=status, items=items, issued=issued, message=message),
        )

    @mcp.tool(title="Create Delivery Note", annotations=EDIT)
    async def create_delivery_note(
        ctx: Context,
        document_id: str,
        items: list[InvoiceItem] | None = None,
        status: Literal["draft", "saved"] = "saved",
        delivery_date: str | None = None,
    ) -> dict:
        """Make a delivery note (Lieferschein) from an issued invoice or an approved quote.

        The delivery note lists the document's lines with quantities and units
        and prints no prices. It takes the next number of its own sequence, refers
        to the source document and is filed in the company's Files space. Pass
        items to note a partial delivery. delivery_date (YYYY-MM-DD) defaults to the source's
        delivery date, or today when it has none. Several delivery notes per document are fine.
        """
        return await _derive(
            ctx,
            document_id,
            "delivery-note",
            _derivation_payload(status=status, items=items, delivery_date=delivery_date),
        )
