import json
import logging
import requests
from typing import Dict, Any, Optional
from urllib.parse import urljoin
from pydantic import Field
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations

from norman_mcp.context import Context
from norman_mcp import config

logger = logging.getLogger(__name__)


def _enrich_report_download_url(data: dict, api=None, report_id: str | None = None) -> dict:
    """Add a presigned downloadUrl for the submitted tax report PDF."""
    if not isinstance(data, dict):
        return data
    if api and report_id and data.get("reportFile"):
        try:
            dl_endpoint = urljoin(
                config.api_base_url,
                f"api/v1/taxes/reports/{report_id}/download/",
            )
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
    async def list_tax_reports(ctx: Context) -> Dict[str, Any]:
        """List all available tax reports."""
        api = ctx.request_context.lifespan_context["api"]
        
        taxes_url = urljoin(config.api_base_url, "api/v1/taxes/reports/")
        
        return api._make_request("GET", taxes_url)

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
        
        report_url = urljoin(
            config.api_base_url,
            f"api/v1/taxes/reports/{report_id}/"
        )
        
        result = api._make_request("GET", report_url)
        return _enrich_report_download_url(result, api=api, report_id=report_id)

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
        tax_number: str = Field(description="Tax number to validate"),
        region_code: str = Field(description="Region code (e.g., DE for Germany)")
    ) -> Dict[str, Any]:
        """
        Validate a tax number for a specific region.
        
        Args:
            tax_number: Tax number to validate
            region_code: Region code (e.g., DE for Germany)
            
        Returns:
            Validation result
        """
        api = ctx.request_context.lifespan_context["api"]
        
        validate_url = urljoin(config.api_base_url, "api/v1/taxes/check-tax-number/")
        
        validation_data = {
            "tax_number": tax_number,
            "region_code": region_code
        }
        
        return api._make_request("POST", validate_url, json_data=validation_data)

    @mcp.tool(
        title="Generate Finanzamt Preview",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def generate_finanzamt_preview(
        ctx: Context,
        report_id: str = Field(description="Public ID of the tax report to generate a preview for")
    ) -> CallToolResult:
        """
        Generate a test Finanzamt preview for a tax report.

        Returns the preview as an inline PNG image (first page) plus a
        downloadUrl for the full PDF. The image is rendered directly in
        clients that support MCP ImageContent.
        """
        api = ctx.request_context.lifespan_context["api"]

        if not report_id or not isinstance(report_id, str) or not report_id.strip():
            raise ValueError("Invalid report ID")

        preview_url = urljoin(
            config.api_base_url,
            f"api/v1/taxes/reports/{report_id}/generate-preview-url/",
        )

        try:
            result = api._make_request("POST", preview_url)
            if not result.get("downloadUrl"):
                raise ValueError("Preview generation failed: no download URL returned")

            content: list = []
            preview_b64 = result.get("previewImage")
            if preview_b64:
                content.append(ImageContent(
                    type="image",
                    data=preview_b64,
                    mimeType="image/png",
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
            openWorldHint=False,
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
            If response status is 403, it means a paid subscription is required to file the report.
        """
        api = ctx.request_context.lifespan_context["api"]
        
        submit_url = urljoin(
            config.api_base_url,
            f"api/v1/taxes/reports/{report_id}/submit-report/"
        )
        
        try:
            result = api._make_request("POST", submit_url)
            return _enrich_report_download_url(result, api=api, report_id=report_id)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                return {
                    "error": "Subscription required",
                    "message": "You need a paid subscription to file tax reports. Please subscribe before submitting.",
                    "status_code": 403
                }
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
        
        return api._make_request("GET", states_url)

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
        
        return api._make_request("GET", settings_url)

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
        tax_type: Optional[str] = Field(description="Type of tax (e.g. 'sales')"),
        vat_type: Optional[str] = Field(description="VAT type (e.g. 'vat_subject')"),
        vat_percent: Optional[float] = Field(description="VAT percentage"),
        start_tax_report_date: Optional[str] = Field(description="Start date for tax reporting (YYYY-MM-DD)"),
        reporting_frequency: Optional[str] = Field(description="Frequency of reporting (e.g. 'monthly')")
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
        
        return api._make_request("GET", stats_url)

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
        
        return api._make_request("GET", vat_url) 