import logging
import os
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin

from norman_mcp.context import Context
from norman_mcp import config
from norman_mcp.security.utils import validate_file_path

logger = logging.getLogger(__name__)

def register_document_tools(mcp):
    """Register all document-related tools with the MCP server."""
    
    @mcp.tool()
    async def upload_bulk_attachments(
        ctx: Context,
        file_paths: List[str],
        cashflow_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Upload multiple file attachments in bulk.
        
        Args:
            file_paths: List of paths to files to upload
            cashflow_type: Optional cashflow type for the transactions (INCOME or EXPENSE)
            
        Returns:
            Response from the bulk upload request
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        # Validate cashflow_type
        if cashflow_type and cashflow_type not in ["INCOME", "EXPENSE"]:
            return {"error": "cashflow_type must be either 'INCOME' or 'EXPENSE'"}
            
        upload_url = urljoin(
            config.api_base_url,
            "api/v1/accounting/transactions/upload-documents/"
        )
        
        try:
            files = []
            valid_paths = []
            
            # Validate all file paths before proceeding
            for path in file_paths:
                if not validate_file_path(path):
                    logger.warning(f"Invalid or unsafe file path: {path}")
                    continue
                    
                if not os.path.exists(path):
                    logger.warning(f"File not found: {path}")
                    continue
                    
                valid_paths.append(path)
                
            if not valid_paths:
                return {"error": "No valid files found for upload"}
                
            # Open and prepare valid files
            for path in valid_paths:
                files.append(("files", open(path, "rb")))
                    
            data = {}
            if cashflow_type:
                data["cashflow_type"] = cashflow_type
                
            return api._make_request("POST", upload_url, json_data=data, files=files)
        except FileNotFoundError as e:
            return {"error": f"File not found: {str(e)}"}
        except PermissionError as e:
            return {"error": f"Permission denied when accessing file: {str(e)}"}
        except Exception as e:
            logger.error(f"Error uploading files: {str(e)}")
            return {"error": f"Error uploading files: {str(e)}"}

    @mcp.tool()
    async def list_attachments(
        ctx: Context,
        file_name: Optional[str] = None,
        linked: Optional[bool] = None,
        attachment_type: Optional[str] = None,
        description: Optional[str] = None,
        brand_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get list of attachments with optional filters.
        
        Args:
            file_name: Filter by file name (case insensitive partial match)
            linked: Filter by whether attachment is linked to transactions
            attachment_type: Filter by attachment type (invoice, receipt, contract, other)
            description: Filter by description (case insensitive partial match)
            brand_name: Filter by brand name (case insensitive partial match)
            
        Returns:
            List of attachments matching the filters
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
            
        attachments_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/attachments/"
        )
        
        params = {}
        if file_name:
            params["file_name"] = file_name
        if linked is not None:
            params["linked"] = linked
        if attachment_type:
            params["has_type"] = attachment_type
        if description:
            params["description"] = description
        if brand_name:
            params["brand_name"] = brand_name
            
        return api._make_request("GET", attachments_url, params=params)

    @mcp.tool()
    async def create_attachment(
        ctx: Context,
        file_path: str,
        transactions: Optional[List[str]] = None,
        attachment_type: Optional[str] = None,
        amount: Optional[float] = None,
        amount_exchanged: Optional[float] = None,
        attachment_number: Optional[str] = None,
        brand_name: Optional[str] = None,
        currency: str = "EUR",
        currency_exchanged: str = "EUR",
        description: Optional[str] = None,
        supplier_country: Optional[str] = None,
        value_date: Optional[str] = None,
        vat_sum_amount: Optional[float] = None,
        vat_sum_amount_exchanged: Optional[float] = None,
        vat_rate: Optional[int] = None,
        sale_type: Optional[str] = None,
        additional_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a new attachment.
        
        Args:
            file_path: Path to file to upload
            transactions: List of transaction IDs to link
            attachment_type: Type of attachment (invoice, receipt)
            amount: Amount related to attachment
            amount_exchanged: Exchanged amount in different currency
            attachment_number: Unique number for attachment
            brand_name: Brand name associated with attachment
            currency: Currency of amount (default EUR)
            currency_exchanged: Exchanged currency (default EUR)
            description: Description of attachment
            supplier_country: Country of supplier (DE, INSIDE_EU, OUTSIDE_EU)
            value_date: Date of value
            vat_sum_amount: VAT sum amount
            vat_sum_amount_exchanged: Exchanged VAT sum amount
            vat_rate: VAT rate percentage
            sale_type: Type of sale
            additional_metadata: Additional metadata for attachment
            
        Returns:
            Created attachment information
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        # Validate file path
        if not validate_file_path(file_path):
            return {"error": "Invalid or unsafe file path"}
            
        # Validate attachment_type    
        if attachment_type and attachment_type not in ["invoice", "receipt", "contract", "other"]:
            return {"error": "attachment_type must be one of: invoice, receipt, contract, other"}
        
        # Validate supplier_country
        if supplier_country and supplier_country not in ["DE", "INSIDE_EU", "OUTSIDE_EU"]:
            return {"error": "supplier_country must be one of: DE, INSIDE_EU, OUTSIDE_EU"}
            
        # Validate sale_type
        if sale_type and sale_type not in ["GOODS", "SERVICES"]:
            return {"error": "sale_type must be one of: GOODS, SERVICES"}
            
        attachments_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/attachments/"
        )
        
        try:
            # Check if file exists and is readable
            if not os.path.exists(file_path):
                return {"error": f"File not found: {file_path}"}
                
            if not os.access(file_path, os.R_OK):
                return {"error": f"Permission denied when accessing file: {file_path}"}
                
            files = {
                "file": open(file_path, "rb")
            }
                
            data = {}
            if transactions:
                data["transactions"] = transactions
            if attachment_type:
                data["attachment_type"] = attachment_type
            if amount is not None:
                data["amount"] = amount
            if amount_exchanged is not None:
                data["amount_exchanged"] = amount_exchanged
            if attachment_number:
                data["attachment_number"] = attachment_number
            if brand_name:
                data["brand_name"] = brand_name
            if currency:
                data["currency"] = currency
            if currency_exchanged:
                data["currency_exchanged"] = currency_exchanged
            if description:
                data["description"] = description
            if supplier_country:
                data["supplier_country"] = supplier_country
            if value_date:
                data["value_date"] = value_date
            if vat_sum_amount is not None:
                data["vat_sum_amount"] = vat_sum_amount
            if vat_sum_amount_exchanged is not None:
                data["vat_sum_amount_exchanged"] = vat_sum_amount_exchanged
            if vat_rate is not None:
                data["vat_rate"] = vat_rate
            if sale_type:
                data["sale_type"] = sale_type
            if additional_metadata:
                data["additional_metadata"] = additional_metadata
                
            return api._make_request("POST", attachments_url, json_data=data, files=files)
        except FileNotFoundError:
            return {"error": f"File not found: {file_path}"}
        except PermissionError:
            return {"error": f"Permission denied when accessing file: {file_path}"}
        except Exception as e:
            logger.error(f"Error uploading file: {str(e)}")
            return {"error": f"Error uploading file: {str(e)}"}

    @mcp.tool()
    async def link_attachment_transaction(
        ctx: Context,
        attachment_id: str,
        transaction_id: str
    ) -> Dict[str, Any]:
        """
        Link a transaction to an attachment.
        
        Args:
            attachment_id: ID of the attachment
            transaction_id: ID of the transaction to link
            
        Returns:
            Response from the link transaction request
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
            
        link_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/attachments/{attachment_id}/link-transaction/"
        )
        
        link_data = {
            "transaction": transaction_id
        }
        
        return api._make_request("POST", link_url, json_data=link_data) 