import base64
import json
import logging
import os
import re
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
import tempfile
import requests
from urllib.parse import urlparse
from pydantic import Field

from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from norman_mcp.context import Context
from norman_mcp import config
from norman_mcp.security.utils import validate_file_path, validate_input

logger = logging.getLogger(__name__)


def _enrich_attachment_download_urls(data: dict, api=None, company_id: str | None = None) -> dict:
    """Add presigned downloadUrl for attachment files."""
    if not isinstance(data, dict):
        return data

    def _enrich_single(item: dict) -> None:
        pk = item.get("publicId") or item.get("pk")
        if pk and item.get("file") and api and company_id:
            try:
                dl_endpoint = urljoin(
                    config.api_base_url,
                    f"api/v1/companies/{company_id}/attachments/{pk}/download/",
                )
                dl_resp = api._make_request("GET", dl_endpoint)
                if dl_resp.get("url"):
                    item["downloadUrl"] = dl_resp["url"]
            except Exception:
                pass

    if data.get("publicId") or data.get("pk"):
        _enrich_single(data)
    if "results" in data and isinstance(data["results"], list):
        for item in data["results"]:
            if isinstance(item, dict):
                _enrich_single(item)
    return data


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

def _strip_base64_prefix(raw: str) -> str:
    """Remove data-URI prefix (e.g. 'data:application/pdf;base64,') if present."""
    if raw.startswith("data:") and "," in raw:
        return raw.split(",", 1)[1]
    return raw


def save_base64_to_temp(content_b64: str, file_name: str) -> Optional[str]:
    """Decode base64 content and write to a temporary file. Returns the path."""
    try:
        cleaned = _strip_base64_prefix(content_b64)
        cleaned = re.sub(r"\s+", "", cleaned)
        data = base64.b64decode(cleaned, validate=True)
        if len(data) == 0:
            logger.error("Base64 decoded to empty content")
            return None
        temp_dir = tempfile.mkdtemp(prefix="norman_")
        temp_path = os.path.join(temp_dir, file_name)
        with open(temp_path, "wb") as f:
            f.write(data)
        logger.info(f"Saved base64 file ({len(data)} bytes) to {temp_path}")
        return temp_path
    except base64.binascii.Error as e:
        logger.error(f"Invalid base64 content: {e}")
        return None
    except Exception as e:
        logger.error(f"Error decoding base64 content: {e}")
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

    @mcp.tool(
        title="Request File Upload URL",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def request_file_upload(
        ctx: Context,
    ) -> Dict[str, Any]:
        """
        Get the URL for uploading a file directly to the MCP server.

        Call this BEFORE create_attachment when the user wants to attach a
        file (image, PDF, receipt) but the file has no public URL.  The
        returned upload_url accepts a multipart POST with a 'file' field.
        After uploading, pass the returned file_ref to create_attachment.

        This avoids encoding large files as base64 (which would exceed the
        LLM context window).
        """
        from norman_mcp.config.settings import config as app_config
        public_url = os.environ.get(
            "NORMAN_MCP_PUBLIC_URL", "https://mcp.norman.finance"
        )
        upload_url = f"{public_url.rstrip('/')}/files/upload"

        return {
            "upload_url": upload_url,
            "method": "POST",
            "content_type": "multipart/form-data",
            "field_name": "file",
            "max_size_mb": 50,
            "expires_in_seconds": 1800,
            "instructions": (
                "Upload the file with: "
                f"curl -X POST {upload_url} -F file=@/path/to/file.pdf "
                "— then pass the returned file_ref to create_attachment."
            ),
        }

    @mcp.tool(
        title="Upload Bulk Attachments",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def upload_bulk_attachments(
        ctx: Context,
        file_urls: Optional[List[str]] = Field(default=None, description="BEST OPTION: List of HTTP(S) URLs. The server downloads each file directly — nothing goes through the LLM context."),
        file_refs: Optional[List[str]] = Field(default=None, description="List of file_ref tokens from prior POST /files/upload calls."),
        files_base64: Optional[List[Dict[str, str]]] = Field(default=None, description="LAST RESORT — only for tiny files (<50 KB each). Each item: {\"file_name\": \"receipt.pdf\", \"content\": \"<base64>\"}. Do NOT use for images or PDFs."),
        file_paths: Optional[List[str]] = Field(default=None, description="Deprecated alias for file_urls."),
        cashflow_type: Optional[str] = Field(description="Optional cashflow type for the transactions (INCOME or EXPENSE). If not provided, then try to detect it from the file")
    ) -> Dict[str, Any]:
        """
        Upload multiple file attachments in bulk.

        Priority: file_urls > file_refs > files_base64.
        Do NOT base64-encode images or PDFs — it will exceed the context window.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        if not file_urls and not file_refs and not files_base64 and not file_paths:
            return {"error": "Provide file_urls (preferred), file_refs, or files_base64."}

        if cashflow_type and cashflow_type not in ["INCOME", "EXPENSE"]:
            return {"error": "cashflow_type must be either 'INCOME' or 'EXPENSE'"}

        upload_url = urljoin(
            config.api_base_url,
            "api/v1/accounting/transactions/upload-documents/"
        )

        temp_files = []
        opened_files = []

        try:
            files = []
            valid_paths = []

            # Priority 1: file_urls
            all_urls = list(file_urls or []) + [p for p in (file_paths or []) if is_url(p)]
            for url in all_urls:
                if not is_url(url):
                    logger.warning("Skipping non-URL: %s", url)
                    continue
                downloaded = download_file(url)
                if downloaded:
                    valid_paths.append(downloaded)
                    temp_files.append(downloaded)
                else:
                    logger.warning("Failed to download: %s", url)

            # Priority 2: file_refs
            if file_refs:
                from norman_mcp.files.upload import resolve_ref
                for ref in file_refs:
                    path = resolve_ref(ref)
                    if path:
                        valid_paths.append(path)
                    else:
                        logger.warning("file_ref not found or expired: %s", ref)

            # Priority 3: base64
            if files_base64:
                for item in files_base64:
                    name = item.get("file_name", "upload")
                    content = item.get("content", "")
                    if not content:
                        continue
                    tmp = save_base64_to_temp(content, name)
                    if tmp:
                        valid_paths.append(tmp)
                        temp_files.append(tmp)
                
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

    @mcp.tool(
        title="List Attachments",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
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
            List of attachments matching the filters. Use downloadUrl for direct temporary file download links.
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
            
        result = api._make_request("GET", attachments_url, params=params)
        return _enrich_attachment_download_urls(result, api=api, company_id=company_id)

    @mcp.tool(
        title="Create Attachment",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def create_attachment(
        ctx: Context,
        file_url: Optional[str] = Field(default=None, description="BEST OPTION: HTTP(S) URL to a publicly accessible file. The server downloads it directly — nothing goes through the LLM context. Use this whenever the file has a URL."),
        file_ref: Optional[str] = Field(default=None, description="Reference token from a prior POST /files/upload call. Use when the client uploaded the file directly to the MCP server."),
        file_content_base64: Optional[str] = Field(default=None, description="LAST RESORT — only for tiny files (<50 KB). Do NOT use for images, PDFs, or scanned documents — the base64 string will exceed the context window. Prefer file_url or file_ref."),
        file_name: Optional[str] = Field(default=None, description="Original filename with extension (e.g. 'invoice.pdf'). Required when using file_content_base64."),
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
        Create a new attachment with a file.

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

        Priority order for providing the file:
        1. file_url   — URL to the file (server downloads it, nothing in context)
        2. file_ref   — token from POST /files/upload (direct binary upload)
        3. file_content_base64 — ONLY for very small files (<50 KB)

        IMPORTANT: Do NOT base64-encode images, PDFs or any large file — it will
        exceed the LLM context window. Use file_url or ask the user to upload
        the file through Norman's web app at app.norman.finance instead.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id

        if not company_id:
            return {"error": "No company available. Please authenticate first."}

        if not file_url and not file_ref and not file_content_base64:
            return {
                "error": "Provide one of: file_url (preferred), file_ref, "
                "or file_content_base64 (small files only)."
            }

        if file_content_base64 and not file_name:
            return {"error": "file_name is required when using file_content_base64"}

        if attachment_type and attachment_type not in ["invoice", "receipt", "contract", "other"]:
            return {"error": "attachment_type must be one of: invoice, receipt, contract, other"}

        if supplier_country and supplier_country not in ["DE", "INSIDE_EU", "OUTSIDE_EU"]:
            return {"error": "supplier_country must be one of: DE, INSIDE_EU, OUTSIDE_EU"}

        if sale_type and sale_type not in ["GOODS", "SERVICES"]:
            return {"error": "sale_type must be one of: GOODS, SERVICES"}

        attachments_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/attachments/"
        )

        try:
            temp_file_path = None
            actual_file_path = None

            # Priority 1: file_url — download from URL
            if file_url:
                if not is_url(file_url):
                    return {
                        "error": f"file_url must be a valid HTTP(S) URL. Got: {file_url}. "
                        "The MCP server cannot access local filesystem paths."
                    }
                logger.info("Downloading file from URL: %s", file_url)
                temp_file_path = download_file(file_url)
                if not temp_file_path:
                    return {"error": f"Failed to download file from URL: {file_url}"}
                actual_file_path = temp_file_path

            # Priority 2: file_ref — previously uploaded via POST /files/upload
            elif file_ref:
                from norman_mcp.files.upload import resolve_ref
                actual_file_path = resolve_ref(file_ref)
                if not actual_file_path:
                    return {
                        "error": f"file_ref '{file_ref}' not found or expired. "
                        "Upload the file again via POST /files/upload."
                    }

            # Priority 3: base64 — small files only
            elif file_content_base64:
                temp_file_path = save_base64_to_temp(file_content_base64, file_name)
                if not temp_file_path:
                    return {"error": "Failed to decode base64 file content"}
                actual_file_path = temp_file_path

            if not actual_file_path or not os.path.exists(actual_file_path):
                return {
                    "error": "File not found. The MCP server cannot access your local "
                    "filesystem. Provide a file_url (HTTP link) or upload via "
                    "POST /files/upload and pass the file_ref."
                }

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
            
            files["file"].close()
            
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                    os.rmdir(os.path.dirname(temp_file_path))
                    logger.info(f"Removed temporary file: {temp_file_path}")
                except Exception as e:
                    logger.warning(f"Failed to remove temporary file: {str(e)}")
                    
            return _enrich_attachment_download_urls(response, api=api, company_id=company_id)
        except FileNotFoundError:
            return {"error": "File not found. Provide a file_url or upload via POST /files/upload."}
        except PermissionError:
            return {"error": "Permission denied when accessing the file."}
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

    @mcp.tool(
        title="Link Attachment to Transaction",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
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

    _IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"}
    _EXT_TO_MIME = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
        ".tiff": "image/tiff", ".tif": "image/tiff",
    }

    @mcp.tool(
        title="Get Attachment Preview",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_attachment_preview(
        ctx: Context,
        attachment_id: str = Field(description="Public ID of the attachment to preview"),
    ) -> CallToolResult:
        """
        Download an attachment and return it as an inline image.

        Works for image attachments (PNG, JPEG, GIF, WebP). For PDFs and
        other non-image files, returns the download URL instead.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id

        if not company_id:
            return CallToolResult(content=[
                TextContent(type="text", text='{"error": "No company available. Please authenticate first."}')
            ])

        detail_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/attachments/{attachment_id}/",
        )
        detail = api._make_request("GET", detail_url)
        file_field = detail.get("file") or ""
        ext = os.path.splitext(file_field)[1].lower() if file_field else ""

        dl_endpoint = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/attachments/{attachment_id}/download/",
        )
        dl_resp = api._make_request("GET", dl_endpoint)
        presigned_url = dl_resp.get("url", "")

        if ext not in _IMAGE_EXTENSIONS or not presigned_url:
            meta = {
                "attachmentId": attachment_id,
                "fileName": detail.get("fileName") or os.path.basename(file_field),
                "downloadUrl": presigned_url,
                "note": "File is not an image; use downloadUrl to access it.",
            }
            return CallToolResult(content=[
                TextContent(type="text", text=json.dumps(meta, ensure_ascii=False))
            ])

        resp = requests.get(presigned_url, timeout=30)
        resp.raise_for_status()
        image_b64 = base64.b64encode(resp.content).decode()
        mime = _EXT_TO_MIME.get(ext, "image/png")

        meta = {
            "attachmentId": attachment_id,
            "fileName": detail.get("fileName") or os.path.basename(file_field),
            "downloadUrl": presigned_url,
        }

        return CallToolResult(content=[
            ImageContent(type="image", data=image_b64, mimeType=mime),
            TextContent(type="text", text=json.dumps(meta, ensure_ascii=False)),
        ])