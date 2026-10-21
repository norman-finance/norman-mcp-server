"""Client declarations waiting for their tax advisor's signature.

A client who has their advisor file a declaration parks the prepared submission
in Norman; the advisor signs it with their own ELSTER certificate, which submits
it to the Finanzamt, or rejects it. These tools are that inbox for advisors who
work from the chat. The certificate itself is uploaded once in Norman.

Signing is a binding submission. The tool only signs a request whose label the
caller repeats, so an approval given for one declaration cannot sign another.
"""

from typing import Any, Dict, Literal, Optional
from urllib.parse import urljoin

from mcp.types import ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True)
# Rejecting cannot be undone; the client sees it, with the reason, in their conversation.
DESTRUCTIVE_WRITE = ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=True)
# A binding transmission to the tax office.
EXTERNAL_IRREVERSIBLE_WRITE = ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=True)

DECLARATIONS = {
    "advance_vat": "UStVA",
    "annual_vat": "USt-Erklärung",
    "income_tax": "ESt-Erklärung",
    "trade_tax": "GewSt-Erklärung",
    "corporate_tax": "KSt-Erklärung",
    "euer": "EÜR",
    "zmdo": "Zusammenfassende Meldung",
    "registration": "Fragebogen zur steuerlichen Erfassung",
}
NO_CERTIFICATE = (
    "No ELSTER certificate is uploaded for this advisor account. Upload the certificate (PFX file and PIN) "
    "once in Norman under the tax advisor settings, then sign again."
)


def _url(path: str) -> str:
    return urljoin(config.api_base_url, f"api/v1/tax-advisor/{path}")


def _failed(result: Any) -> Optional[Dict[str, Any]]:
    return result if isinstance(result, dict) and result.get("error") else None


def _label(request: Dict[str, Any]) -> str:
    """The label an advisor confirms: the client's own, or the declaration and the client's name."""
    declaration = DECLARATIONS.get(request.get("declaration_type"), request.get("declaration_type") or "")
    return (request.get("label") or "").strip() or f"{declaration} {request.get('companyName') or ''}".strip()


def _request(request: Dict[str, Any]) -> Dict[str, Any]:
    entry = {
        "id": request.get("public_id"),
        "label": _label(request),
        "declaration": DECLARATIONS.get(request.get("declaration_type"), request.get("declaration_type")),
        "clientCompanyId": request.get("companyId"),
        "clientCompanyName": request.get("companyName"),
        "requestedBy": request.get("requestedByEmail"),
        "status": request.get("status"),
        "requestedAt": request.get("created"),
    }
    if request.get("transferticket"):
        entry["transferticket"] = request["transferticket"]
    if request.get("signed_at"):
        entry["signedAt"] = request["signed_at"]
    if request.get("error_message"):
        entry["note"] = request["error_message"]
    return entry


def _rows(result: Any) -> list:
    if isinstance(result, dict):
        result = result.get("results") or []
    return [row for row in result if isinstance(row, dict)] if isinstance(result, list) else []


def _api_detail(result: Dict[str, Any]) -> Dict[str, Any]:
    detail = result.get("detail")
    return detail if isinstance(detail, dict) else {}


def register_advisor_signature_tools(mcp):
    """Register the signature inbox for tax advisors."""

    @mcp.tool(title="List Signature Requests", annotations=READ_ONLY)
    async def list_signature_requests(
        ctx: Context,
        status: Literal["pending", "signed", "rejected", "failed", "all"] = Field(
            default="pending", description="Which requests to list; pending by default.",
        ),
    ) -> Dict[str, Any]:
        """For tax advisors of German clients (Germany only): declarations waiting for your
        signature, or their history.

        Shows the client, the declaration and its label, and whether your ELSTER certificate for
        German filings is uploaded and until when it is valid. Before signing, review the client's numbers
        (switch_company, then list_tax_reports or get_tax_report).
        """
        api = ctx.request_context.lifespan_context["api"]
        result = await api.arequest("GET", _url("pending-signatures/"), params={"status": status})
        if _failed(result):
            return result
        certificate = await api.arequest("GET", _url("elster-certificate/"))
        if _failed(certificate):
            certificate_info: Dict[str, Any] = {"uploaded": False}
            if certificate.get("status_code") == 404:
                certificate_info["hint"] = NO_CERTIFICATE
        else:
            certificate_info = {"uploaded": True, "validUntil": certificate.get("valid_until")}
        return {"requests": [_request(row) for row in _rows(result)], "certificate": certificate_info}

    @mcp.tool(title="Sign and Submit Declaration", annotations=EXTERNAL_IRREVERSIBLE_WRITE)
    async def sign_and_submit_declaration(
        ctx: Context,
        request_id: str = Field(description="The signature request id from list_signature_requests."),
        label: str = Field(description="The request's label exactly as list_signature_requests showed it and the advisor confirmed it."),
    ) -> Dict[str, Any]:
        """For tax advisors of German clients: sign a declaration with your ELSTER certificate and
        submit it to the Finanzamt (Germany only).

        A binding submission that cannot be undone. Show the advisor the client, the declaration
        and its label, and call only after their explicit confirmation; the label must match the
        request, so a confirmation for one declaration cannot sign another.
        """
        api = ctx.request_context.lifespan_context["api"]
        pending = await api.arequest("GET", _url("pending-signatures/"), params={"status": "pending"})
        if _failed(pending):
            return pending
        request = next((row for row in _rows(pending) if row.get("public_id") == request_id), None)
        if request is None:
            return {"error": "This request is not waiting for your signature (already handled, or assigned to someone else)."}
        if label.strip().casefold() != _label(request).casefold():
            return {
                "error": "The label does not match this request, so nothing was signed.",
                "requestLabel": _label(request),
            }

        result = await api.arequest("POST", _url(f"pending-signatures/{request_id}/sign/"))
        if _failed(result):
            detail = _api_detail(result)
            if detail.get("code") == "no_certificate":
                return {"error": NO_CERTIFICATE, "status_code": result.get("status_code")}
            message = detail.get("detail") if isinstance(detail.get("detail"), str) else result.get("error")
            return {"error": message, "status_code": result.get("status_code"), "code": detail.get("code")}
        return _request(result) if isinstance(result, dict) else {"error": "Unexpected response from Norman."}

    @mcp.tool(title="Reject Signature Request", annotations=DESTRUCTIVE_WRITE)
    async def reject_signature_request(
        ctx: Context,
        request_id: str = Field(description="The signature request id from list_signature_requests."),
        reason: str = Field(description="Why the declaration is sent back; the client sees it.", max_length=2000),
    ) -> Dict[str, Any]:
        """For tax advisors of German clients: send a declaration back unsigned, with a reason the
        client sees.

        Cannot be undone: the client prepares a new request. Confirm the reason with the advisor first.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not reason.strip():
            return {"error": "Give the client a reason."}
        result = await api.arequest("POST", _url(f"pending-signatures/{request_id}/reject/"),
                                    json_data={"reason": reason.strip()})
        if _failed(result):
            return result
        return _request(result) if isinstance(result, dict) else {"error": "Unexpected response from Norman."}
