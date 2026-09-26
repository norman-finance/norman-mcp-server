import asyncio
import base64
import json
import logging
import os
import random
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
from norman_mcp.files.download import FileDownloadError, download_file
from norman_mcp.tools._concurrency import gather_bounded
from norman_mcp.tools.results import is_failure

logger = logging.getLogger(__name__)

# source_system used when a structured import names an external_id without one:
# the API needs both to recognise a retried document.
DEFAULT_SOURCE_SYSTEM = "mcp"
# Structured imports with an external_id are idempotent, so a transient server
# or network failure is retried with exponential backoff and jitter.
STRUCTURED_IMPORT_ATTEMPTS = 3
STRUCTURED_IMPORT_BACKOFF_SECONDS = 1.0
_RETRYABLE_TRANSPORT_CODES = {"connection_error", "timeout", "request_error"}

_STRUCTURED_DOCUMENT_KEYS = {
    "file_url", "file_ref", "file_content_base64", "file_name",
    "source_system", "external_id", "metadata",
}
_STRUCTURED_METADATA_KEYS = {
    "supplier", "customer", "invoice_number", "invoice_date", "service_date",
    "net_amount", "vat_amount", "gross_amount", "currency", "document_type",
    "direction", "tags",
}


async def _enrich_attachment_download_urls(data: dict, api=None, company_id: str | None = None) -> dict:
    """Add presigned downloadUrl for attachment files.

    One API call per row, fanned out with bounded concurrency: chained, a page
    of attachments used to hold the event loop for a round trip per row.
    """
    if not isinstance(data, dict):
        return data

    async def _enrich_single(item: dict) -> None:
        pk = item.get("publicId") or item.get("pk")
        if pk and item.get("file") and api and company_id:
            dl_endpoint = urljoin(
                config.api_base_url,
                f"api/v1/companies/{company_id}/attachments/{pk}/download/",
            )
            dl_resp = await api.arequest("GET", dl_endpoint)
            if isinstance(dl_resp, dict) and dl_resp.get("url"):
                item["downloadUrl"] = dl_resp["url"]

    items = [data] if data.get("publicId") or data.get("pk") else []
    if isinstance(data.get("results"), list):
        items.extend(item for item in data["results"] if isinstance(item, dict))
    # A failed row keeps its fields and simply gets no downloadUrl.
    await gather_bounded(_enrich_single(item) for item in items)
    return data


def is_url(path: str) -> bool:
    """Check if the given path is a URL."""
    try:
        result = urlparse(path)
        return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
    except Exception:
        return False

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


def _validate_structured_document(document: Dict[str, Any]) -> Optional[str]:
    unknown = sorted(set(document) - _STRUCTURED_DOCUMENT_KEYS)
    if unknown:
        return f"Unsupported document fields: {', '.join(unknown)}"

    sources = [
        key for key in ("file_url", "file_ref", "file_content_base64")
        if document.get(key)
    ]
    if len(sources) != 1:
        return "Provide exactly one of file_url, file_ref, or file_content_base64."
    if document.get("file_content_base64") and not document.get("file_name"):
        return "file_name is required with file_content_base64."

    metadata = document.get("metadata") or {}
    if not isinstance(metadata, dict):
        return "metadata must be an object."
    unknown_metadata = sorted(set(metadata) - _STRUCTURED_METADATA_KEYS)
    if unknown_metadata:
        return f"Unsupported metadata fields: {', '.join(unknown_metadata)}"
    if "tags" in metadata and not isinstance(metadata["tags"], list):
        return "metadata.tags must be an array."
    return None


async def _resolve_structured_document_file(document: Dict[str, Any]) -> tuple[Optional[str], bool, Optional[str]]:
    """Return (path, is_temporary, error) for one portable document input."""
    if file_url := document.get("file_url"):
        if not is_url(file_url):
            return None, False, "file_url must be a valid HTTP(S) URL."
        path = await download_file(file_url)
        return path, True, None

    if file_ref := document.get("file_ref"):
        from norman_mcp.files.upload import resolve_ref
        path = resolve_ref(file_ref)
        return (path, False, None) if path else (None, False, "file_ref was not found or expired.")

    path = save_base64_to_temp(document["file_content_base64"], document["file_name"])
    return (path, True, None) if path else (None, False, "Failed to decode file_content_base64.")


def _is_retryable_import_failure(response: Any) -> bool:
    """A 5xx or transport failure, which may succeed when sent again."""
    if not is_failure(response):
        return False
    status = response.get("status_code")
    if isinstance(status, int):
        return status >= 500
    return response.get("code") in _RETRYABLE_TRANSPORT_CODES


async def _post_structured_import(
    api: Any,
    url: str,
    path: str,
    metadata: Dict[str, Any],
    *,
    retry: bool,
) -> Dict[str, Any]:
    """Post one document, retrying transient failures only when ``retry``.

    Only call with retry=True for a document that has an external_id: the API
    then returns the already-stored document instead of a duplicate, even if
    an earlier attempt succeeded but its response was lost.
    """
    attempts = STRUCTURED_IMPORT_ATTEMPTS if retry else 1
    for attempt in range(1, attempts + 1):
        # A fresh handle per attempt: the previous upload consumed the stream.
        with open(path, "rb") as file_handle:
            response = await api.arequest(
                "POST",
                url,
                json_data=metadata,
                files={"file": file_handle},
            )
        if attempt == attempts or not _is_retryable_import_failure(response):
            break
        delay = STRUCTURED_IMPORT_BACKOFF_SECONDS * 2 ** (attempt - 1)
        await asyncio.sleep(delay * random.uniform(0.5, 1.5))
    if attempt > 1 and isinstance(response, dict):
        response = {**response, "attempts": attempt}
    return response


def _remove_temp_file(path: Optional[str]) -> None:
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
            os.rmdir(os.path.dirname(path))
    except Exception as exc:
        logger.warning("Failed to remove temporary file %s: %s", path, exc)

def register_document_tools(mcp):
    """Register all document-related tools with the MCP server."""

    @mcp.tool(
        title="Create File Upload Link",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def request_file_upload(
        ctx: Context,
        description: Optional[str] = Field(
            default=None,
            description="Short description shown to the user on the upload page, e.g. 'Receipt for Meta Ads January 2025'.",
        ),
    ) -> Dict[str, Any]:
        """
        Generate a short-lived upload link that the USER opens in their browser.

        Call this BEFORE create_attachment when the user wants to attach a file
        (image, PDF, receipt) and you cannot provide a public file_url.
        The link opens a drag-and-drop upload page. After the user uploads,
        the page shows a file_ref token. Use that file_ref in create_attachment.

        IMPORTANT: Do NOT try to upload the file yourself (curl, base64, etc.).
        Just give the link to the user and wait for them to upload.
        """
        from norman_mcp.files.upload import create_upload_token

        public_url = os.environ.get(
            "NORMAN_MCP_PUBLIC_URL", "https://mcp.norman.finance"
        )
        token = create_upload_token(description)
        upload_page_url = f"{public_url.rstrip('/')}/files/upload/{token}"

        return {
            "upload_url": upload_page_url,
            "expires_in_seconds": 1800,
            "instructions": (
                f"Please open this link in your browser and drop the file: {upload_page_url} "
                "— after uploading, the page will show a file_ref code. "
                "Give it back to me so I can attach the file."
            ),
        }

    @mcp.tool(
        title="Upload Bulk Attachments",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def upload_bulk_attachments(
        ctx: Context,
        file_urls: Optional[List[str]] = Field(default=None, description="BEST OPTION: List of HTTP(S) URLs. The server downloads each file directly — nothing goes through the LLM context."),
        file_refs: Optional[List[str]] = Field(default=None, description="List of file_ref tokens from prior POST /files/upload calls."),
        files_base64: Optional[List[Dict[str, str]]] = Field(default=None, description="LAST RESORT — only for tiny files (<50 KB each). Each item: {\"file_name\": \"receipt.pdf\", \"content\": \"<base64>\"}. Do NOT use for images or PDFs."),
        file_paths: Optional[List[str]] = Field(default=None, description="Deprecated alias for file_urls."),
        cashflow_type: Optional[str] = Field(default=None, description="Optional cashflow type for the transactions (INCOME or EXPENSE). If not provided, then try to detect it from the file")
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
        download_errors = []

        try:
            files = []
            valid_paths = []

            # Priority 1: file_urls
            all_urls = list(file_urls or []) + [p for p in (file_paths or []) if is_url(p)]
            for index, url in enumerate(all_urls):
                if not is_url(url):
                    download_errors.append({
                        "index": index, "code": "invalid_file_url",
                        "error": "file_url must be a valid HTTP(S) URL.",
                    })
                    continue
                try:
                    downloaded = await download_file(url)
                except FileDownloadError as exc:
                    download_errors.append({"index": index, **exc.as_result()})
                    continue
                valid_paths.append(downloaded)
                temp_files.append(downloaded)

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
                return {"error": "No valid files found for upload", "download_errors": download_errors}
                
            # Open and prepare valid files
            for path in valid_paths:
                file_handle = open(path, "rb")
                opened_files.append(file_handle)
                files.append(("files", file_handle))
                    
            data = {}
            if cashflow_type:
                data["cashflow_type"] = cashflow_type
                
            response = await api.arequest("POST", upload_url, json_data=data, files=files)
            
            if download_errors:
                response = {**response, "download_errors": download_errors}
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
        title="Import Structured Documents (No OCR)",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def upload_structured_attachments(
        ctx: Context,
        documents: List[Dict[str, Any]] = Field(
            description=(
                "Documents to store without OCR. Each item contains exactly one of "
                "file_url, file_ref, or file_content_base64; optional external_id (the "
                "document's stable id in the source system) and source_system (the "
                "system's name; required by the API with external_id and defaults to "
                "\"mcp\" -- set it when importing from several systems so their ids "
                "cannot collide); and optional metadata with supplier, customer, "
                "invoice_number, invoice_date, service_date, net_amount, vat_amount, "
                "gross_amount, currency, document_type, direction, and tags."
            ),
        ),
    ) -> Dict[str, Any]:
        """Store pre-processed documents without transaction side effects.

        Missing metadata remains missing. With an external_id, a repeated import
        returns the existing document instead of creating a duplicate, so those
        documents are retried automatically (up to 3 attempts) after a server
        error or connection failure. Give every document an external_id for
        large batches; failed documents can then simply be sent again.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        if not documents:
            return {"error": "documents must contain at least one item."}
        if len(documents) > 100:
            return {"error": "A maximum of 100 documents can be imported at once."}

        import_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/attachments/structured-import/",
        )
        results: List[Dict[str, Any]] = []
        created_count = 0
        existing_count = 0
        failed_count = 0

        for index, document in enumerate(documents):
            if not isinstance(document, dict):
                results.append({"index": index, "error": "Each document must be an object."})
                failed_count += 1
                continue

            if error := _validate_structured_document(document):
                results.append({"index": index, "error": error})
                failed_count += 1
                continue

            try:
                path, is_temporary, error = await _resolve_structured_document_file(document)
            except FileDownloadError as exc:
                results.append({"index": index, **exc.as_result()})
                failed_count += 1
                continue
            if error or not path:
                results.append({"index": index, "error": error or "File is unavailable."})
                failed_count += 1
                continue

            try:
                metadata = dict(document.get("metadata") or {})
                external_id = document.get("external_id")
                source_system = document.get("source_system")
                if external_id and not source_system:
                    source_system = DEFAULT_SOURCE_SYSTEM
                if source_system:
                    metadata["external_source"] = source_system
                if external_id:
                    metadata["external_id"] = external_id

                response = await _post_structured_import(
                    api,
                    import_url,
                    path,
                    metadata,
                    retry=bool(external_id),
                )

                result = {"index": index, **response}
                if response.get("error"):
                    failed_count += 1
                elif response.get("created") is False:
                    existing_count += 1
                else:
                    created_count += 1
                results.append(result)
            except (FileNotFoundError, PermissionError) as exc:
                failed_count += 1
                results.append({"index": index, "error": str(exc)})
            except Exception as exc:
                logger.exception("Structured document import failed at index %d", index)
                failed_count += 1
                results.append({"index": index, "error": f"Import failed: {exc}"})
            finally:
                if is_temporary:
                    _remove_temp_file(path)

        return {
            "total": len(documents),
            "created": created_count,
            "existing": existing_count,
            "failed": failed_count,
            "results": results,
        }

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
        file_name: Optional[str] = Field(default=None, description="Filter by file name (case insensitive partial match)"),
        linked: Optional[bool] = Field(default=None, description="true: only documents attached to a transaction; false: only documents not attached to any. Omit for all."),
        attachment_type: Optional[str] = Field(default=None, description="Filter by attachment type (invoice, receipt, contract, other)"),
        description: Optional[str] = Field(default=None, description="Filter by description (case insensitive partial match)"),
        brand_name: Optional[str] = Field(default=None, description="Filter by brand name (case insensitive partial match)"),
        search: Optional[str] = Field(default=None, description="Preferred supplier/document search across brand, description, file name, invoice number and amount. Do not also fill the individual text filters unless intentionally narrowing results."),
        date_from: Optional[str] = Field(default=None, description="Earliest document date, YYYY-MM-DD; the upload date counts when a document has none. Allow for invoice/payment lag when matching receipts."),
        date_to: Optional[str] = Field(default=None, description="Latest document date, YYYY-MM-DD; the upload date counts when a document has none."),
        page: int = Field(default=1, ge=1, description="Result page; continue while the response has next"),
        page_size: int = Field(default=50, ge=1, le=100, description="Documents per page"),
        include_download_urls: bool = Field(default=True, description="Add a temporary downloadUrl to every result. Set false for metadata searches such as receipt matching; it saves one API call per document."),
    ) -> Dict[str, Any]:
        """
        Search saved purchase invoices and receipts (not outgoing sales invoices).

        Prefer search for supplier discovery; individual filters combine with AND.
        For receipt matching, use search with page_size=10 and include_download_urls=false.
        An empty filtered result does not prove a document is missing: try aliases or a
        date-bounded search. Page within the requested scope rather than enumerating the
        whole archive.

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
        
        params: Dict[str, Any] = {"page": page, "page_size": page_size}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        if search:
            params["search"] = search
        if file_name:
            params["file_name"] = file_name
        if linked is not None:
            # The API's filter is inverted for historical reasons: linked=true
            # returns UNlinked documents (filtersets/attachment.py). Translate
            # so the parameter means what it says.
            params["linked"] = not linked
        if attachment_type:
            params["has_type"] = attachment_type
        if description:
            params["description"] = description
        if brand_name:
            params["brand_name"] = brand_name
            
        result = await api.arequest("GET", attachments_url, params=params)
        if include_download_urls:
            return await _enrich_attachment_download_urls(result, api=api, company_id=company_id)
        return result

    @mcp.tool(
        title="Create Attachment",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def create_attachment(
        ctx: Context,
        file_url: Optional[str] = Field(default=None, description="BEST OPTION: HTTP(S) download URL, including a valid presigned URL with query parameters. Must be accessible without additional headers. The server downloads it directly; the file does not go through the LLM context."),
        file_ref: Optional[str] = Field(default=None, description="Reference token from a prior POST /files/upload call. Use when the client uploaded the file directly to the MCP server."),
        file_content_base64: Optional[str] = Field(default=None, description="LAST RESORT — only for tiny files (<50 KB). Do NOT use for images, PDFs, or scanned documents — the base64 string will exceed the context window. Prefer file_url or file_ref."),
        file_name: Optional[str] = Field(default=None, description="Original filename with extension (e.g. 'invoice.pdf'). Required when using file_content_base64."),
        transactions: Optional[List[str]] = Field(default=None, description="List of transaction IDs to link"),
        attachment_type: Optional[str] = Field(default=None, description="Type of attachment (invoice, receipt)"),
        amount: Optional[float] = Field(default=None, description="Amount related to attachment"),
        amount_exchanged: Optional[float] = Field(default=None, description="Exchanged amount in different currency"),
        attachment_number: Optional[str] = Field(default=None, description="Unique number for attachment"),
        brand_name: Optional[str] = Field(default=None, description="Brand name associated with attachment"),
        currency: str = "EUR",
        currency_exchanged: str = "EUR",
        description: Optional[str] = Field(default=None, description="Description of attachment"),
        supplier_country: Optional[str] = Field(default=None, description="Country of supplier (DE, INSIDE_EU, OUTSIDE_EU)"),
        value_date: Optional[str] = Field(default=None, description="Date of value"),
        vat_sum_amount: Optional[float] = Field(default=None, description="VAT sum amount"),
        vat_sum_amount_exchanged: Optional[float] = Field(default=None, description="Exchanged VAT sum amount"),
        vat_rate: Optional[int] = Field(default=None, description="VAT rate percentage"),
        sale_type: Optional[str] = Field(default=None, description="Type of sale"),
        additional_metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata for attachment")
    ) -> Dict[str, Any]:
        """
        Create a new attachment with a file.

        Args:
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

        How to provide the file (pick one):
        1. file_url  — best if the file has a public HTTP(S) URL
        2. file_ref  — call request_file_upload first to get an upload link,
           ask the user to open it in their browser and drop the file,
           then pass the file_ref here
        3. file_content_base64 — ONLY for tiny files under 50 KB

        NEVER base64-encode images, PDFs, or scans — they will blow up the
        context window. Use file_url or request_file_upload instead.
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

        temp_file_path = None
        files = {}
        try:
            actual_file_path = None

            # Priority 1: file_url — download from URL
            if file_url:
                if not is_url(file_url):
                    return {
                        "error": "file_url must be a valid HTTP(S) URL. "
                        "The MCP server cannot access local filesystem paths."
                    }
                temp_file_path = await download_file(file_url)
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
                
            response = await api.arequest("POST", attachments_url, json_data=data, files=files)
            
            return await _enrich_attachment_download_urls(response, api=api, company_id=company_id)
        except FileDownloadError as exc:
            return exc.as_result()
        except FileNotFoundError:
            return {"error": "File not found. Provide a file_url or upload via POST /files/upload."}
        except PermissionError:
            return {"error": "Permission denied when accessing the file."}
        except Exception as e:
            logger.error(f"Error uploading file: {str(e)}")
            return {"error": f"Error uploading file: {str(e)}"}
        finally:
            for file_handle in files.values():
                file_handle.close()
            _remove_temp_file(temp_file_path)


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
        
        return await api.arequest("POST", link_url, json_data=link_data)

    @mcp.tool(
        title="Delete Attachment",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def delete_attachment(
        ctx: Context,
        attachment_id: str = Field(description="ID of the attachment to delete"),
        confirm: bool = Field(
            default=False,
            description=(
                "Documents under legal retention (GoBD, ~10 years) cannot be deleted "
                "without confirmation — the API returns 409 with requiresConfirmation. "
                "Set true to confirm and override the retention guard. Only do this on "
                "the user's explicit instruction to delete a retained document."
            ),
        ),
    ) -> Dict[str, Any]:
        """
        Delete an attachment — e.g. an orphan receipt/invoice with no linked transaction
        (a stale self-statement left behind after the real invoice was attached).

        Retention-aware: Norman keeps documents under GoBD retention. A retained document
        returns a 409 whose `detail.requiresConfirmation` is true (with a `retentionUntil`
        date); re-call with `confirm=true` to override. Only call once the user has
        confirmed the attachment should be removed.

        Args:
            attachment_id: ID of the attachment to delete
            confirm: set true to override the legal-retention guard on a retained document

        Returns:
            Confirmation of deletion, or the 409 retention warning if confirm is not set
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return {"error": "No company available. Please authenticate first."}

        attachment_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/attachments/{attachment_id}/",
        )
        # Backend expects ?confirmed=true to override the GoBD retention guard.
        params = {"confirmed": "true"} if confirm else None
        result = await api.arequest("DELETE", attachment_url, params=params)
        # The API client returns {} on an empty 204 response — treat any falsy result as success.
        if not result:
            return {"message": f"Attachment {attachment_id} deleted successfully."}
        return result

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

        def _failed(payload: Dict[str, Any]) -> CallToolResult:
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, default=str))],
                isError=True,
            )

        if not company_id:
            return _failed({"error": "No company available. Please authenticate first."})

        detail_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/attachments/{attachment_id}/",
        )
        detail = await api.arequest("GET", detail_url)
        # A failed lookup used to read as "not an image" with an empty link.
        if is_failure(detail):
            return _failed(detail)
        file_field = detail.get("file") or ""
        # In production `file` is a presigned URL: take the extension from its
        # path, or ".png?X-Amz-..." never matched and no image was ever shown.
        file_path = urlparse(file_field).path if file_field else ""
        ext = os.path.splitext(file_path)[1].lower()

        dl_endpoint = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/attachments/{attachment_id}/download/",
        )
        dl_resp = await api.arequest("GET", dl_endpoint)
        if is_failure(dl_resp):
            return _failed(dl_resp)
        presigned_url = dl_resp.get("url", "")

        if ext not in _IMAGE_EXTENSIONS or not presigned_url:
            meta = {
                "attachmentId": attachment_id,
                "fileName": detail.get("fileName") or os.path.basename(file_path),
                "downloadUrl": presigned_url,
                "note": "File is not an image; use downloadUrl to access it.",
            }
            return CallToolResult(content=[
                TextContent(type="text", text=json.dumps(meta, ensure_ascii=False))
            ])

        # Off the event loop: this download can take up to 30 seconds.
        resp = await asyncio.to_thread(requests.get, presigned_url, timeout=30)
        resp.raise_for_status()

        try:
            from PIL import Image
            from io import BytesIO
            img = Image.open(BytesIO(resp.content))
            max_dim = 1200
            if max(img.size) > max_dim:
                img.thumbnail((max_dim, max_dim), Image.LANCZOS)
            buf = BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=75, optimize=True)
            image_b64 = base64.b64encode(buf.getvalue()).decode()
            mime = "image/jpeg"
        except Exception:
            image_b64 = base64.b64encode(resp.content).decode()
            mime = _EXT_TO_MIME.get(ext, "image/png")

        meta = {
            "attachmentId": attachment_id,
            "fileName": detail.get("fileName") or os.path.basename(file_path),
            "downloadUrl": presigned_url,
        }

        return CallToolResult(content=[
            ImageContent(type="image", data=image_b64, mimeType=mime),
            TextContent(type="text", text=json.dumps(meta, ensure_ascii=False)),
        ])
