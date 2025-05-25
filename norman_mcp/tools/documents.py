import logging
import os
import re
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
import tempfile
import requests
from urllib.parse import urlparse
from pydantic import Field

from norman_mcp.context import Context
from norman_mcp import config
from norman_mcp.security.utils import validate_file_path, validate_input

logger = logging.getLogger(__name__)

def is_url(path: str) -> bool:
    """Check if the given path is a URL."""
    try:
        result = urlparse(path)
        return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
    except Exception:
        return False

def download_file(url: str) -> Optional[str]:
    """Download a file from URL to a temporary location and return its path."""
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        # Extract filename from URL or Content-Disposition header
        filename = None
        
        if "Content-Disposition" in response.headers:
            # Try to get filename from Content-Disposition header
            content_disposition = response.headers["Content-Disposition"]
            match = re.search(r'filename="?([^"]+)"?', content_disposition)
            if match:
                filename = match.group(1)
        
        # If no filename found in header, extract from URL
        if not filename:
            url_path = urlparse(url).path
            filename = os.path.basename(url_path) or "downloaded_file"
        
        # Create a temporary file
        temp_dir = tempfile.mkdtemp(prefix="norman_")
        temp_path = os.path.join(temp_dir, filename)
        
        # Write the file
        with open(temp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        return temp_path
    except Exception as e:
        logger.error(f"Error downloading file from {url}: {str(e)}")
        return None

def validate_file_path(file_path: str) -> bool:
    """Validate that a file path is safe to use."""
    # Allow URLs as they'll be handled separately
    if is_url(file_path):
        return True
        
    # Check for local file path safety
    file_path = os.path.abspath(file_path)
    is_path_traversal = ".." in file_path or "~" in file_path
    return not is_path_traversal

def validate_input(input_str: str) -> str:
    """Validate that input string doesn't contain malicious content."""
    if not input_str:
        return ""
    # Remove any potential script or command injection characters
    return re.sub(r'[;<>&|]', '', input_str)

def register_document_tools(mcp):
    """Register all document-related tools with the MCP server."""
    
    @mcp.tool()
    async def upload_bulk_attachments(
        ctx: Context,
        file_paths: List[str] = Field(description="List of paths or URLs to files to upload"),
        cashflow_type: Optional[str] = Field(description="Optional cashflow type for the transactions (INCOME or EXPENSE). If not provided, then try to detect it from the file")
    ) -> Dict[str, Any]:
        """
        Upload multiple file attachments in bulk.
        
        Args:
            file_paths: List of paths or URLs to files to upload
            cashflow_type: Optional cashflow type for the transactions (INCOME or EXPENSE). If not provided, then try to detect it from the file
            
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
        
        temp_files = []  # Track temp files for cleanup
        opened_files = []  # Track opened file handles for cleanup
        
        try:
            files = []
            valid_paths = []
            
            # Process all file paths before proceeding
            for path in file_paths:
                if not validate_file_path(path):
                    logger.warning(f"Invalid or unsafe file path: {path}")
                    continue
                
                actual_path = path
                
                # Handle URLs by downloading them first
                if is_url(path):
                    logger.info(f"Downloading file from URL: {path}")
                    downloaded_path = download_file(path)
                    if not downloaded_path:
                        logger.warning(f"Failed to download file from URL: {path}")
                        continue
                    actual_path = downloaded_path
                    temp_files.append(actual_path)
                    logger.info(f"File downloaded to: {actual_path}")
                
                # Validate the file exists and is accessible
                if not os.path.exists(actual_path):
                    logger.warning(f"File not found: {actual_path}")
                    continue
                
                if not os.access(actual_path, os.R_OK):
                    logger.warning(f"Permission denied when accessing file: {actual_path}")
                    continue
                    
                valid_paths.append(actual_path)
                
            if not valid_paths:
                return {"error": "No valid files found for upload"}
                
            # Open and prepare valid files
            for path in valid_paths:
                file_handle = open(path, "rb")
                opened_files.append(file_handle)
                files.append(("files", file_handle))
                    
            data = {}
            if cashflow_type:
                data["cashflow_type"] = cashflow_type
                
            response = api._make_request("POST", upload_url, json_data=data, files=files)
            
            # Close all opened file handles
            for file_handle in opened_files:
                file_handle.close()
                
            # Clean up temporary files
            for temp_file in temp_files:
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                        os.rmdir(os.path.dirname(temp_file))
                        logger.info(f"Removed temporary file: {temp_file}")
                except Exception as e:
                    logger.warning(f"Failed to remove temporary file {temp_file}: {str(e)}")
                    
            return response
            
        except FileNotFoundError as e:
            return {"error": f"File not found: {str(e)}"}
        except PermissionError as e:
            return {"error": f"Permission denied when accessing file: {str(e)}"}
        except Exception as e:
            logger.error(f"Error uploading files: {str(e)}")
            return {"error": f"Error uploading files: {str(e)}"}
        finally:
            # Ensure files are closed and temp files are cleaned up in case of exceptions
            for file_handle in opened_files:
                try:
                    file_handle.close()
                except Exception:
                    pass
                    
            for temp_file in temp_files:
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                        os.rmdir(os.path.dirname(temp_file))
                except Exception:
                    pass

    @mcp.tool()
    async def list_attachments(
        ctx: Context,
        file_name: Optional[str] = Field(description="Filter by file name (case insensitive partial match)"),
        linked: Optional[bool] = Field(description="Filter by whether attachment is linked to transactions"),
        attachment_type: Optional[str] = Field(description="Filter by attachment type (invoice, receipt, contract, other)"),
        description: Optional[str] = Field(description="Filter by description (case insensitive partial match)"),
        brand_name: Optional[str] = Field(description="Filter by brand name (case insensitive partial match)")
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
            List of attachments matching the filters. Use field "file" that contains direct links to the file in the response and make the link clickable along with the other fields.
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
        file_path: str = Field(description="Path or URL to file to upload"),
        transactions: Optional[List[str]] = Field(description="List of transaction IDs to link"),
        attachment_type: Optional[str] = Field(description="Type of attachment (invoice, receipt)"),
        amount: Optional[float] = Field(description="Amount related to attachment"),
        amount_exchanged: Optional[float] = Field(description="Exchanged amount in different currency"),
        attachment_number: Optional[str] = Field(description="Unique number for attachment"),
        brand_name: Optional[str] = Field(description="Brand name associated with attachment"),
        currency: str = "EUR",
        currency_exchanged: str = "EUR",
        description: Optional[str] = Field(description="Description of attachment"),
        supplier_country: Optional[str] = Field(description="Country of supplier (DE, INSIDE_EU, OUTSIDE_EU)"),
        value_date: Optional[str] = Field(description="Date of value"),
        vat_sum_amount: Optional[float] = Field(description="VAT sum amount"),
        vat_sum_amount_exchanged: Optional[float] = Field(description="Exchanged VAT sum amount"),
        vat_rate: Optional[int] = Field(description="VAT rate percentage"),
        sale_type: Optional[str] = Field(description="Type of sale"),
        additional_metadata: Optional[Dict[str, Any]] = Field(description="Additional metadata for attachment")
    ) -> Dict[str, Any]:
        """
        Create a new attachment.
        
        Args:
            file_path: Path to file or URL to upload
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
            temp_file_path = None
            actual_file_path = file_path
            
            # Check if file_path is a URL and download it if needed
            if is_url(file_path):
                logger.info(f"Downloading file from URL: {file_path}")
                temp_file_path = download_file(file_path)
                if not temp_file_path:
                    return {"error": f"Failed to download file from URL: {file_path}"}
                actual_file_path = temp_file_path
                logger.info(f"File downloaded to: {actual_file_path}")
            
            # Check if file exists and is readable
            if not os.path.exists(actual_file_path):
                return {"error": f"File not found: {actual_file_path}"}
                
            if not os.access(actual_file_path, os.R_OK):
                return {"error": f"Permission denied when accessing file: {actual_file_path}"}
                
            files = {
                "file": open(actual_file_path, "rb")
            }
                
            data = {}
            if transactions:
            # Validate each transaction ID
                data["transactions"] = [tx for tx in transactions if validate_input(tx)]
            if attachment_type:
                data["attachment_type"] = attachment_type
            if amount is not None:
                data["amount"] = amount
            if amount_exchanged is not None:
                data["amount_exchanged"] = amount_exchanged
            if attachment_number:
                data["attachment_number"] = validate_input(attachment_number)
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
                # Sanitize the metadata
                sanitized_metadata = {}
                for key, value in additional_metadata.items():
                    if isinstance(value, str):
                        sanitized_metadata[validate_input(key)] = validate_input(value)
                    else:
                        sanitized_metadata[validate_input(key)] = value
                data["additional_metadata"] = sanitized_metadata
                
            response = api._make_request("POST", attachments_url, json_data=data, files=files)
            
            # Close the file handle
            files["file"].close()
            
            # Clean up temporary file if we downloaded one
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                    os.rmdir(os.path.dirname(temp_file_path))
                    logger.info(f"Removed temporary file: {temp_file_path}")
                except Exception as e:
                    logger.warning(f"Failed to remove temporary file: {str(e)}")
                    
            return response
        except FileNotFoundError:
            return {"error": f"File not found: {file_path}"}
        except PermissionError:
            return {"error": f"Permission denied when accessing file: {file_path}"}
        except Exception as e:
            # Clean up temporary file if there was an error
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                    os.rmdir(os.path.dirname(temp_file_path))
                except Exception:
                    pass
            logger.error(f"Error uploading file: {str(e)}")
            return {"error": f"Error uploading file: {str(e)}"}

    @mcp.tool()
    async def link_attachment_transaction(
        ctx: Context,
        attachment_id: str = Field(description="ID of the attachment"),
        transaction_id: str = Field(description="ID of the transaction to link")
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