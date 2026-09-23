import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urljoin

from mcp.types import ToolAnnotations

from norman_mcp import config
from norman_mcp.context import Context
from norman_mcp.tools.invoice_schemas import (
    ClientData,
    CompanyData,
    DocumentDesign,
    InvoiceItem,
    MailingData,
    OverdueSettings,
    apply_invoice_options,
    item_payloads,
)

OFFER_TYPE = "quote"
logger = logging.getLogger(__name__)


def _enrich_offer_response(data: dict, api=None, company_id: Optional[str] = None) -> dict:
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
                logger.debug("Could not fetch presigned PDF URL for offer %s", pid)

    if data.get("publicId"):
        _enrich_single(data)

    if "results" in data and isinstance(data["results"], list):
        for item in data["results"]:
            if isinstance(item, dict):
                _enrich_single(item)

    return data


def _get_api_and_company(ctx: Context):
    api = ctx.request_context.lifespan_context["api"]
    company_id = api.company_id

    if not company_id:
        return api, None, {"error": "No company available. Please authenticate first."}

    return api, company_id, None


def register_offer_tools(mcp):
    """Register all offer/quote-related tools with the MCP server."""

    @mcp.tool(
        title="Create Offer",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def create_offer(
        ctx: Context,
        client_id: str | None,
        items: list[InvoiceItem],
        offer_number: Optional[str] = None,
        issued: Optional[str] = None,
        valid_until: Optional[str] = None,
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
        service_start_date: Optional[str] = None,
        service_end_date: Optional[str] = None,
        delivery_date: Optional[str] = None,
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
        status: Literal["draft", "saved"] | None = None,
        payment_status: str | None = None,
        payment_date: str | None = None,
        bank_account_pk: str | None = None,
        is_to_create_transaction: bool | None = None,
        paid_amount: int | None = None,
        online_payment_enabled: bool | None = None,
        source_contract_id: str | None = None,
        settings_on_overdue: OverdueSettings | None = None,
    ) -> Dict[str, Any]:
        """
        Create a new offer/quote, with the same line, design, payment and sender options as create_invoice.
        Omit document_design, colour and font to inherit company branding. The API enforces paid template access.
        Use update_invoice to edit an existing quote.

        Args:
            client_id: ID of the client for the offer
            items: List of offer items. Example:
                [{"name": "Software Development", "quantity": 3, "rate": 30000, "vatRate": 19}]
                VAT rates might be 0, 7, 19. Rate is in cents.
            offer_number: Optional offer number (will be auto-generated if not provided)
            issued: Issue date in YYYY-MM-DD format
            valid_until: Offer validity date in YYYY-MM-DD format (defaults to 30 days from today)
            currency: Offer currency (EUR, USD); omit for the company's own currency.
            payment_terms: Payment terms text
            notes: Additional notes
            language: Offer language (en, de)
            invoice_type: Type of offer (SERVICES, GOODS)
            is_vat_included: Whether prices include VAT
            bank_name: Name of the bank
            iban: IBAN for payments
            bic: BIC/SWIFT code
            create_qr: Whether to create payment QR code (only if BIC and IBAN provided)
            color_schema: Offer colour (hex code); omit to inherit saved branding.
            font: Offer font; omit to inherit the saved font.
            is_to_send: Whether to send the offer automatically to client
            mailing_data: Email data if is_to_send is True
            service_start_date: Service period start date (YYYY-MM-DD)
            service_end_date: Service period end date (YYYY-MM-DD)
            delivery_date: Delivery date for goods (YYYY-MM-DD)
            status: "draft" keeps an editable draft that is never emailed. Omit or use
                "saved" to issue it.

        Returns:
            Information about the created offer. Use downloadUrl for a direct temporary PDF
            download link when available.
        """
        api, company_id, error = _get_api_and_company(ctx)
        if error:
            return error

        if not issued:
            issued = datetime.now().strftime("%Y-%m-%d")

        offers_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/invoices/",
        )

        if not offer_number:
            next_offer_url = urljoin(
                config.api_base_url,
                f"api/v1/companies/{company_id}/invoices/next-invoice-number/",
            )
            next_offer_data = api._make_request(
                "GET",
                next_offer_url,
                params={"type": OFFER_TYPE},
            )
            offer_number = (
                next_offer_data.get("nextInvoiceNumber")
                or next_offer_data.get("next_invoice_number")
            )
            if not offer_number:
                return {
                    "error": "Could not generate offer number",
                    "detail": next_offer_data,
                }

        offer_data = {
            "client": client_id,
            "invoiceNumber": offer_number,
            "issued": issued,
            "invoicedItems": item_payloads(items),
            "language": language,
            "invoiceType": invoice_type,
            "isVatIncluded": is_vat_included,
            "createQr": create_qr,
            "isToSend": is_to_send,
            "type": OFFER_TYPE,
            "dueTo": valid_until
            if valid_until
            else (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            "paymentTerms": payment_terms if payment_terms else "",
            "notes": notes if notes else "",
            "bankName": bank_name if bank_name else "",
            "iban": iban if iban else "",
            "bic": bic if bic else "",
        }

        if currency is not None:
            offer_data["currency"] = currency
        if invoice_type == "SERVICES":
            offer_data["serviceStartDate"] = (
                service_start_date
                if service_start_date
                else datetime.now().strftime("%Y-%m-%d")
            )
            offer_data["serviceEndDate"] = (
                service_end_date
                if service_end_date
                else (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
            )
        if invoice_type == "GOODS":
            offer_data["deliveryDate"] = (
                delivery_date if delivery_date else datetime.now().strftime("%Y-%m-%d")
            )

        apply_invoice_options(
            offer_data,
            source_contract=source_contract_id,
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

        result = api._make_request("POST", offers_url, json_data=offer_data)
        return _enrich_offer_response(result, api=api, company_id=company_id)

    @mcp.tool(
        title="List Offers",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_offers(
        ctx: Context,
        status: Optional[Literal["draft", "saved", "sent", "approved", "invoiced"]] = None,
        name: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: Optional[int] = 100,
    ) -> Dict[str, Any]:
        """
        List offers/quotes with optional filtering.

        Args:
            status: Filter by offer status. "invoiced" means converted to an invoice.
            name: Filter by client name
            from_date: Only offers issued on or after this date (YYYY-MM-DD)
            to_date: Only offers issued on or before this date (YYYY-MM-DD)
            limit: Maximum number of offers to return (default 100)

        Returns:
            List of offers matching the criteria
        """
        api, company_id, error = _get_api_and_company(ctx)
        if error:
            return error

        offers_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/invoices/",
        )

        params: Dict[str, Any] = {"type": OFFER_TYPE}
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

        result = api._make_request("GET", offers_url, params=params)
        return _enrich_offer_response(result, api=api, company_id=company_id)

    @mcp.tool(
        title="Get Offer Details",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_offer(
        ctx: Context,
        offer_id: str,
    ) -> Dict[str, Any]:
        """
        Get detailed information about a specific offer/quote.

        Args:
            offer_id: ID of the offer to retrieve

        Returns:
            Detailed offer information
        """
        api, company_id, error = _get_api_and_company(ctx)
        if error:
            return error

        offer_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/invoices/{offer_id}/",
        )

        result = api._make_request("GET", offer_url)
        return _enrich_offer_response(result, api=api, company_id=company_id)

    @mcp.tool(
        title="Send Offer via Email",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def send_offer(
        ctx: Context,
        offer_id: str,
        subject: str,
        body: str,
        additional_emails: Optional[List[str]] = None,
        is_send_to_company: bool = False,
        custom_client_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send an offer/quote via email.

        Args:
            offer_id: ID of the offer to send
            subject: Email subject line
            body: Email body content
            additional_emails: List of additional email addresses to send to
            is_send_to_company: Whether to send a copy to the company email
            custom_client_email: Custom client email address

        Returns:
            Response from the send offer request
        """
        api, company_id, error = _get_api_and_company(ctx)
        if error:
            return error

        send_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/invoices/{offer_id}/send/",
        )

        send_data = {
            "subject": subject,
            "body": body,
            "isSendToCompany": is_send_to_company,
        }

        if additional_emails:
            send_data["additionalEmails"] = additional_emails
        if custom_client_email:
            send_data["customClientEmail"] = custom_client_email

        return api._make_request("POST", send_url, json_data=send_data)

    @mcp.tool(
        title="Convert Offer to Invoice",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def convert_offer_to_invoice(
        ctx: Context,
        offer_id: str,
    ) -> Dict[str, Any]:
        """
        Convert a quote into a draft invoice.

        The quote stays, with the status "invoiced", and the invoice refers to it
        (sourceDocument). Issue the invoice with update_invoice status "saved"
        before sending it.

        Args:
            offer_id: ID of the quote to convert

        Returns:
            The new draft invoice
        """
        api, company_id, error = _get_api_and_company(ctx)
        if error:
            return error

        convert_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/invoices/{offer_id}/convert-to-invoice/",
        )

        result = api._make_request("POST", convert_url)
        return _enrich_offer_response(result, api=api, company_id=company_id)
