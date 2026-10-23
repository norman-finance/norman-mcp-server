import json
import logging
import requests
from typing import Dict, Any, Optional
from urllib.parse import urljoin
from pydantic import Field
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from mcp.server.mcpserver.exceptions import ToolError

from norman_mcp.context import Context
from norman_mcp import config
from norman_mcp.tools.results import as_object, first_text
from norman_mcp.tools.polish_settings import company_country, propose, propose_vat_status

logger = logging.getLogger(__name__)


NO_COMPANY_ERROR = {"error": "No company available. Please authenticate first."}

EMAIL_NOT_CONFIRMED_ERROR = {
    "error": "Email not confirmed",
    "message": (
        "Filing needs a confirmed email address. Call resend_email_confirmation and ask the user "
        "to open the link in that email."
    ),
    "status_code": 403,
}

RESEND_TOO_SOON_ERROR = {
    "error": "Link sent a moment ago",
    "message": "A confirmation link was sent a moment ago. Ask the user to check their inbox and spam folder.",
    "status_code": 429,
}


def _error_code(response: requests.Response) -> Optional[str]:
    try:
        return response.json().get("code")
    except ValueError:
        return None


def reports_url(company_id: str, suffix: str = "") -> str:
    """The company-scoped tax reports route.

    The unscoped api/v1/taxes/reports/ ignores X-Company-Id and serves the
    user's first company (ReportsViewSet._get_company falls back to
    Company.objects.for_user(user).first()). After switch_company -- or for
    anyone whose selected company is not their first -- the tools listed,
    previewed and submitted another company's reports. The MCP apps already
    use this route; it is the same viewset.
    """
    return urljoin(config.api_base_url, f"api/v1/companies/{company_id}/taxes/reports/{suffix}")


def _enrich_report_download_url(
    data: dict, api=None, report_id: str | None = None, company_id: str | None = None
) -> dict:
    """Add a presigned downloadUrl for the submitted tax report PDF."""
    if not isinstance(data, dict):
        return data
    if api and report_id and company_id and data.get("reportFile"):
        try:
            dl_endpoint = reports_url(company_id, f"{report_id}/download/")
            dl_resp = api._make_request("GET", dl_endpoint)
            if dl_resp.get("url"):
                data["downloadUrl"] = dl_resp["url"]
        except Exception:
            logger.debug("Could not fetch presigned download URL for report %s", report_id)
    return data


def register_tax_tools(mcp):
    """Register all tax-related tools with the MCP server."""
    
    @mcp.tool(
        title="List Tax Reports",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_tax_reports(
        ctx: Context,
        date_from: Optional[str] = Field(default=None, description="Earliest report period start (YYYY-MM-DD)"),
        date_to: Optional[str] = Field(default=None, description="Latest report period end (YYYY-MM-DD)"),
        report_type: str | None = Field(
            default=None,
            description="Report type, e.g. ADVANCED_SALEX_TAX (German UStVA) or JPK_V7M / JPK_V7K (Polish VAT)",
        ),
        page: int = Field(default=1, ge=1, description="Page within these filters; follow next when needed"),
    ) -> Dict[str, Any]:
        """List existing tax reports, optionally scoped to a period and report type.

        Date filters include reports wholly inside the given period. Check the returned
        dates and type; if no exact period exists, inspect the company's filing frequency.
        German companies: an existing draft can be passed to generate_finanzamt_preview without
        creating a duplicate. Polish companies: pass a JPK_V7 report to get_polish_jpk_register.
        """
        api = ctx.request_context.lifespan_context["api"]
        
        company_id = api.company_id
        if not company_id:
            return NO_COMPANY_ERROR
        taxes_url = reports_url(company_id)

        params = {"page": page}
        for key, value in (("date_from", date_from), ("date_to", date_to), ("type", report_type)):
            if value is not None:
                params[key] = value
        return await api.arequest("GET", taxes_url, params=params)

    @mcp.tool(
        title="Get Tax Report",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_tax_report(
        ctx: Context,
        report_id: str = Field(description="Public ID of the tax report to retrieve")
    ) -> Dict[str, Any]:
        """
        Retrieve a specific tax report.
        
        Args:
            report_id: Public ID of the tax report to retrieve
            
        Returns:
            Tax report details
        """
        api = ctx.request_context.lifespan_context["api"]
        
        company_id = api.company_id
        if not company_id:
            return NO_COMPANY_ERROR

        result = await api.arequest("GET", reports_url(company_id, f"{report_id}/"))
        return _enrich_report_download_url(result, api=api, report_id=report_id, company_id=company_id)

    @mcp.tool(
        title="Get Filed Report Changes",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_filed_report_changes(
        ctx: Context,
        report_id: str = Field(description="Public ID of a filed UStVA (advance VAT return)"),
    ) -> Dict[str, Any]:
        """
        What changed in a filed UStVA since it was sent to ELSTER.

        A late document keeps its legal date, also in a filed month. This compares the figures sent with today's,
        per Kennzahl, and says whether a correction is due: a higher tax due must be corrected without delay
        (§ 153 AO). Other reports, and returns not filed yet, answer changed false.

        Args:
            report_id: Public ID of the filed UStVA

        Returns:
            changed, correction_required, and the changed lines (kz, filed, now)
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return NO_COMPANY_ERROR
        return await api.arequest("GET", reports_url(company_id, f"{report_id}/changes-since-filing/"))

    @mcp.tool(
        title="Validate Tax Number",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def validate_tax_number(
        ctx: Context,
        tax_number: str = Field(description="German business tax number (Steuernummer) to validate"),
        region_code: str = Field(
            description=(
                "Two-letter code of the federal state (Bundesland) whose Finanzamt issued "
                "the number, e.g. BE, BY or NW; see list_tax_states. Not a country code."
            )
        ),
    ) -> Dict[str, Any]:
        """
        Check a German tax number (Steuernummer) with the ELSTER validator.

        Returns {"valid": true|false, "message": ...}. An invalid number is a
        normal result, not an error.
        """
        api = ctx.request_context.lifespan_context["api"]
        
        validate_url = urljoin(config.api_base_url, "api/v1/taxes/check-tax-number/")
        
        validation_data = {
            "tax_number": tax_number,
            "region_code": region_code
        }
        
        response = api._make_request("POST", validate_url, json_data=validation_data)
        # The API answers with the bare JSON string "Tax number is valid", and
        # with the reason as a 400 body when the number is invalid.
        if isinstance(response, str):
            return {"valid": True, "message": response}
        if isinstance(response, dict) and response.get("status_code") == 400:
            return {"valid": False, "message": first_text(response.get("detail")) or response.get("error")}
        return as_object(response)

    @mcp.tool(
        title="Generate Finanzamt Preview",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def generate_finanzamt_preview(
        ctx: Context,
        report_id: str = Field(description="Public ID of the tax report to generate a preview for")
    ) -> CallToolResult:
        """
        Generate a test Finanzamt preview for a tax report.

        Generates and stores a temporary preview PDF without submitting the report.
        Returns its first page as an inline image in the API's format (normally JPEG)
        plus a downloadUrl for the full PDF. Repeated calls create new preview files.
        """
        api = ctx.request_context.lifespan_context["api"]

        if not report_id or not isinstance(report_id, str) or not report_id.strip():
            raise ToolError("Invalid report ID")

        company_id = api.company_id
        if not company_id:
            raise ToolError(NO_COMPANY_ERROR["error"])
        preview_url = reports_url(company_id, f"{report_id}/generate-preview-url/")

        try:
            result = api._make_request("POST", preview_url)
            if not result.get("downloadUrl"):
                raise ToolError("Preview generation failed: no download URL returned")

            content: list = []
            preview_b64 = result.get("previewImage")
            if preview_b64:
                content.append(ImageContent(
                    type="image",
                    data=preview_b64,
                    mimeType=result.get("mimeType") or "image/jpeg",
                ))

            meta = {k: v for k, v in result.items() if k != "previewImage"}
            content.append(TextContent(
                type="text",
                text=json.dumps(meta, ensure_ascii=False),
            ))

            return CallToolResult(content=content)
        except ToolError:
            # Deliberate failures remain useful to clients on both protocol eras.
            raise
        except requests.exceptions.RequestException as e:
            logger.error("Failed to generate tax report preview: %s", e)
            if hasattr(e, "response") and e.response is not None:
                logger.error("Response: %s", e.response.text)
            raise ToolError("Could not generate the tax preview. Please try again.") from e
        except Exception as e:
            logger.error("Error generating tax report preview: %s", e)
            raise ToolError(
                "Could not generate the tax preview. Please try again or contact Norman support."
            ) from e

    @mcp.tool(
        title="Submit Tax Report to Finanzamt",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def submit_tax_report(
        ctx: Context,
        report_id: str = Field(description="Public ID of the tax report to submit")
    ) -> Dict[str, Any]:
        """
        Submit a tax report to the Finanzamt.
        
        Args:
            report_id: Public ID of the tax report to submit
            
        Returns:
            Response from the submission request and a link to the tax report from reportFile to download.
            A 403 means either an unconfirmed email address (see resend_email_confirmation)
            or that a paid subscription is required to file the report.
        """
        api = ctx.request_context.lifespan_context["api"]
        
        company_id = api.company_id
        if not company_id:
            return NO_COMPANY_ERROR
        submit_url = reports_url(company_id, f"{report_id}/submit-report/")

        try:
            result = api._make_request("POST", submit_url)
            return _enrich_report_download_url(result, api=api, report_id=report_id, company_id=company_id)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                if _error_code(e.response) == "email_not_verified":
                    return EMAIL_NOT_CONFIRMED_ERROR
                return {
                    "error": "Subscription required",
                    "message": "Tax report submission is unavailable with the account's current entitlement.",
                    "status_code": 403
                }
            raise

    @mcp.tool(
        title="Resend Email Confirmation",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def resend_email_confirmation(ctx: Context) -> Dict[str, Any]:
        """
        Mail a new confirmation link to the user's login email.

        Filing tax reports and sending invoices need a confirmed email address; a paid
        plan confirms it without the mail. Ask the user to open the link in the email.

        Returns:
            verified: true when an address is already confirmed; then nothing is sent.
        """
        api = ctx.request_context.lifespan_context["api"]
        url = urljoin(config.api_base_url, "api/v1/auth/resend-confirmation/")
        try:
            return api._make_request("POST", url)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                return RESEND_TOO_SOON_ERROR
            raise

    @mcp.tool(
        title="List German Tax States",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_tax_states(ctx: Context) -> Dict[str, Any]:
        """
        Get list of available tax states.
        
        Returns:
            List of tax states
        """
        api = ctx.request_context.lifespan_context["api"]
        
        states_url = urljoin(config.api_base_url, "api/v1/taxes/states/")
        
        return await api.arequest("GET", states_url)

    @mcp.tool(
        title="List Tax Settings",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_tax_settings(ctx: Context) -> Dict[str, Any]:
        """
        Get list of tax settings for the current company.
        
        Returns:
            List of company tax settings
        """
        api = ctx.request_context.lifespan_context["api"]
        
        settings_url = urljoin(config.api_base_url, "api/v1/taxes/tax-settings/")
        
        return await api.arequest("GET", settings_url)

    @mcp.tool(
        title="Update Tax Setting",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def update_tax_setting(
        ctx: Context,
        setting_id: str = Field(description="Public ID of the tax setting to update"),
        tax_type: Optional[str] = Field(default=None, description="Type of tax (e.g. 'sales')"),
        vat_type: Optional[str] = Field(default=None, description="VAT type (e.g. 'vat_subject')"),
        vat_percent: Optional[float] = Field(default=None, description="VAT percentage"),
        start_tax_report_date: Optional[str] = Field(default=None, description="Start date for tax reporting (YYYY-MM-DD)"),
        reporting_frequency: Optional[str] = Field(default=None, description="Frequency of reporting (e.g. 'monthly')")
    ) -> Dict[str, Any]:
        """
        Update a tax setting for the selected company. Read its country and supported settings first.
        Review the report through its country-specific tools before any submission.
        For a Polish company it changes nothing itself: it proposes this year's VAT status and JPK_V7 frequency,
        and the owner applies it in Norman through the returned openUrl (propose_tax_setting_change).
        
        Args:
            setting_id: Public ID of the tax setting to update
            tax_type: Type of tax (e.g. "sales"); Options: "sales", "trade", "income", "profit_loss"
            vat_type: API VAT status for the selected company; use the values returned by get_tax_settings.
            vat_percent: VAT percentage supported for the company country (Germany and Poland differ).
            start_tax_report_date: Start date for tax reporting (YYYY-MM-DD)
            reporting_frequency: Frequency of reporting (e.g. "monthly"), Options: "monthly", "quarterly", "yearly"
            
        Returns:
            Updated tax setting
        """
        api = ctx.request_context.lifespan_context["api"]
        
        setting_url = urljoin(
            config.api_base_url,
            f"api/v1/taxes/tax-settings/{setting_id}/"
        )
        if await company_country(api) == "PL":
            return await propose_vat_status(
                api, setting_url, vat_type=vat_type, reporting_frequency=reporting_frequency,
                others={
                    "tax_type": tax_type, "vat_percent": vat_percent, "start_tax_report_date": start_tax_report_date,
                },
            )
        
        update_data = {}
        if tax_type:
            update_data["taxType"] = tax_type
        if vat_type:
            update_data["vatType"] = vat_type
        if vat_percent is not None:
            update_data["vatPercent"] = vat_percent
        if start_tax_report_date:
            update_data["startTaxReportDate"] = start_tax_report_date
        if reporting_frequency:
            update_data["reportingFrequency"] = reporting_frequency
            
        # Only make request if there are changes
        if update_data:
            return api._make_request("PATCH", setting_url, json_data=update_data)
        else:
            return {"message": "No changes to apply"}

    @mcp.tool(
        title="Get Company Tax Statistics",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_company_tax_statistics(ctx: Context) -> Dict[str, Any]:
        """
        Get tax statistics for the company.
        
        Returns:
            Company tax statistics data
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        stats_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/company-tax-statistic/"
        )
        
        return await api.arequest("GET", stats_url)

    @mcp.tool(
        title="Get Next VAT Report",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_vat_next_report(ctx: Context) -> Dict[str, Any]:
        """
        The next VAT return: its period, VAT amount and deadline. A German company's UStVA; a
        Polish VAT payer's JPK_V7M or JPK_V7K, due the 25th (next working day); none for a Polish
        company exempt from VAT. For "when is my next tax deadline?" also check list_tax_reports:
        a Polish company's PIT or CIT advance and ZUS DRA fall due on the 20th.
        
        Returns:
            VAT next report amount data
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        vat_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/vat-next-report-amount/"
        )
        
        return await api.arequest("GET", vat_url)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    async def get_vat_proportion(ctx: Context) -> dict[str, Any]:
        """
        Polish VAT payers with both taxed and VAT-exempt (art. 43) sales: the VAT deduction proportion of
        art. 90 by tax year. For each year: the percent purchases marked "proportion" deduct, where it comes
        from (computed from the previous year's turnover, estimated by the owner, or as filed), the turnover
        it is worked out of, and for the last closed year the art. 91 correction Norman puts into the next
        January's JPK_V7. Norman prepares the figures; the owner checks and files.

        Returns:
            hasExemptSales, usesProportion and years[] with percent, source, turnovers, settings, correction
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        return await api.arequest(
            "GET", urljoin(config.api_base_url, f"api/v1/companies/{company_id}/taxes/vat-proportion/"),
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False))
    async def update_vat_proportion(  # noqa: PLR0913 - one argument per choice the endpoint takes
        ctx: Context,
        year: int = Field(description="Tax year the choices are for, e.g. 2027"),
        estimated_percent: int | None = Field(
            default=None, ge=0, le=100,
            description="Estimated proportion for the year (art. 90 ust. 8-9), when the previous year had less "
            "than PLN 30,000 turnover or is unrepresentative. The owner must notify the tax office.",
        ),
        clear_estimate: bool | None = Field(
            default=None, description="True to drop the estimate and use the previous year's turnover again.",
        ),
        round_to_whole: bool | None = Field(
            default=None, description="Take above 98 % as 100 % and 2 % or less as 0 % (art. 90 ust. 10).",
        ),
        previous_taxed_turnover: str | None = Field(
            default=None, description="Previous year's turnover with the right to deduct, PLN net, e.g. '120000.00'",
        ),
        previous_exempt_turnover: str | None = Field(
            default=None, description="Previous year's VAT-exempt turnover, PLN net, e.g. '30000.00'",
        ),
        fixed_asset_correction: str | None = Field(
            default=None,
            description="The year's correction of fixed assets' input VAT (art. 91 ust. 2), PLN, + or -, e.g. "
            "'-120.00'. Goes into K_44 of the next January.",
        ),
    ) -> dict[str, Any]:
        """
        Set the owner's choices about the Polish VAT deduction proportion (art. 90) of one tax year. Only
        what is given changes. Confirm the numbers with the user first: they come from the user's records.
        It proposes them: the owner applies the proposal in Norman through the returned openUrl.

        Returns:
            The year as get_vat_proportion describes it
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        data: dict[str, Any] = {}
        if clear_estimate:
            data["estimatedPercent"] = None
        elif estimated_percent is not None:
            data["estimatedPercent"] = estimated_percent
        given = {
            "roundToWhole": round_to_whole,
            "previousTaxedTurnover": previous_taxed_turnover,
            "previousExemptTurnover": previous_exempt_turnover,
            "fixedAssetCorrection": fixed_asset_correction,
        }
        data |= {key: value for key, value in given.items() if value is not None}
        if not data:
            return {"message": "Nothing to change."}
        if await company_country(api) == "PL":
            return await propose(api, "vat_proportion", {"year": year, **data})
        return await api.arequest(
            "PUT", urljoin(config.api_base_url, f"api/v1/companies/{company_id}/taxes/vat-proportion/{year}/"),
            json_data=data,
        )
