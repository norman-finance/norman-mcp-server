from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
from datetime import datetime, timedelta

def register_invoice_tools(mcp):
    """Register all invoice-related tools with the MCP server."""
    
    @mcp.tool()
    async def create_invoice(
        ctx: Context,
        client_id: str,
        items: list[dict],
        invoice_number: Optional[str] = None,
        issued: Optional[str] = None,
        due_to: Optional[str] = None,
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
        color_schema: str = "#FFFFFF",
        font: str = "Plus Jakarta Sans",
        is_to_send: bool = False,
        mailing_data: Optional[Dict[str, str]] = None,
        settings_on_overdue: Optional[Dict[str, Any]] = None,
        service_start_date: Optional[str] = None,
        service_end_date: Optional[str] = None,
        delivery_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new invoice."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        # Use current date if not provided
        if not issued:
            issued = datetime.now().strftime("%Y-%m-%d")
        
        invoices_url = urljoin(
            config.api_base_url, 
            f"api/v1/companies/{company_id}/invoices/"
        )
        
        # Get next invoice number if not provided
        if not invoice_number:
            next_invoice_url = urljoin(
                config.api_base_url, 
                f"api/v1/companies/{company_id}/invoices/next-invoice-number/"
            )
            next_invoice_data = api._make_request("GET", next_invoice_url)
            invoice_number = next_invoice_data.get("nextInvoiceNumber")
        
        # Prepare invoice data
        invoice_data = {
            "client": client_id,
            "invoiceNumber": invoice_number,
            "issued": issued,
            "invoicedItems": items,
            "currency": currency,
            "language": language,
            "invoiceType": invoice_type,
            "isVatIncluded": is_vat_included,
            "createQr": create_qr,
            "isToSend": is_to_send,
            "type": "invoice",
            "companyId": company_id,
            "companyEmail": config.NORMAN_EMAIL
        }
        
        # Add optional fields if provided
        invoice_data["dueTo"] = due_to if due_to else (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        invoice_data["paymentTerms"] = payment_terms if payment_terms else ""
        invoice_data["notes"] = notes if notes else ""
        invoice_data["bankName"] = bank_name if bank_name else ""
        invoice_data["iban"] = iban if iban else ""
        invoice_data["bic"] = bic if bic else ""
        invoice_data["colorSchema"] = color_schema
        invoice_data["font"] = font
        if mailing_data and is_to_send:
            invoice_data["mailingData"] = mailing_data
        if settings_on_overdue:
            invoice_data["settingsOnOverdue"] = settings_on_overdue
        else:
            invoice_data["settingsOnOverdue"] = {"isToAutosendNotification": False}
        if invoice_type == "SERVICES":
            invoice_data["serviceStartDate"] = service_start_date if service_start_date else datetime.now().strftime("%Y-%m-%d")
            invoice_data["serviceEndDate"] = service_end_date if service_end_date else (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        if invoice_type == "GOODS":
            invoice_data["deliveryDate"] = delivery_date if delivery_date else datetime.now().strftime("%Y-%m-%d")

        return api._make_request("POST", invoices_url, json_data=invoice_data)

    @mcp.tool()
    async def create_recurring_invoice(
        ctx: Context,
        client_id: str,
        items: list[dict],
        frequency_type: str,
        frequency_unit: int,
        starts_from_date: str,
        ends_on_date: Optional[str] = None,
        ends_on_invoice_count: Optional[int] = None,
        invoice_number: Optional[str] = None,
        issued: Optional[str] = None,
        due_to: Optional[str] = None,
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
        color_schema: str = "#FFFFFF",
        font: str = "Plus Jakarta Sans",
        is_to_send: bool = False,
        settings_on_overdue: Optional[Dict[str, Any]] = None,
        service_start_date: Optional[str] = None,
        service_end_date: Optional[str] = None,
        delivery_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a recurring invoice."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}

        if not issued:
            issued = starts_from_date

        recurring_invoices_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/recurring-invoices/"
        )

        # Get next invoice number if not provided
        if not invoice_number:
            next_invoice_url = urljoin(
                config.api_base_url,
                f"api/v1/companies/{company_id}/invoices/next-invoice-number/"
            )
            next_invoice_data = api._make_request("GET", next_invoice_url)
            invoice_number = next_invoice_data.get("nextInvoiceNumber")

        # Prepare recurring invoice data
        invoice_data = {
            "client": client_id,
            "invoiceNumber": invoice_number,
            "recurringNumber": invoice_number,
            "issued": issued,
            "invoicedItems": items,
            "currency": currency,
            "language": language,
            "invoiceType": invoice_type,
            "isVatIncluded": is_vat_included,
            "createQr": create_qr,
            "isToSend": is_to_send,
            "isRecurring": True,
            "frequencyType": frequency_type,
            "frequencyUnit": frequency_unit,
            "startsFromDate": starts_from_date,
            "type": "invoice",
            "companyId": company_id,
            "companyEmail": config.NORMAN_EMAIL
        }

        # Add conditional end parameters
        if ends_on_date:
            invoice_data["endsOnDate"] = ends_on_date
        if ends_on_invoice_count:
            invoice_data["endsOnInvoiceCount"] = ends_on_invoice_count
        
        if not ends_on_date and not ends_on_invoice_count:
            invoice_data["endsOnInvoiceCount"] = 3

        # Add optional fields
        invoice_data["dueTo"] = due_to if due_to else (datetime.strptime(issued, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        invoice_data["paymentTerms"] = payment_terms if payment_terms else ""
        invoice_data["notes"] = notes if notes else ""
        invoice_data["bankName"] = bank_name if bank_name else ""
        invoice_data["iban"] = iban if iban else ""
        invoice_data["bic"] = bic if bic else ""
        invoice_data["colorSchema"] = color_schema
        invoice_data["font"] = font
        
        if settings_on_overdue:
            invoice_data["settingsOnOverdue"] = settings_on_overdue
        else:
            invoice_data["settingsOnOverdue"] = {"isToAutosendNotification": False}

        if invoice_type == "SERVICES":
            invoice_data["serviceStartDate"] = service_start_date if service_start_date else starts_from_date
            invoice_data["serviceEndDate"] = service_end_date if service_end_date else (datetime.strptime(starts_from_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        if invoice_type == "GOODS":
            invoice_data["deliveryDate"] = delivery_date if delivery_date else starts_from_date

        return api._make_request("POST", recurring_invoices_url, json_data=invoice_data)

    @mcp.tool()
    async def get_invoice(
        ctx: Context,
        invoice_id: str
    ) -> Dict[str, Any]:
        """Get detailed information about a specific invoice."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        invoice_url = urljoin(
            config.api_base_url, 
            f"api/v1/companies/{company_id}/invoices/{invoice_id}/"
        )
        
        return api._make_request("GET", invoice_url)

    @mcp.tool()
    async def send_invoice(
        ctx: Context,
        invoice_id: str,
        subject: str,
        body: str,
        additional_emails: Optional[List[str]] = None,
        is_send_to_company: bool = False,
        custom_client_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send an invoice via email."""
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
            
        return api._make_request("POST", send_url, json_data=send_data)

    @mcp.tool()
    async def send_invoice_overdue_reminder(
        ctx: Context,
        invoice_id: str,
        subject: str,
        body: str,
        additional_emails: Optional[List[str]] = None,
        is_send_to_company: bool = False,
        custom_client_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send an overdue payment reminder for an invoice via email."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        send_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/invoices/{invoice_id}/send-on-overdue/"
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
            
        return api._make_request("POST", send_url, json_data=send_data)

    @mcp.tool() 
    async def link_transaction(
        ctx: Context,
        invoice_id: str,
        transaction_id: str
    ) -> Dict[str, Any]:
        """Link a transaction to an invoice."""
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
        
        return api._make_request("POST", link_url, json_data=link_data)

    @mcp.tool()
    async def get_einvoice_xml(
        ctx: Context,
        invoice_id: str
    ) -> Dict[str, Any]:
        """Get the e-invoice XML for a specific invoice."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        xml_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/invoices/{invoice_id}/xml/"
        )

        try:
            response = requests.get(
                xml_url,
                headers={"Authorization": f"Bearer {api.access_token}"},
                timeout=config.NORMAN_API_TIMEOUT
            )
            response.raise_for_status()
            
            # Return the XML content as a string
            return {"xml_content": response.text}
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get e-invoice XML: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return {"error": f"Failed to get e-invoice XML: {str(e)}"}

    @mcp.tool()
    async def list_invoices(
        ctx: Context,
        status: Optional[str] = None,
        name: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: Optional[int] = 100
    ) -> Dict[str, Any]:
        """List invoices with optional filtering."""
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
        
        return api._make_request("GET", invoices_url, params=params) 