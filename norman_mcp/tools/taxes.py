import json
import logging
import requests
from typing import Dict, Any, Optional
from urllib.parse import urljoin
from pydantic import Field
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations

from norman_mcp.context import Context
from norman_mcp import config
from norman_mcp.tools.results import as_object, is_failure

logger = logging.getLogger(__name__)


NO_COMPANY_ERROR = {"error": "No company available. Please authenticate first."}


def reports_url(company_id: str, suffix: str = "") -> str:
    """The company-scoped tax reports route.

    The unscoped api/v1/taxes/reports/ ignores X-Company-Id and serves the
    user's OLDEST company, so after switch_company -- or for anyone whose
    last-active company is not their first -- these tools listed, previewed
    and submitted another company's reports. The MCP apps already use this.
    """
    return urljoin(config.api_base_url, f"api/v1/companies/{company_id}/taxes/reports/{suffix}")


async def _enrich_report_download_url(
    data: dict, api=None, report_id: str | None = None, company_id: str | None = None
) -> dict:
    """Add a presigned downloadUrl for the submitted tax report PDF."""
    if not isinstance(data, dict):
        return data
    if api and report_id and company_id and data.get("reportFile"):
        dl_endpoint = reports_url(company_id, f"{report_id}/download/")
        dl_resp = await api.arequest("GET", dl_endpoint)
        if isinstance(dl_resp, dict) and dl_resp.get("url"):
            data["downloadUrl"] = dl_resp["url"]
        else:
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
        report_type: Optional[str] = Field(default=None, description="Report type, e.g. ADVANCED_SALEX_TAX for German monthly/quarterly VAT"),
        status: Optional[str] = Field(default=None, description="NOT_COMPLETED, SUBMIT, PAID, SUBMIT_AND_PAID or REQUIRE_CORRECTION"),
        page: int = Field(default=1, ge=1, description="Page within these filters; follow next when needed"),
    ) -> Dict[str, Any]:
        """List the selected company's tax reports, optionally scoped to a period, type or status.

        Date filters include reports wholly inside the given period. Check the returned
        dates and type; if no exact period exists, inspect the company's filing frequency.
        An existing draft can be passed to generate_finanzamt_preview without creating a duplicate.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return NO_COMPANY_ERROR

        params: Dict[str, Any] = {"page": page}
        for key, value in (("date_from", date_from), ("date_to", date_to), ("type", report_type), ("status", status)):
            if value is not None:
                params[key] = value
        return await api.arequest("GET", reports_url(company_id), params=params)

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
        return await _enrich_report_download_url(
            result, api=api, report_id=report_id, company_id=company_id
        )

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

        response = await api.arequest("POST", validate_url, json_data=validation_data)
        # The API answers 201 with the bare JSON string "Tax number is valid",
        # and 400 with the reason as a bare string.
        if isinstance(response, str):
            return {"valid": True, "message": response}
        if (
            isinstance(response, dict)
            and response.get("status_code") == 400
            and isinstance(response.get("detail"), str)
        ):
            return {"valid": False, "message": response["detail"]}
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
            raise ValueError("Invalid report ID")

        company_id = api.company_id
        if not company_id:
            raise ValueError(NO_COMPANY_ERROR["error"])
        preview_url = reports_url(company_id, f"{report_id}/generate-preview-url/")

        try:
            result = await api.arequest("POST", preview_url)
            if is_failure(result):
                # Keep the API's reason (e.g. an ELSTER validation message)
                # instead of the generic "no download URL" below.
                raise ValueError(json.dumps(result, ensure_ascii=False, default=str))
            if not result.get("downloadUrl"):
                raise ValueError("Preview generation failed: no download URL returned")

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
        except requests.exceptions.RequestException as e:
            logger.error("Failed to generate tax report preview: %s", e)
            if hasattr(e, "response") and e.response is not None:
                logger.error("Response: %s", e.response.text)
            raise ValueError(f"Failed to generate tax report preview: {e}")
        except Exception as e:
            logger.error("Error generating tax report preview: %s", e)
            raise ValueError(f"Error generating tax report preview: {e}")

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
            A 403 carries the API's reason and code, e.g. that the plan does not include
            filing; tell the user that reason instead of retrying.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return NO_COMPANY_ERROR

        # The client returns API errors (the 403 reason and code included)
        # instead of raising, so there is nothing to catch here.
        result = await api.arequest("POST", reports_url(company_id, f"{report_id}/submit-report/"))
        return await _enrich_report_download_url(
            result, api=api, report_id=report_id, company_id=company_id
        )

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
        Update a tax setting. Always generate a preview of the tax report @generate_finanzamt_preview before submitting it to the Finanzamt.
        
        Args:
            setting_id: Public ID of the tax setting to update
            tax_type: Type of tax (e.g. "sales"); Options: "sales", "trade", "income", "profit_loss"
            vat_type: VAT type (e.g. "vat_subject"), Options: "vat_subject", "kleinunternehmer", "vat_exempt"
            vat_percent: VAT percentage; Options: 0, 7, 19
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
            return await api.arequest("PATCH", setting_url, json_data=update_data)
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
        Get the VAT amount for the next report period.
        
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
