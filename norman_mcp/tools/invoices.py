import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urljoin

from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context
from norman_mcp.tools._concurrency import gather_bounded
from norman_mcp.tools.contracts import register_contract_tools
from norman_mcp.tools.invoice_management import register_invoice_management_tools
from norman_mcp.tools.invoice_schemas import (
    ClientData,
    CompanyData,
    DocumentDesign,
    InvoiceItem,
    MailingData,
    OverdueSettings,
    TransactionInvoiceItem,
    apply_invoice_options,
    item_payloads,
)

logger = logging.getLogger(__name__)


async def _enrich_invoice_response(data: dict, api=None, company_id: str | None = None) -> dict:
    """Replace private reportUrl with a presigned downloadUrl (1-hour TTL)."""
    if not isinstance(data, dict):
        return data

    async def _enrich_single(item: dict) -> None:
        pid = item.get("publicId")
        if pid and item.get("reportUrl") and api and company_id:
            pdf_endpoint = urljoin(
                config.api_base_url,
                f"api/v1/companies/{company_id}/invoices/{pid}/pdf/",
            )
            resp = await api.arequest("GET", pdf_endpoint)
            if isinstance(resp, dict) and resp.get("url"):
                item["downloadUrl"] = resp["url"]
            else:
                logger.debug("Could not fetch presigned PDF URL for invoice %s", pid)

    items = [data] if data.get("publicId") else []
    if isinstance(data.get("results"), list):
        items.extend(item for item in data["results"] if isinstance(item, dict))
    await gather_bounded(_enrich_single(item) for item in items)
    return data


def sent_or_nothing_sent(result: Any) -> Any:
    """The send result, or an error when the API sent nothing.

    The send endpoints answer 201 with an empty body when the sender skips the
    email because there is no recipient address (plan and email-verification
    blocks are 403s). The tools returned that {} as-is, and the agent told the
    user the email was on its way.
    """
    if result == {}:
        return {
            "error": (
                "Nothing was sent: there is no recipient email address. Add an email to "
                "the client, or pass custom_client_email, and send again."
            ),
            "code": "no_recipient",
        }
    return result


def register_invoice_tools(mcp):
    """Register all invoice-related tools with the MCP server."""
    register_contract_tools(mcp)
    register_invoice_management_tools(mcp, enrich=_enrich_invoice_response)
    
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
        service_start_date: Optional[str] = None,
        service_end_date: Optional[str] = None,
        delivery_date: Optional[str] = None,
        source_contract_id: str | None = None,
        document_design: DocumentDesign | None = None,
        discount_percents: int | None = None,
        currency_exchanged: str | None = None,
        full_cost_origin_exchanged: float | None = None,
        tax_exempt_reason: str | None = None,
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
            instructions: Invoice instructions.
            message: Invoice message.
            company_email: Sender email; omit to use the company email.
            skip_bank_details: Exclude bank details from the document.
            save_client_details: Also save the submitted client details to the client record.
            client_data: Recipient details for this document.
            company_data: Sender details for this document.
            online_payment_enabled: Enable Stripe/PayPal payment links; omit to inherit, false to disable.
            document_type: Document type: invoice, quote, delivery_note, cancel or credit_note. Use invoice unless another type is requested. To cancel or credit an EXISTING invoice, or to make a delivery note from one, use cancel_invoice, create_credit_note or create_delivery_note instead.
            status: "draft" keeps an editable draft that is never emailed, marked paid or
                matched to payments. Omit or use "saved" to issue it.
            payment_status: Payment status: unpaid or paid.
            payment_date: Payment date in YYYY-MM-DD format.
            bank_account_pk: Bank account ID for payment details.
            is_to_create_transaction: Create a linked accounting transaction with the invoice.
            paid_amount: Amount already paid in minor currency units.
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
            mailing_data: Email data if is_to_send is True. Example: {
                "emailSubject": "Invoice No.{invoice_number} for {client_name}",
                "emailBody": "Dear {client_name},...",
                "customClientEmail": "client@example.com" // email to send the invoice to, if not provided, it will be sent to the client email address
            }
            settings_on_overdue: Configuration for overdue notifications. Example: {
                "isToAutosendNotification": true, // whether to send notification automatically
                "customEmailSubject": "Reminder: Invoice {invoice_number} is overdue", // custom email subject
                "customEmailBody": "Dear {client_name},...", // custom email body
                "notifyAfterDays": [1, 3], // days to notify after the due date
                "notifyInParticularDays": [] // days to notify in particular dates [2025-05-23", "2025-05-24"]
            }
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
            status=status,
            payment_status=payment_status,
            payment_date=payment_date,
            bank_account_pk=bank_account_pk,
            is_to_create_transaction=is_to_create_transaction,
            paid_amount=paid_amount,
        )

        result = await api.arequest("POST", invoices_url, json_data=invoice_data)
        return await _enrich_invoice_response(result, api=api, company_id=company_id)

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
        client_id: str | None,
        items: list[InvoiceItem],
        frequency_type: str,
        frequency_unit: int,
        starts_from_date: str,
        ends_on_date: Optional[str] = None,
        ends_on_invoice_count: Optional[int] = None,
        invoice_number: Optional[str] = None,
        currency: str = "EUR",
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
        settings_on_overdue: OverdueSettings | None = None,
        source_contract_id: str | None = None,
        payment_due_days: int | None = None,
        billing_in_advance: bool = False,
        is_ongoing: bool = False,
        document_design: DocumentDesign | None = None,
        discount_percents: int | None = None,
        currency_exchanged: str | None = None,
        full_cost_origin_exchanged: float | None = None,
        tax_exempt_reason: str | None = None,
        instructions: str | None = None,
        message: str | None = None,
        company_email: str | None = None,
        skip_bank_details: bool | None = None,
        save_client_details: bool | None = None,
        client_data: ClientData | None = None,
        company_data: CompanyData | None = None,
        online_payment_enabled: bool | None = None,
        mailing_data: MailingData | None = None,
    ) -> Dict[str, Any]:
        """
        Create a recurring invoice that will automatically generate new invoices based on specified frequency.
        Useful for contracts or services that bill on a regular basis.
        Always ask for recurring configuration, for example:
            - How often to generate invoices (weekly, monthly)
            - Number of units for frequency (e.g. 1 for monthly = every month, 2 = every 2 months)
            - Start date
            - End date
            - End invoice count (optional)
            
        Ask for additional information if needed, for example:
            - If the client is not found, ask for the client details and create a new client if necessary.
            - If the invoice number is not provided, ask for it.
            - If the due date is not provided, ask for it.
            - If the payment terms are not provided, ask for it.
            - If the bank details are not provided, ask for it.

        For a contract, use prepare_invoice_from_contract and review its proposal first.
        Preserve source_contract_id on creation to link the original document.

        Args:
            document_design: Template and appearance settings. Omit to inherit the company design. Paid templates require an active subscription.
            discount_percents: Overall invoice discount percentage.
            currency_exchanged: Reporting currency code.
            full_cost_origin_exchanged: Total in reporting currency in major units; omit for automatic conversion.
            tax_exempt_reason: VAT note; omit for automatic text, or use an empty string to print no note.
            instructions: Invoice instructions.
            message: Invoice message.
            company_email: Sender email; omit to use the company email.
            skip_bank_details: Exclude bank details from the document.
            save_client_details: Also save the submitted client details to the client record.
            client_data: Recipient details for this document.
            company_data: Sender details for this document.
            online_payment_enabled: Enable Stripe/PayPal payment links; omit to inherit, false to disable.
            mailing_data: Email subject, body, recipient, extra recipients and copy-to-company option.
            source_contract_id: Source contract ID in the active company.
            client_id: Client public ID, or null for an allowed invoice without a recipient
            items: List of invoice items, each containing name, quantity, rate and vatRate.
                Optional per item: "description", "unit" and "productId", as in create_invoice.
            is_ongoing: Continue until cancelled; omit both end conditions when true.
            payment_due_days: Days after each issue date until payment is due (0-365).
            billing_in_advance: True bills the upcoming service period; false bills in arrears.
            frequency_type: How often to generate invoices ("weekly", "monthly")
            frequency_unit: Number of units for frequency (e.g. 1 for monthly = every month, 2 = every 2 months)
            starts_from_date: Date to start generating invoices from (YYYY-MM-DD)
            ends_on_date: Optional end date for recurring invoices (YYYY-MM-DD). Either ends_on_date or ends_on_invoice_count should be provided.
            ends_on_invoice_count: Optional number of invoices to generate before stopping. Either ends_on_date or ends_on_invoice_count should be provided.
            invoice_number: Base invoice number (will be auto-generated if not provided)
            currency: Invoice currency, e.g. USD. EUR, the default, bills in the company's own currency.
            payment_terms: Payment terms text
            notes: Additional notes
            language: Invoice language (en, de)
            invoice_type: Type of invoice (SERVICES, GOODS)
            is_vat_included: Whether prices include VAT
            bank_name: Name of the bank
            iban: IBAN for payments
            bic: BIC/SWIFT code
            create_qr: Whether to create payment QR code
            color_schema: Invoice style color (hex code). Omit to inherit company branding.
            font: Invoice font. Omit to inherit the company font.
            is_to_send: Whether to send invoices automatically to client
            settings_on_overdue: Configuration for overdue notifications

        Returns:
            Information about the created recurring invoice. Use downloadUrl for a direct temporary PDF download link (valid for 1 hour).
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}

        recurring_invoices_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/recurring-invoices/"
        )

        if not invoice_number:
            next_invoice_url = urljoin(
                config.api_base_url,
                f"api/v1/companies/{company_id}/invoices/next-invoice-number/"
            )
            next_invoice_data = await api.arequest("GET", next_invoice_url)
            invoice_number = next_invoice_data.get("nextInvoiceNumber")

        invoice_data = {
            "client": client_id,
            "recurringNumber": invoice_number,
            "invoicedItems": item_payloads(items),
            "currency": currency,
            "language": language,
            "invoiceType": invoice_type,
            "isVatIncluded": is_vat_included,
            "createQr": create_qr,
            "isToSend": is_to_send,
            "frequencyType": frequency_type,
            "frequencyUnit": frequency_unit,
            "startsFromDate": starts_from_date,
        }

        invoice_data["isOngoing"] = is_ongoing
        # Add conditional end parameters
        if ends_on_date is not None:
            invoice_data["endsOnDate"] = ends_on_date
        if ends_on_invoice_count is not None:
            invoice_data["endsOnInvoiceCount"] = ends_on_invoice_count
        
        if not is_ongoing and ends_on_date is None and ends_on_invoice_count is None:
            invoice_data["endsOnInvoiceCount"] = 3

        if payment_due_days is not None:
            invoice_data["paymentDueDays"] = payment_due_days
        invoice_data["billingInAdvance"] = billing_in_advance

        # Add optional fields
        if source_contract_id is not None:
            invoice_data["sourceContract"] = source_contract_id
        invoice_data["paymentTerms"] = payment_terms if payment_terms else ""
        invoice_data["notes"] = notes if notes else ""
        invoice_data["bankName"] = bank_name if bank_name else ""
        invoice_data["iban"] = iban if iban else ""
        invoice_data["bic"] = bic if bic else ""
        

        apply_invoice_options(
            invoice_data,
            document_design=document_design,
            discount_percents=discount_percents,
            currency_exchanged=currency_exchanged,
            full_cost_origin_exchanged=full_cost_origin_exchanged,
            tax_exempt_reason=tax_exempt_reason,
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
        )

        result = await api.arequest("POST", recurring_invoices_url, json_data=invoice_data)
        return await _enrich_invoice_response(result, api=api, company_id=company_id)

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
        return await _enrich_invoice_response(result, api=api, company_id=company_id)

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
        subject: str,
        body: str,
        additional_emails: Optional[List[str]] = None,
        is_send_to_company: bool = False,
        custom_client_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send an invoice via email.
        
        Args:
            invoice_id: ID of the invoice to send
            subject: Email subject line
            body: Email body content
            additional_emails: List of additional email addresses to send to
            is_send_to_company: Whether to send the copy to the company email (Owner)
            custom_client_email: Custom email address for the client (By default the email address of the client is used if it is set)
            
        Returns:
            Response from the send invoice request
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        send_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/invoices/{invoice_id}/send/"
        )
        
        send_data = {
            "subject": subject,
            "body": body,
            "isSendToCompany": is_send_to_company
        }
        
        if additional_emails:
            send_data["additionalEmails"] = additional_emails if additional_emails else []
        if custom_client_email:
            send_data["customClientEmail"] = custom_client_email
            
        return sent_or_nothing_sent(await api.arequest("POST", send_url, json_data=send_data))

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
        is_send_to_company: bool = False,
        custom_client_email: Optional[str] = None,
        fee: float | None = None,
    ) -> Dict[str, Any]:
        """
        Send an overdue payment reminder for an invoice via email.
        
        Args:
            invoice_id: ID of the invoice to send reminder for
            fee: Reminder fee in major currency units, e.g. 2.50 EUR. Omit for no fee.
            subject: Email subject line; omit for the API default
            body: Email body content
            additional_emails: List of additional email addresses to send to
            is_send_to_company: Whether to send the copy to the company email (Owner)
            custom_client_email: Custom email address for the client (By default the email address of the client is used if it is set)
            
        Returns:
            Response from the send overdue reminder request
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        send_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/invoices/{invoice_id}/send-on-overdue/"
        )
        
        send_data = {
            "isSendToCompany": is_send_to_company
        }
        
        apply_invoice_options(send_data, subject=subject, body=body, fee=fee)

        if additional_emails:
            send_data["additionalEmails"] = additional_emails if additional_emails else []
        if custom_client_email:
            send_data["customClientEmail"] = custom_client_email
            
        return sent_or_nothing_sent(await api.arequest("POST", send_url, json_data=send_data))

    @mcp.tool(
        title="Link Transaction to Invoice",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
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
        Link a transaction to an invoice.
        
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

        return await api.arequest("POST", link_url, json_data=link_data)

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
            E-invoice XML data as xml_content
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
        response = await api.arequest("GET", xml_url)
        if "content" not in response:
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
        limit: Optional[int] = Field(default=100, ge=1, le=200),
        document_type: Optional[Literal["invoice", "quote", "delivery_note", "cancel", "credit_note"]] = None,
        page: int = Field(default=1, ge=1),
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
            limit: Invoices per page (default 100)
            page: Page number, starting at 1; the response's next tells whether more exist
            
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
        # The API paginates by page/page_size; "limit" was ignored, so at most
        # 20 invoices ever came back.
        params["page_size"] = limit or 100
        params["page"] = page
        if name:
            params["name"] = name
        if document_type:
            params["type"] = document_type
        
        result = await api.arequest("GET", invoices_url, params=params)
        return await _enrich_invoice_response(result)

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
