"""MCP App entry point and authenticated upload-result handoff."""

import json
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.apps.inbox import resolve_company
from norman_mcp.context import Context, get_oauth_provider
from norman_mcp.files.inline_upload import (
    MAX_FILES,
    MAX_FILE_SIZE,
    MAX_TOTAL_SIZE,
    TTL,
    UploadError,
    UploadStore,
    current_access,
    grant_key,
    public_url,
    upload_html,
)

UPLOAD_URI = "ui://norman/document-upload-v1.html"


def result(data: dict, *, meta: dict | None = None, error: bool = False):
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data))],
        structuredContent=data,
        _meta=meta or {},
        isError=error,
    )


def register_upload_resource(mcp: Any):
    origin = urlsplit(public_url())
    connect_origin = f"{origin.scheme}://{origin.netloc}"

    @mcp.resource(
        UPLOAD_URI,
        name="norman-document-upload",
        title="Upload documents to Norman",
        mime_type="text/html;profile=mcp-app",
        meta={
            "ui": {
                "prefersBorder": False,
                "csp": {"connectDomains": [connect_origin], "resourceDomains": []},
            },
            "openai/widgetPrefersBorder": False,
            "openai/widgetDescription": "Upload receipts and invoices directly to Norman, choosing Revenue or Expense for each file.",
            "openai/widgetCSP": {"connect_domains": [connect_origin], "resource_domains": []},
        },
    )
    async def document_upload() -> str:
        return upload_html()


def register_upload_tools(mcp: Any):
    @mcp.tool(
        title="Upload Documents",
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
        ),
        meta={
            "ui": {"resourceUri": UPLOAD_URI},
            "openai/outputTemplate": UPLOAD_URI,
            "openai/widgetAccessible": True,
            "openai/toolInvocation/invoking": "Opening document upload…",
            "openai/toolInvocation/invoked": "Ready to upload documents",
        },
    )
    async def request_file_upload(
        ctx: Context,
        description: Optional[str] = Field(
            default=None,
            description="Optional description of the receipts or invoices the user wants to upload.",
        ),
    ) -> CallToolResult:
        """Open an in-chat multi-file uploader for receipts and invoices.

        Prefer this when the user needs to choose local files. The user selects
        Revenue or Expense per document and confirms upload in the panel.
        Uploaded attachments are saved by the panel: DO NOT call create_attachment
        or upload_bulk_attachments again for these files. Use get_file_upload_status
        to read the outcome. Only show fallback_url if the panel is unavailable or
        fails. If a file is already accessible through file_url, use the existing
        document tools directly instead of asking for another upload.
        """
        provider, access = get_oauth_provider(), get_access_token()
        if not provider or not access:
            return result(
                {
                    "error": "The inline uploader requires an authenticated hosted Norman connection. Use file_url or the existing direct upload flow in other clients."
                },
                error=True,
            )
        api = ctx.request_context.lifespan_context["api"]
        company = await resolve_company(api)
        if not company:
            return result({"error": "Select a company before uploading documents."}, error=True)
        details = await api.arequest(
            "GET", urljoin(config.api_base_url, f"api/v1/companies/{company}/")
        )
        if not isinstance(details, dict) or details.get("error"):
            return result(
                {"error": "Could not verify the selected company. Reconnect Norman and try again."},
                error=True,
            )
        name = str(details.get("name") or details.get("companyName") or company)
        country = details.get("country") or ""
        if isinstance(country, dict):
            country = country.get("code") or country.get("isoCode") or ""
        try:
            store = UploadStore()
            session_id, ticket = store.create(
                grant_key(provider, access),
                str(company),
                provider.get_company_for_token(access.token),
                name,
                str(country),
            )
            session = store.session(session_id=session_id)
            current_access(session, provider)
        except UploadError as exc:
            return result({"error": exc.message}, error=True)
        fallback_url = f"{public_url()}/files/upload-app#{ticket}"
        data = {
            "session_id": session_id,
            "company_id": str(company),
            "company_name": name,
            "country": str(country),
            "description": description if isinstance(description, str) else "",
            "expires_in_seconds": TTL,
            "fallback_url": fallback_url,
            "instructions": "Use the in-chat upload panel. Only offer fallback_url if the panel cannot be used. After upload, call get_file_upload_status with this session_id; attachments are already saved. Never ask the user to copy a file_ref.",
        }
        return result(
            data,
            meta={
                "upload": {
                    "ticket": ticket,
                    "base_url": public_url(),
                    "max_file_size": MAX_FILE_SIZE,
                    "max_total_size": MAX_TOTAL_SIZE,
                    "max_files": MAX_FILES,
                }
            },
        )

    @mcp.tool(
        title="Get Document Upload Status",
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
        meta={"ui": {"visibility": ["model", "app"]}, "openai/widgetAccessible": True},
    )
    async def get_file_upload_status(ctx: Context, session_id: str) -> CallToolResult:
        """Read this user's upload panel result, including per-document direction and attachment IDs.

        Read after the panel/fallback upload finishes. Successful attachments
        already exist in Norman; do not upload them again. Pending OCR is not
        finalized bookkeeping. No file_ref needs to be copied by the user.
        """
        provider, access = get_oauth_provider(), get_access_token()
        try:
            store = UploadStore()
            session = store.session(session_id=session_id)
            if not provider or not access or grant_key(provider, access) != session["grant_key"]:
                raise UploadError("Upload session is not available to this connection.", 403)
            company = await resolve_company(ctx.request_context.lifespan_context["api"])
            if str(company) != session["company"]:
                raise UploadError(
                    "This upload belongs to a different company. Select its company to review it.",
                    403,
                )
            current_access(session, provider)
            return result(store.summary(session))
        except UploadError as exc:
            return result({"error": exc.message}, error=True)


def register_upload_app(mcp: Any):
    register_upload_resource(mcp)
    register_upload_tools(mcp)
