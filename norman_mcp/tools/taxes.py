import logging
import requests
from typing import Dict, Any, Optional
from urllib.parse import urljoin
from pydantic import Field
from mcp.server.fastmcp.utilities.types import Image
import io
from pdf2image import convert_from_bytes
from PIL import Image as PILImage

from norman_mcp.context import Context
from norman_mcp import config

logger = logging.getLogger(__name__)

def register_tax_tools(mcp):
    """Register all tax-related tools with the MCP server."""
    
    @mcp.tool()
    async def list_tax_reports(ctx: Context) -> Dict[str, Any]:
        """List all available tax reports."""
        api = ctx.request_context.lifespan_context["api"]
        
        taxes_url = urljoin(config.api_base_url, "api/v1/taxes/reports/")
        
        return api._make_request("GET", taxes_url)

    @mcp.tool()
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
        
        return api._make_request("GET", report_url)

    @mcp.tool()
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

    @mcp.tool()
    async def generate_finanzamt_preview(
        ctx: Context,
        report_id: str = Field(description="Public ID of the tax report to generate a preview for")
    ) -> Image:
        """
        Generate a test Finanzamt preview for a tax report and return it as an image.
        
        Args:
            report_id: Public ID of the tax report
            
        Returns:
            The tax report preview as an image in PNG format
        """
        api = ctx.request_context.lifespan_context["api"]
        
        # Validate report_id
        if not report_id or not isinstance(report_id, str) or not report_id.strip():
            raise ValueError("Invalid report ID")
        
        preview_url = urljoin(
            config.api_base_url,
            f"api/v1/taxes/reports/{report_id}/generate-preview/"
        )

        try:
            response = requests.post(
                preview_url,
                headers={"Authorization": f"Bearer {api.access_token}"},
                timeout=config.NORMAN_API_TIMEOUT
            )
            response.raise_for_status()
            
            # The response contains raw PDF bytes
            if isinstance(response.content, bytes) and len(response.content) > 0:
                # Convert PDF to image
                images = convert_from_bytes(response.content, dpi=150)
                
                # Get the first page as PIL Image
                first_page = images[0]
                
                # Convert to RGB and resize if needed to keep file size manageable
                first_page = first_page.convert('RGB')
                
                # Calculate new dimensions while maintaining aspect ratio
                width, height = first_page.size
                max_dim = 1000
                if width > max_dim or height > max_dim:
                    if width > height:
                        new_width = max_dim
                        new_height = int(height * (max_dim / width))
                    else:
                        new_height = max_dim
                        new_width = int(width * (max_dim / height))
                    first_page = first_page.resize((new_width, new_height), PILImage.LANCZOS)
                
                # Save as PNG to bytes buffer
                buffer = io.BytesIO()
                first_page.save(buffer, format="PNG", optimize=True)
                buffer.seek(0)
                
                # Return as Image
                return Image(data=buffer.getvalue(), format="png")
            else:
                raise ValueError("Preview generation failed or invalid response format")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to generate tax report preview: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise ValueError(f"Failed to generate tax report preview: {str(e)}")
        except Exception as e:
            logger.error(f"Error generating tax report preview: {str(e)}")
            raise ValueError(f"Error generating tax report preview: {str(e)}")

    @mcp.tool()
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
            return api._make_request("POST", submit_url)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                return {
                    "error": "Subscription required",
                    "message": "You need a paid subscription to file tax reports. Please subscribe before submitting.",
                    "status_code": 403
                }
            raise

    @mcp.tool()
    async def list_tax_states(ctx: Context) -> Dict[str, Any]:
        """
        Get list of available tax states.
        
        Returns:
            List of tax states
        """
        api = ctx.request_context.lifespan_context["api"]
        
        states_url = urljoin(config.api_base_url, "api/v1/taxes/states/")
        
        return api._make_request("GET", states_url)

    @mcp.tool()
    async def list_tax_settings(ctx: Context) -> Dict[str, Any]:
        """
        Get list of tax settings for the current company.
        
        Returns:
            List of company tax settings
        """
        api = ctx.request_context.lifespan_context["api"]
        
        settings_url = urljoin(config.api_base_url, "api/v1/taxes/tax-settings/")
        
        return api._make_request("GET", settings_url)

    @mcp.tool()
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

    @mcp.tool()
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

    @mcp.tool()
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