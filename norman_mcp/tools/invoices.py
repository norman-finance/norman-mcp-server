import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urljoin

from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context
from norman_mcp.tools.contracts import register_contract_tools
from norman_mcp.tools.invoice_management import register_invoice_management_tools
from norman_mcp.tools.invoice_schemas import (
    ClientData,
    CompanyData,
    DocumentDesign,
    InvoiceItem,
    MailingData,
    OverdueSettings,
    RepeatRule,
    TransactionInvoiceItem,
    apply_invoice_options,
    item_payloads,
)

logger = logging.getLogger(__name__)


def _enrich_invoice_response(data: dict, api=None, company_id: str | None = None) -> dict:
    """Replace private reportUrl with a presigned downloadUrl (1-hour TTL)."""
    if not isinstance(data, dict):
        return data

    def _enrich_single(item: dict) -> None:
        pid = item.get("publicId")
        if pid and item.get("reportUrl") and api and company_id:
            try:
                pdf_endpoint = urljoin(
                    config.api_base_url,
                    f"api/v1/companies/{company_id}/invoices/{pid}/pdf/",
                )
                resp = api._make_request("GET", pdf_endpoint)
                if resp.get("url"):
                    item["downloadUrl"] = resp["url"]
            except Exception:
                logger.debug("Could not fetch presigned PDF URL for invoice %s", pid)

    if data.get("publicId"):
        _enrich_single(data)

    if "results" in data and isinstance(data["results"], list):
        for item in data["results"]:
            if isinstance(item, dict):
                _enrich_single(item)

    return data


async def _aenrich_invoice_response(data: dict, api=None, company_id: str | None = None) -> dict:
    """Async entry point for the shared management tools; the work itself is sync here."""
    return _enrich_invoice_response(data, api=api, company_id=company_id)


def register_invoice_tools(mcp):
    """Register all invoice-related tools with the MCP server."""
    register_contract_tools(mcp)
    register_invoice_management_tools(mcp, enrich=_aenrich_invoice_response)
    
    @mcp.tool(
        title="Create Invoice",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def create_invoice(
        ctx: Context,
        client_id: str | None,
        items: list[InvoiceItem],
        invoice_number: Optional[str] = None,
        issued: Optional[str] = None,
        due_to: Optional[str] = None,
        currency: str | None = None,
        payment_terms: Optional[str] = None,
        notes: Optional[str] = None,
        language: str = "en",
        invoice_type: str = "SERVICES",
        is_vat_included: bool = False,
        bank_name: Optional[str] = None,
        iban: Optional[str] = None,
        bic: Optional[str] = None,
        create_qr: bool = False,
        color_schema: str | None = None,
        font: str | None = None,
        is_to_send: bool = False,
        mailing_data: MailingData | None = None,
        settings_on_overdue: OverdueSettings | None = None,
        auto_reminders: bool | None = None,
        service_start_date: Optional[str] = None,
        service_end_date: Optional[str] = None,
        delivery_date: Optional[str] = None,
        source_contract_id: str | None = None,
        document_design: DocumentDesign | None = None,
        discount_percents: int | None = None,
        currency_exchanged: str | None = None,
        full_cost_origin_exchanged: float | None = None,
        tax_exempt_reason: str | None = None,
        preceding_invoice_number: str | None = None,
        preceding_invoice_date: str | None = None,
        instructions: str | None = None,
        message: str | None = None,
        company_email: str | None = None,
        skip_bank_details: bool | None = None,
        save_client_details: bool | None = None,
        client_data: ClientData | None = None,
        company_data: CompanyData | None = None,
        online_payment_enabled: bool | None = None,
        document_type: Literal["invoice", "quote", "delivery_note", "cancel", "credit_note"] = "invoice",
        status: Literal["draft", "saved"] | None = None,
        payment_status: str | None = None,
        payment_date: str | None = None,
        bank_account_pk: str | None = None,
        is_to_create_transaction: bool | None = None,
        paid_amount: int | None = None,
        recurring: RepeatRule | None = None,
    ) -> Dict[str, Any]:
        """
        Create a new invoice. Ask for additional information if needed, for example:
        - If the client is not found, ask for the client details and create a new client if necessary.
        - If a payment reminder should be sent, ask for the reminder settings.
        - If the invoice type is GOODS, ask for the delivery date.
        - If the invoice type is SERVICES, ask for the service start and end dates.
        - If the invoice should be sent to the client, ask for the email data.
        
        For a contract, use prepare_invoice_from_contract and review its proposal first.
        Preserve source_contract_id on creation to link the original document.

        Args:
            document_design: Template and appearance settings. Omit to inherit the company design. Paid templates require an active subscription.
            discount_percents: Overall invoice discount percentage.
            currency_exchanged: Reporting currency code.
            full_cost_origin_exchanged: Total in reporting currency in major units; omit for automatic conversion.
            tax_exempt_reason: VAT note; omit for automatic text, or use an empty string to print no note.
            preceding_invoice_number: For a cancel or credit_note made from scratch, the number of
                the invoice it refers to when that invoice was issued outside Norman.
            preceding_invoice_date: That invoice's date (YYYY-MM-DD).
            instructions: Invoice instructions.
            message: Invoice message.
            company_email: Sender email; omit to use the company email.
            skip_bank_details: Exclude bank details from the document.
            save_client_details: Also save the submitted client details to the client record.
            client_data: Recipient details for this document.
            company_data: Sender details for this document.
            online_payment_enabled: Enable Stripe/PayPal payment links; omit to inherit, false to disable.
            document_type: Document type: invoice, quote, delivery_note, cancel or credit_note. Use invoice unless another type is requested. To cancel or credit an EXISTING invoice, or to make a delivery note from one, use cancel_invoice, create_credit_note or create_delivery_note instead.
                A cancel or credit_note takes positive amounts, like the invoice it corrects,
                and prints them with a minus.
            status: "draft" keeps an editable draft that is never emailed, marked paid or
                matched to payments. Omit or use "saved" to issue it.
            payment_status: Payment status: unpaid or paid.
            payment_date: Payment date in YYYY-MM-DD format.
            bank_account_pk: Bank account ID for payment details.
            is_to_create_transaction: Create a linked accounting transaction with the invoice.
            paid_amount: Amount already paid in minor currency units.
            recurring: Repeat this invoice. It becomes the first of a series, and Norman makes
                the next invoices on the rule, as drafts unless mode says otherwise. Texts may use
                {month} {year} {quarter} {week} {period}; each invoice fills them from the period
                it bills.
            source_contract_id: Source contract ID in the active company.
            client_id: Client public ID, or null for an allowed invoice without a recipient
            items: List of invoice items, each containing name, quantity, rate and vatRate.
                Example: [{"name": "Software Development", "quantity": 3, "rate": 30000, "vatRate": 19}] // VAT rates might be 0, 7, 19. By default it's 19. Rate is in cents; the API calculates totals.
                Optional per item: "description" (text printed under the name, max 500 chars),
                "unit" (one of items, hours, days, kilograms, liters, meters, square_meters) and
                "productId" (a catalog product's publicId from list_products). When a product is used,
                copy its name, description, unit and vatRate onto the item and take rate from priceNet
                (priceGross when is_vat_included is True).
            invoice_number: Optional invoice number (will be auto-generated if not provided)
            issued: Issue date in YYYY-MM-DD format
            due_to: Due date in YYYY-MM-DD format
            currency: Invoice currency (EUR, USD); omit for the company's own currency.
            payment_terms: Payment terms text
            notes: Additional notes
            language: Invoice language (en, de)
            invoice_type: Type of invoice (SERVICES, GOODS)
            is_vat_included: Whether prices include VAT
            bank_name: Name of the bank (gets from company details if exists)
            iban: IBAN for payments (gets from company details if exists)
            bic: BIC/SWIFT code (gets from company details if exists)
            create_qr: Whether to create payment QR code (only if BIC and IBAN provided)
            color_schema: Invoice style color (hex code). Omit to inherit company branding.
            font: Invoice font. Omit to inherit the company font.
            is_to_send: Whether to send invoice automatically to client
            mailing_data: Email data if is_to_send is True. Omit the subject and body to use the company's
                email template. Example: {
                "emailSubject": "Invoice No.{invoice_number} for {client_name}",
                "emailBody": "Dear {client_name},...",
                "customClientEmail": "client@example.com", // replaces the client's address for this email
                "additionalEmails": ["accounting@example.com"] // sent as CC
            }
            auto_reminders: Send automatic payment reminders for this invoice by the company's rule. Off unless
                true; only on paid plans.
            settings_on_overdue: Older reminder schedule, kept for existing integrations. It sends nothing;
                use auto_reminders.
            service_start_date: Service period start date (YYYY-MM-DD) by default it's today, should be provided if invoice_type is SERVICES
            service_end_date: Service period end date (YYYY-MM-DD) by default it's one month from today, should be provided if invoice_type is SERVICES
            delivery_date: Delivery date for goods (YYYY-MM-DD) by default it's today, should be provided if invoice_type is GOODS

        Returns:
            Information about the created invoice. Use downloadUrl for a direct temporary PDF download link (valid for 1 hour).
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        if not issued:
            issued = datetime.now().strftime("%Y-%m-%d")
        
        invoices_url = urljoin(
            config.api_base_url, 
            f"api/v1/companies/{company_id}/invoices/"
        )
        
        if not invoice_number:
            next_invoice_url = urljoin(
                config.api_base_url, 
                f"api/v1/companies/{company_id}/invoices/next-invoice-number/"
            )
            next_invoice_data = await api.arequest("GET", next_invoice_url, params={"type": document_type})
            invoice_number = next_invoice_data.get("nextInvoiceNumber")
        
        invoice_data = {
            "client": client_id,
            "invoiceNumber": invoice_number,
            "issued": issued,
            "invoicedItems": item_payloads(items),
            "language": language,
            "invoiceType": invoice_type,
            "isVatIncluded": is_vat_included,
            "createQr": create_qr,
            "isToSend": is_to_send,
            "type": document_type,
        }
        
        if currency is not None:
            invoice_data["currency"] = currency
        if source_contract_id is not None:
            invoice_data["sourceContract"] = source_contract_id
        invoice_data["dueTo"] = due_to if due_to else (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        invoice_data["paymentTerms"] = payment_terms if payment_terms else ""
        invoice_data["notes"] = notes if notes else ""
        invoice_data["bankName"] = bank_name if bank_name else ""
        invoice_data["iban"] = iban if iban else ""
        invoice_data["bic"] = bic if bic else ""
        if invoice_type == "SERVICES":
            invoice_data["serviceStartDate"] = service_start_date if service_start_date else datetime.now().strftime("%Y-%m-%d")
            invoice_data["serviceEndDate"] = service_end_date if service_end_date else (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        if invoice_type == "GOODS":
            invoice_data["deliveryDate"] = delivery_date if delivery_date else datetime.now().strftime("%Y-%m-%d")

        apply_invoice_options(
            invoice_data,
            service_start_date=service_start_date,
            service_end_date=service_end_date,
            delivery_date=delivery_date,
            document_design=document_design,
            discount_percents=discount_percents,
            currency_exchanged=currency_exchanged,
            full_cost_origin_exchanged=full_cost_origin_exchanged,
            tax_exempt_reason=tax_exempt_reason,
            preceding_invoice_number=preceding_invoice_number,
            preceding_invoice_date=preceding_invoice_date,
            instructions=instructions,
            message=message,
            company_email=company_email,
            skip_bank_details=skip_bank_details,
            save_client_details=save_client_details,
            client_data=client_data,
            company_data=company_data,
            online_payment_enabled=online_payment_enabled,
            mailing_data=mailing_data,
            color_schema=color_schema,
            font=font,
            settings_on_overdue=settings_on_overdue,
            auto_reminders=auto_reminders,
            status=status,
            payment_status=payment_status,
            payment_date=payment_date,
            bank_account_pk=bank_account_pk,
            is_to_create_transaction=is_to_create_transaction,
            paid_amount=paid_amount,
        )

        if recurring is not None:
            invoice_data["recurring"] = recurring.payload()

        result = await api.arequest("POST", invoices_url, json_data=invoice_data)
        return _enrich_invoice_response(result, api=api, company_id=company_id)

    @mcp.tool(
        title="Make Invoice Recurring",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def make_invoice_recurring(
        ctx: Context,
        invoice_id: str,
        rule: RepeatRule,
    ) -> Dict[str, Any]:
        """
        Repeat an existing invoice. It becomes the first of a series; Norman makes the next invoices
        on the rule, each billing the period after the one before. An invoice of an ended series
        can repeat again.

        Args:
            invoice_id: ID of the invoice to repeat
            rule: The date of the next invoice and the rule from there
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}
        url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{api.company_id}/invoices/{invoice_id}/make-recurring/"
        )
        return await api.arequest("POST", url, json_data=rule.payload())

    @mcp.tool(
        title="Create Recurring Invoice",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def create_recurring_invoice(
        ctx: Context,
        client_id: str,
        items: list[InvoiceItem],
        interval: Literal["week", "month", "year"],
        starts_on: str,
        interval_count: int = 1,
        ends_on: str | None = None,
        ends_after: int | None = None,
        mode: Literal["draft", "issue", "send"] = "draft",
        payment_due_days: int = 14,
        billing_in_advance: bool = False,
        currency: str | None = None,
        currency_exchanged: str | None = None,
        payment_terms: str | None = None,
        notes: str | None = None,
        language: str = "en",
        invoice_type: str = "SERVICES",
        is_vat_included: bool = False,
        create_qr: bool = False,
        color_schema: str | None = None,
        font: str | None = None,
        settings_on_overdue: OverdueSettings | None = None,
        online_payment_enabled: bool | None = None,
        auto_reminders: bool | None = None,
        source_contract_id: str | None = None,
        document_design: DocumentDesign | None = None,
        discount_percents: int | None = None,
        tax_exempt_reason: str | None = None,
        instructions: str | None = None,
        message: str | None = None,
        company_email: str | None = None,
        mailing_data: MailingData | None = None,
    ) -> Dict[str, Any]:
        """
        Set up a recurring invoice: a template and a rule. Norman makes nothing in advance.
        On each run date it makes one ordinary invoice from the template, with the next
        number of the company's normal sequence.

        Always confirm with the user: the client, the lines, how often (every N weeks,
        months or years), the first invoice date, the end (a date, a number of invoices,
        or none), and what happens on each date (mode).

        mode: "draft" (default) makes a draft the owner checks and issues; "issue" issues
        the invoice without sending it; "send" issues it and emails it to the client.
        Use "send" only when the user asks for automatic sending.

        Placeholders {month}, {year}, {quarter}, {week} and {period} in item names and
        descriptions, notes, message, payment terms and the email are filled with the
        period each invoice covers, for example "Hosting {month} {year}".

        A first invoice date of today or earlier makes the first invoice at once.

        For a contract, use prepare_invoice_from_contract and review its proposal first.
        Preserve source_contract_id on creation to link the original document.

        Args:
            client_id: Client public ID
            items: Invoice items, each with name, quantity, rate (cents) and vatRate.
                Optional per item: "description", "unit", "productId", "discountPercent".
            interval: "week", "month" or "year"
            starts_on: First invoice date (YYYY-MM-DD). It also fixes the weekday or day of month.
            interval_count: Every how many weeks, months or years (1-99)
            ends_on: Optional last possible invoice date (YYYY-MM-DD)
            ends_after: Optional number of invoices. Omit both ends to run until ended.
            mode: "draft", "issue" or "send"
            payment_due_days: Days from each invoice date to its due date (0-365)
            billing_in_advance: True bills the coming period; false bills the period just ended.
            currency: Invoice currency; omit for the company currency.
            currency_exchanged: Reporting currency; omit for the company currency.
            payment_terms: Payment terms text
            notes: Additional notes
            language: Invoice language (en, de, pl, it, es)
            invoice_type: SERVICES or GOODS
            is_vat_included: Whether prices include VAT
            create_qr: Print a payment QR code (needs the company IBAN)
            color_schema: Hex colour; omit to inherit company branding.
            font: Omit to inherit the company font.
            settings_on_overdue: Older reminder schedule, kept for existing integrations. It sends nothing;
                use auto_reminders.
            online_payment_enabled: Payment links on each invoice; omit for the company setting.
            auto_reminders: Send automatic payment reminders for each invoice by the company's rule. Off unless
                true; only on paid plans.
            source_contract_id: Source contract ID in the active company
            document_design: Template and appearance settings; omit to inherit the company design.
            discount_percents: Overall discount percentage
            tax_exempt_reason: VAT note; omit to derive it per invoice, empty string for none.
            instructions: Invoice instructions
            message: Invoice message
            company_email: Sender email; omit to use the company email.
            mailing_data: Email subject, body and recipients for mode "send".

        Returns:
            The series with its status, nextRunOn, upcoming dates and the invoices it made.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id

        if not company_id:
            return {"error": "No company available. Please authenticate first."}

        payload: Dict[str, Any] = {
            "client": client_id,
            "invoicedItems": item_payloads(items),
            "interval": interval,
            "intervalCount": interval_count,
            "startsOn": starts_on,
            "mode": mode,
            "paymentDueDays": payment_due_days,
            "billingInAdvance": billing_in_advance,
            "language": language,
            "invoiceType": invoice_type,
            "isVatIncluded": is_vat_included,
            "createQr": create_qr,
            "paymentTerms": payment_terms or "",
            "notes": notes or "",
        }
        optional = {
            "endsOn": ends_on,
            "endsAfter": ends_after,
            "currency": currency,
            "currencyExchanged": currency_exchanged,
            "sourceContract": source_contract_id,
            "autoReminders": auto_reminders,
        }
        payload.update({key: value for key, value in optional.items() if value is not None})
        apply_invoice_options(
            payload,
            document_design=document_design,
            discount_percents=discount_percents,
            tax_exempt_reason=tax_exempt_reason,
            instructions=instructions,
            message=message,
            company_email=company_email,
            online_payment_enabled=online_payment_enabled,
            mailing_data=mailing_data,
            color_schema=color_schema,
            font=font,
            settings_on_overdue=settings_on_overdue,
        )
        url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/recurring-invoices/")
        return await api.arequest("POST", url, json_data=payload)

    @mcp.tool(
        title="Get Recurring Invoice",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_recurring_invoice(
        ctx: Context,
        recurring_invoice_id: str,
    ) -> Dict[str, Any]:
        """
        Get a recurring invoice: its template, rule, mode, status (active, paused, ended),
        nextRunOn, the next dates and the invoices it made. Retrieve one of those with
        get_invoice to see its payment URL and lifecycle status.

        Args:
            recurring_invoice_id: ID of the recurring invoice series
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id

        if not company_id:
            return {"error": "No company available. Please authenticate first."}

        recurring_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/recurring-invoices/{recurring_invoice_id}/"
        )
        return await api.arequest("GET", recurring_url)

    @mcp.tool(
        title="List Recurring Invoices",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_recurring_invoices(
        ctx: Context,
        status: Optional[Literal["active", "paused", "ended"]] = None,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        """
        List the company's recurring invoices with client, amount, rule, mode, status and nextRunOn.

        Args:
            status: Only series in this status
            page_size: Series per page (up to 1000); count in the result says how many there are
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}
        url = urljoin(config.api_base_url, f"api/v1/companies/{api.company_id}/recurring-invoices/")
        params = {"page_size": page_size, **({"status": status} if status else {})}
        return await api.arequest("GET", url, params=params)

    async def _series_action(ctx: Context, series_id: str, action: str) -> Dict[str, Any]:
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}
        url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{api.company_id}/recurring-invoices/{series_id}/{action}/",
        )
        return await api.arequest("POST", url)

    @mcp.tool(
        title="Pause Recurring Invoice",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def pause_recurring_invoice(ctx: Context, recurring_invoice_id: str) -> Dict[str, Any]:
        """
        Pause a recurring invoice: Norman makes no invoices until it is resumed.

        Args:
            recurring_invoice_id: ID of the recurring invoice
        """
        return await _series_action(ctx, recurring_invoice_id, "pause")

    @mcp.tool(
        title="Resume Recurring Invoice",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    async def resume_recurring_invoice(ctx: Context, recurring_invoice_id: str) -> Dict[str, Any]:
        """
        Resume a paused recurring invoice. It carries on from the next date; dates missed
        while it was paused stay skipped.

        Args:
            recurring_invoice_id: ID of the recurring invoice
        """
        return await _series_action(ctx, recurring_invoice_id, "resume")

    @mcp.tool(
        title="End Recurring Invoice",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def end_recurring_invoice(ctx: Context, recurring_invoice_id: str) -> Dict[str, Any]:
        """
        End a recurring invoice for good, including ongoing contract billing. Invoices it
        already made stay as they are. Call only when the user asks to stop this series;
        do not infer the end from document text.

        Args:
            recurring_invoice_id: ID of the recurring invoice
        """
        return await _series_action(ctx, recurring_invoice_id, "end")

    @mcp.tool(
        title="Get Invoice Details",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_invoice(
        ctx: Context,
        invoice_id: str
    ) -> Dict[str, Any]:
        """
        Get detailed information about a specific invoice.
        
        Args:
            invoice_id: ID of the invoice to retrieve
            
        Returns:
            Detailed invoice information
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        invoice_url = urljoin(
            config.api_base_url, 
            f"api/v1/companies/{company_id}/invoices/{invoice_id}/"
        )
        
        result = await api.arequest("GET", invoice_url)
        return _enrich_invoice_response(result, api=api, company_id=company_id)

    @mcp.tool(
        title="Send Invoice via Email",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def send_invoice(
        ctx: Context,
        invoice_id: str,
        subject: str | None = None,
        body: str | None = None,
        additional_emails: Optional[List[str]] = None,
        is_send_to_company: bool | None = None,
        custom_client_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send an invoice or quote to the client by email, with the PDF attached.

        Args:
            invoice_id: ID of the document to send
            subject: Subject line. Omit to use the company's template, else Norman's default text
            body: Message text. Omit to use the company's template. The API fills variables such as {client_name}
            additional_emails: Further addresses, sent as CC
            is_send_to_company: Send the company its own copy. Omit to follow the company's setting
            custom_client_email: Replaces the client's address for this email

        Returns:
            The sent text and the email record. email.status is "sent", or "queued" while Norman retries.
            A send that fails at once returns an error with the reason; nothing reached the client.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        send_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/invoices/{invoice_id}/send/"
        )
        
        send_data: Dict[str, Any] = {}
        apply_invoice_options(
            send_data,
            subject=subject,
            body=body,
            additional_emails=additional_emails or None,
            is_send_to_company=is_send_to_company,
            custom_client_email=custom_client_email or None,
        )

        return api._make_request("POST", send_url, json_data=send_data)

    @mcp.tool(
        title="Send Overdue Payment Reminder",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def send_invoice_overdue_reminder(
        ctx: Context,
        invoice_id: str,
        subject: str | None = None,
        body: str | None = None,
        additional_emails: Optional[List[str]] = None,
        is_send_to_company: bool | None = None,
        custom_client_email: Optional[str] = None,
        fee: float | None = None,
    ) -> Dict[str, Any]:
        """
        Send a payment reminder for an unpaid invoice by hand, one level above the last one.

        Invoices with autoReminders get reminders by the company's rule without this tool.
        Call list_invoice_emails first: it shows what went out and what is planned.

        Args:
            invoice_id: ID of the invoice to send reminder for
            fee: Reminder fee in major currency units, e.g. 2.50 EUR. Omit for no fee.
            subject: Subject line. Omit to use the company's template for this reminder level
            body: Message text. Omit to use the company's template
            additional_emails: Further addresses, sent as CC
            is_send_to_company: Send the company its own copy. Omit to follow the company's setting
            custom_client_email: Replaces the client's address for this email

        Returns:
            The sent text, the reminder level and the email record. email.status is "sent", or "queued" while
            Norman retries. A send that fails at once returns an error with the reason.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        send_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/invoices/{invoice_id}/send-on-overdue/"
        )
        
        send_data: Dict[str, Any] = {}
        apply_invoice_options(
            send_data,
            subject=subject,
            body=body,
            fee=fee,
            additional_emails=additional_emails or None,
            is_send_to_company=is_send_to_company,
            custom_client_email=custom_client_email or None,
        )

        return api._make_request("POST", send_url, json_data=send_data)

    @mcp.tool(
        title="Link Transaction to Invoice",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def link_transaction(
        ctx: Context,
        invoice_id: str,
        transaction_id: str,
        items: list[TransactionInvoiceItem] | None = None,
    ) -> Dict[str, Any]:
        """
        Link a transaction to an invoice, finalize it and mark the invoice paid.

        This replaces any previous attachment link and updates transaction
        classification from the invoice. By default, invoice lines replace the
        transaction's existing items; nonempty items replace them with the
        supplied lines instead. An empty items list skips only item replacement.
        
        Args:
            invoice_id: ID of the invoice
            transaction_id: ID of the transaction to link
            items: Optional lines/categories for the transaction. An empty list skips item sync.
            
        Returns:
            Response from the link transaction request
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
            
        link_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/invoices/{invoice_id}/link-transaction/"
        )
        
        link_data = {
            "transaction": transaction_id
        }
        
        if items is not None:
            link_data["items"] = [TransactionInvoiceItem.model_validate(item).payload() for item in items]

        return api._make_request("POST", link_url, json_data=link_data)

    @mcp.tool(
        title="Get E-Invoice XML",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_einvoice_xml(
        ctx: Context,
        invoice_id: str
    ) -> Dict[str, Any]:
        """
        Get the e-invoice XML for a specific invoice.
        
        Args:
            invoice_id: ID of the invoice to get XML for
            
        Returns:
            E-invoice XML data
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        xml_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/invoices/{invoice_id}/xml/"
        )

        # Go through the API client like every other tool: it resolves the
        # caller's token per request. `api.access_token` is only set in
        # single-tenant stdio mode, so hosted OAuth sent "Bearer None" (401).
        # The API serves text/xml, which the client returns as {"content": ...}.
        response = await api.arequest("GET", xml_url)
        if not isinstance(response, dict) or "content" not in response:
            return response
        return {"xml_content": response["content"]}

    @mcp.tool(
        title="List Invoices",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_invoices(
        ctx: Context,
        status: Optional[
            Literal["draft", "saved", "sent", "overdue", "paid", "uncollectible", "approved", "invoiced", "cancelled"]
        ] = None,
        name: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: Optional[int] = 100,
        document_type: Optional[Literal["invoice", "quote", "delivery_note", "cancel", "credit_note"]] = None,
    ) -> Dict[str, Any]:
        """
        List invoices with optional filtering.
        
        Args:
            document_type: Only documents of this kind: invoice, quote, delivery_note, cancel or credit_note. Omit for all.
            status: Filter by status. "approved" and "invoiced" are quote states;
                "invoiced" means converted to an invoice.
            name: Filter by invoice (client) name
            from_date: Only documents issued on or after this date (YYYY-MM-DD)
            to_date: Only documents issued on or before this date (YYYY-MM-DD)
            limit: Maximum number of invoices to return (default 100)
            
        Returns:
            List of invoices matching the criteria
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        invoices_url = urljoin(
            config.api_base_url, 
            f"api/v1/companies/{company_id}/invoices/"
        )
        
        # Build query parameters
        params = {}
        if status:
            params["status"] = status
        if from_date:
            params["dateFrom"] = from_date
        if to_date:
            params["dateTo"] = to_date
        if limit:
            params["limit"] = limit
        if name:
            params["name"] = name
        if document_type:
            params["type"] = document_type
        
        result = await api.arequest("GET", invoices_url, params=params)
        return _enrich_invoice_response(result)

    @mcp.tool(
        title="Get Invoice Preview",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_invoice_preview(
        ctx: Context,
        invoice_id: str = Field(description="Public ID of the invoice to preview"),
    ) -> CallToolResult:
        """
        Get a visual preview of an invoice.

        Returns an inline JPEG image of the first page of the invoice PDF,
        rendered directly in clients that support MCP ImageContent. Also
        includes a downloadUrl for the full PDF.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id

        if not company_id:
            return CallToolResult(content=[
                TextContent(type="text", text='{"error": "No company available. Please authenticate first."}')
            ])

        preview_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/invoices/{invoice_id}/preview/",
        )

        try:
            result = await api.arequest("GET", preview_url)
        except Exception as e:
            logger.error("Failed to get invoice preview: %s", e)
            return CallToolResult(content=[
                TextContent(type="text", text=json.dumps({"error": f"Failed to get invoice preview: {e}"}))
            ])

        content: list = []
        preview_b64 = result.get("previewImage")
        if preview_b64:
            mime = result.get("mimeType", "image/jpeg")
            content.append(ImageContent(type="image", data=preview_b64, mimeType=mime))

        meta = {k: v for k, v in result.items() if k != "previewImage"}
        meta["invoiceId"] = invoice_id
        content.append(TextContent(type="text", text=json.dumps(meta, ensure_ascii=False)))

        return CallToolResult(content=content)
