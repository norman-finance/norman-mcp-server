import base64
import json
import logging
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context
from norman_mcp.document_input import (
    DocumentInputError,
    ResolvedDocument,
    normalize_document_input,
    resolve_document_input,
)
from norman_mcp.security.utils import validate_input

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

        public_url = os.environ.get("NORMAN_MCP_PUBLIC_URL", "https://mcp.norman.finance")
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
            openWorldHint=False,
        ),
        meta={"openai/fileParams": ["files"]},
    )
    async def upload_bulk_attachments(
        ctx: Context,
        files: Optional[List[Dict[str, Any]]] = Field(
            default=None,
            description=(
                "Provider-neutral file objects. Each item may contain download_url, "
                "file_ref, or file_data with file_name. OpenAI clients can attach files "
                "to this parameter; Claude clients should provide a signed URL, inline "
                "data, or a Norman file_ref."
            ),
        ),
        file_urls: Optional[List[str]] = Field(
            default=None,
            description="List of signed HTTPS URLs. The server downloads each file directly — nothing goes through the LLM context.",
        ),
        file_refs: Optional[List[str]] = Field(
            default=None, description="List of file_ref tokens from prior POST /files/upload calls."
        ),
        files_base64: Optional[List[Dict[str, str]]] = Field(
            default=None,
            description='LAST RESORT — only for tiny files (<50 KB each). Each item: {"file_name": "receipt.pdf", "content": "<base64>"}. Do NOT use for images or PDFs.',
        ),
        file_paths: Optional[List[str]] = Field(
            default=None,
            description="Legacy local-worker input. Public MCP clients should use files, file_urls, or file_refs.",
        ),
        cashflow_type: Optional[str] = Field(
            default=None,
            description="Optional cashflow type for the transactions (INCOME or EXPENSE). If not provided, then try to detect it from the file",
        ),
    ) -> Dict[str, Any]:
        """
        Upload multiple file attachments in bulk.

        Prefer the provider-neutral ``files`` parameter. Signed HTTPS URLs and
        Norman ``file_ref`` values are portable across OpenAI and Claude. Inline
        base64 is accepted only for small files.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id

        if not company_id:
            return {"error": "No company available. Please authenticate first."}

        if not files and not file_urls and not file_refs and not files_base64 and not file_paths:
            return {"error": "Provide files, file_urls, file_refs, or files_base64."}

        if cashflow_type and cashflow_type not in ["INCOME", "EXPENSE"]:
            return {"error": "cashflow_type must be either 'INCOME' or 'EXPENSE'"}

        upload_url = urljoin(
            config.api_base_url, "api/v1/accounting/transactions/upload-documents/"
        )

        resolved_documents: List[ResolvedDocument] = []
        opened_files = []
        allow_local_paths = os.environ.get("MCP_ALLOW_LOCAL_FILE_PATHS", "").lower() in {
            "1",
            "true",
            "yes",
        }

        try:
            from norman_mcp.files.upload import resolve_ref

            document_inputs: List[Dict[str, Any]] = list(files or [])
            document_inputs.extend({"download_url": url} for url in file_urls or [])
            document_inputs.extend({"file_ref": ref} for ref in file_refs or [])
            document_inputs.extend(
                {
                    "file_name": item.get("file_name"),
                    "file_data": item.get("content"),
                }
                for item in files_base64 or []
            )
            document_inputs.extend({"file_path": path} for path in file_paths or [])

            for item in document_inputs:
                if "file_path" in item:
                    normalized = normalize_document_input(file_path=item["file_path"])
                else:
                    normalized = normalize_document_input(item)
                resolved_documents.append(
                    resolve_document_input(
                        normalized,
                        file_ref_resolver=resolve_ref,
                        allow_local_paths=allow_local_paths,
                    )
                )

            if not resolved_documents:
                return {"error": "No valid files found for upload."}

            multipart_files = []
            for document in resolved_documents:
                file_handle = open(document.path, "rb")
                opened_files.append(file_handle)
                multipart_files.append(("files", (document.filename, file_handle)))

            data = {}
            if cashflow_type:
                data["cashflow_type"] = cashflow_type

            return api._make_request(
                "POST",
                upload_url,
                json_data=data,
                files=multipart_files,
            )

        except DocumentInputError as e:
            return {
                "error": str(e),
                "accepted_inputs": [
                    "files[].download_url",
                    "files[].file_ref",
                    "files[].file_data + files[].file_name",
                ],
            }
        except Exception as e:
            logger.exception("Error uploading files")
            return {"error": f"Error uploading files: {str(e)}"}
        finally:
            for file_handle in opened_files:
                try:
                    file_handle.close()
                except Exception:
                    pass
            for document in resolved_documents:
                document.cleanup()

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
        file_name: Optional[str] = Field(
            default=None, description="Filter by file name (case insensitive partial match)"
        ),
        linked: Optional[bool] = Field(
            default=None, description="Filter by whether attachment is linked to transactions"
        ),
        attachment_type: Optional[str] = Field(
            default=None,
            description="Filter by attachment type (invoice, receipt, contract, other)",
        ),
        description: Optional[str] = Field(
            default=None, description="Filter by description (case insensitive partial match)"
        ),
        brand_name: Optional[str] = Field(
            default=None, description="Filter by brand name (case insensitive partial match)"
        ),
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
            config.api_base_url, f"api/v1/companies/{company_id}/attachments/"
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
        meta={"openai/fileParams": ["file"]},
    )
    async def create_attachment(
        ctx: Context,
        file: Optional[Dict[str, Any]] = Field(
            default=None,
            description=(
                "Provider-neutral file object. Use download_url, file_ref, or "
                "file_data with file_name. OpenAI clients can attach a file to "
                "this parameter; Claude clients should provide a signed URL, "
                "inline data, or a Norman file_ref."
            ),
        ),
        file_url: Optional[str] = Field(
            default=None,
            description="Signed HTTPS URL to a publicly accessible file. The server downloads it directly — nothing goes through the LLM context.",
        ),
        file_ref: Optional[str] = Field(
            default=None,
            description="Reference token from a prior POST /files/upload call. Use when the client uploaded the file directly to the MCP server.",
        ),
        file_content_base64: Optional[str] = Field(
            default=None,
            description="LAST RESORT — only for tiny files (<50 KB). Do NOT use for images, PDFs, or scanned documents — the base64 string will exceed the context window. Prefer file_url or file_ref.",
        ),
        file_name: Optional[str] = Field(
            default=None,
            description="Original filename with extension (e.g. 'invoice.pdf'). Required when using file_content_base64.",
        ),
        file_path: Optional[str] = Field(
            default=None,
            description=(
                "Legacy local file path or URL. Kept for backwards compatibility. "
                "Remote clients should prefer file, file_url, or file_ref."
            ),
        ),
        transactions: Optional[List[str]] = Field(
            default=None, description="List of transaction IDs to link"
        ),
        attachment_type: Optional[str] = Field(
            default=None, description="Type of attachment (invoice, receipt)"
        ),
        amount: Optional[float] = Field(default=None, description="Amount related to attachment"),
        amount_exchanged: Optional[float] = Field(
            default=None, description="Exchanged amount in different currency"
        ),
        attachment_number: Optional[str] = Field(
            default=None, description="Unique number for attachment"
        ),
        brand_name: Optional[str] = Field(
            default=None, description="Brand name associated with attachment"
        ),
        currency: str = "EUR",
        currency_exchanged: str = "EUR",
        description: Optional[str] = Field(default=None, description="Description of attachment"),
        supplier_country: Optional[str] = Field(
            default=None,
            description="Country of supplier (DE, DOMESTIC, INSIDE_EU, OUTSIDE_EU)",
        ),
        value_date: Optional[str] = Field(default=None, description="Date of value"),
        vat_sum_amount: Optional[float] = Field(default=None, description="VAT sum amount"),
        vat_sum_amount_exchanged: Optional[float] = Field(
            default=None, description="Exchanged VAT sum amount"
        ),
        vat_rate: Optional[int] = Field(default=None, description="VAT rate percentage"),
        sale_type: Optional[str] = Field(default=None, description="Type of sale"),
        additional_metadata: Optional[Dict[str, Any]] = Field(
            default=None, description="Additional metadata for attachment"
        ),
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
            supplier_country: Country of supplier (DE, DOMESTIC, INSIDE_EU, OUTSIDE_EU)
            value_date: Date of value
            vat_sum_amount: VAT sum amount
            vat_sum_amount_exchanged: Exchanged VAT sum amount
            vat_rate: VAT rate percentage
            sale_type: Type of sale
            additional_metadata: Additional metadata for attachment

        How to provide the file (pick one):
        1. file_url  — use a short-lived signed HTTPS URL
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

        if not file and not file_url and not file_ref and not file_content_base64 and not file_path:
            return {
                "error": "Provide one of: file, file_url, file_ref, or "
                "file_content_base64 (small files only). Legacy file_path is also accepted."
            }

        if attachment_type and attachment_type not in ["invoice", "receipt", "contract", "other"]:
            return {"error": "attachment_type must be one of: invoice, receipt, contract, other"}

        if supplier_country and supplier_country not in [
            "DE",
            "DOMESTIC",
            "INSIDE_EU",
            "OUTSIDE_EU",
        ]:
            return {"error": "supplier_country must be one of: DE, DOMESTIC, INSIDE_EU, OUTSIDE_EU"}

        if sale_type and sale_type not in ["GOODS", "SERVICES"]:
            return {"error": "sale_type must be one of: GOODS, SERVICES"}

        attachments_url = urljoin(
            config.api_base_url, f"api/v1/companies/{company_id}/attachments/"
        )

        resolved_document: ResolvedDocument | None = None
        file_handle = None
        try:
            from norman_mcp.files.upload import resolve_ref

            normalized = normalize_document_input(
                file,
                file_url=file_url,
                file_ref=file_ref,
                file_content_base64=file_content_base64,
                file_name=file_name,
                file_path=file_path,
            )
            resolved_document = resolve_document_input(
                normalized,
                file_ref_resolver=resolve_ref,
            )
            file_handle = open(resolved_document.path, "rb")
            multipart_files = {
                "file": (resolved_document.filename, file_handle),
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
                # Multipart form fields must be scalar values. DRF's JSONField
                # parses the serialized object on the Norman API side.
                data["additional_metadata"] = json.dumps(sanitized_metadata)

            response = api._make_request(
                "POST",
                attachments_url,
                json_data=data,
                files=multipart_files,
            )
            return _enrich_attachment_download_urls(response, api=api, company_id=company_id)
        except DocumentInputError as e:
            return {
                "error": str(e),
                "accepted_inputs": [
                    "file.download_url",
                    "file.file_ref",
                    "file.file_data + file.file_name",
                ],
            }
        except FileNotFoundError:
            return {"error": "File not found. Provide a file_url or upload via POST /files/upload."}
        except PermissionError:
            return {"error": "Permission denied when accessing the file."}
        except Exception as e:
            logger.error(f"Error uploading file: {str(e)}")
            return {"error": f"Error uploading file: {str(e)}"}
        finally:
            if file_handle:
                try:
                    file_handle.close()
                except Exception:
                    pass
            if resolved_document:
                resolved_document.cleanup()

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
        transaction_id: str = Field(description="ID of the transaction to link"),
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
            f"api/v1/companies/{company_id}/attachments/{attachment_id}/link-transaction/",
        )

        link_data = {"transaction": transaction_id}

        return api._make_request("POST", link_url, json_data=link_data)

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
        result = api._make_request("DELETE", attachment_url, params=params)
        # _make_request returns {} on an empty 204 response — treat any falsy result as success.
        if not result:
            return {"message": f"Attachment {attachment_id} deleted successfully."}
        return result

    _IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"}
    _EXT_TO_MIME = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
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
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text='{"error": "No company available. Please authenticate first."}',
                    )
                ]
            )

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
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(meta, ensure_ascii=False))]
            )

        resp = requests.get(presigned_url, timeout=30)
        resp.raise_for_status()

        try:
            from io import BytesIO

            from PIL import Image

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
            "fileName": detail.get("fileName") or os.path.basename(file_field),
            "downloadUrl": presigned_url,
        }

        return CallToolResult(
            content=[
                ImageContent(type="image", data=image_b64, mimeType=mime),
                TextContent(type="text", text=json.dumps(meta, ensure_ascii=False)),
            ]
        )
