import logging
from typing import Any, Dict, Literal, Optional
from urllib.parse import urljoin
from datetime import date
from pydantic import Field

from mcp.types import ToolAnnotations
from norman_mcp.context import Context
from norman_mcp import config
from norman_mcp.tools.results import as_object
from norman_mcp.company_profile import without_company_personal_identifiers
from norman_mcp.tools.polish_settings import company_country, propose_company_details, summarize

logger = logging.getLogger(__name__)

# A tax advisor sees every client here too; stop after a few hundred entries.
COMPANIES_PAGE_SIZE = 100
COMPANIES_MAX_PAGES = 5


def _company_summary(company: Dict[str, Any], active_id: Optional[str]) -> Dict[str, Any]:
    """What tells the companies apart. The list endpoint returns full records
    (IBAN, tax numbers, members); none of that is needed to pick one."""
    company_id = company.get("publicId")
    return {
        "id": company_id,
        "name": company.get("name"),
        "legalForm": company.get("accountType"),
        "country": company.get("country"),
        "isSme": company.get("isSme"),
        "isArchived": company.get("isArchived"),
        "active": bool(company_id) and company_id == active_id,
    }


# A Polish company's tax settings among the company details: proposed, never written here (the API refuses them).
POLISH_TAX_DETAILS = ("vatNumber", "taxNumber", "activityStart", "isToNotifyTaxDeadlines")


async def _update_polish_company(
    api: Any, company_url: str, update_data: Dict[str, Any], tax_details: Dict[str, Any],
) -> Dict[str, Any]:
    """A Polish company: its NIP, EU VAT number, business start and reminders are proposed for the owner to apply in
    Norman; the other details are written as before."""
    answer = summarize(await propose_company_details(api, tax_details))
    other = {key: value for key, value in update_data.items() if key not in POLISH_TAX_DETAILS}
    if other:
        answer["company"] = without_company_personal_identifiers(
            api._make_request("PATCH", company_url, json_data=other)  # noqa: SLF001 - the client's write path
        )
        answer["updated"] = sorted(other)
    return answer


def register_company_tools(mcp):
    """Register all company-related tools with the MCP server."""
    from norman_mcp.tools.financial_overview import register_financial_overview_tools

    register_financial_overview_tools(mcp)
    
    @mcp.tool(
        title="Get Company Details",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_company_details(ctx: Context) -> Dict[str, Any]:
        """Get detailed information about the user's company."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        return without_company_personal_identifiers(await api.arequest("GET", company_url))

    @mcp.tool(
        title="List My Companies",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_companies(
        ctx: Context,
        include_archived: bool = Field(
            default=False,
            description="Also list archived (wound-down) companies. They stay readable but cannot be made active.",
        ),
    ) -> Dict[str, Any]:
        """
        List every company the user can work in: the ones they own or are a member of,
        and the ones they advise as a tax advisor. The most recently used company comes
        first; `active` marks the one the other tools currently work on.

        Pass a returned id to switch_company to work in another company.
        """
        api = ctx.request_context.lifespan_context["api"]
        companies_url = urljoin(config.api_base_url, "api/v1/companies/")
        params: Dict[str, Any] = {"pageSize": COMPANIES_PAGE_SIZE}
        if include_archived:
            params["includeArchived"] = "true"

        companies = []
        total = 0
        for page in range(1, COMPANIES_MAX_PAGES + 1):
            response = await api.arequest("GET", companies_url, params={**params, "page": page})
            if isinstance(response, dict) and response.get("error"):
                if not companies:
                    return response
                break
            if isinstance(response, list):
                companies.extend(response)
                total = len(companies)
                break
            companies.extend(response.get("results") or [])
            total = response.get("count") or len(companies)
            if not response.get("next"):
                break

        active_id = api.company_id
        result: Dict[str, Any] = {
            "count": total,
            "activeCompanyId": active_id,
            "companies": [_company_summary(company, active_id) for company in companies],
        }
        if total > len(companies):
            result["note"] = (
                f"Showing the {len(companies)} most recently used of {total} companies. "
                "Tax advisors get every client from list_tax_advisor_clients."
            )
        return result

    @mcp.tool(
        title="Get Company Balance",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_company_balance(ctx: Context) -> Dict[str, Any]:
        """
        Get the current balance of the company.
        
        Returns:
            Company balance information
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        balance_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/balance/"
        )
        
        return await api.arequest("GET", balance_url)

    @mcp.tool(
        title="Update Company Details",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def update_company_details(
        ctx: Context,
        name: Optional[str] = None,
        profession: Optional[str] = None,
        address: Optional[str] = None,
        zip_code: Optional[str] = None,
        city: Optional[str] = None,
        country: Optional[str] = None,
        vat_id: Optional[str] = None,
        tax_id: Optional[str] = Field(default=None, description="Business tax number: German Steuernummer or Polish NIP. Enter personal identifiers only in authenticated forms."),
        phone: Optional[str] = None,
        tax_state: Optional[str] = None,
        activity_start: Optional[date] = Field(default=None, description="Business activity start date (YYYY-MM-DD)"),
        chart_of_accounts: Optional[str] = Field(default=None, description="Country-supported chart template from list_coa_templates: SKR03/SKR04 or PL_KPIR/PL_FULL."),
        datev_advisor_number: Optional[str] = Field(default=None, description="German companies only: DATEV tax advisor number"),
        datev_client_number: Optional[str] = Field(default=None, description="German companies only: DATEV client/Mandant number"),
        notify_tax_deadlines: Optional[bool] = Field(
            default=None,
            description=(
                "Tax deadline reminders. German companies: e-mails a week before and on the due date "
                "of each UStVA and ZM. Polish companies: in the app, by push and by e-mail, a few days "
                "before and on the day, for the JPK_V7, VAT-UE, PIT and CIT advances, ZUS DRA, annual "
                "PIT and CIT-8. False turns them off."
            ),
        ),
    ) -> Dict[str, Any]:
        """Update company information.

        Use a chart_of_accounts template supported by the company country. DATEV advisor/client numbers are German-only.
        notify_tax_deadlines switches the tax deadline reminders on or off: the UStVA and ZM e-mails
        of a German company, the JPK_V7, VAT-UE, PIT, CIT and ZUS reminders of a Polish one.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        
        update_data = {}
        
        if name:
            update_data["name"] = name
        if profession:
            update_data["profession"] = profession
        if address:
            update_data["address"] = address
        if zip_code:
            update_data["zipCode"] = zip_code
        if city:
            update_data["city"] = city
        if country:
            update_data["country"] = country
        if vat_id:
            update_data["vatNumber"] = vat_id
        if tax_id:
            update_data["taxNumber"] = tax_id
        if phone:
            update_data["phoneNumber"] = phone
        if tax_state:
            update_data["taxState"] = tax_state
        if activity_start:
            # A date object is not JSON serializable: the client used to fail
            # in json.dumps before sending, and this tool still said success.
            update_data["activityStart"] = activity_start.isoformat()
        if chart_of_accounts:
            update_data["chartOfAccounts"] = chart_of_accounts
        if datev_advisor_number is not None:
            update_data["datevAdvisorNumber"] = datev_advisor_number
        if datev_client_number is not None:
            update_data["datevClientNumber"] = datev_client_number
        if notify_tax_deadlines is not None:
            update_data["isToNotifyTaxDeadlines"] = notify_tax_deadlines

        if POLISH_TAX_DETAILS & update_data.keys() and await company_country(api) == "PL":
            return await _update_polish_company(api, company_url, update_data, {
                "tax_id": tax_id, "vat_id": vat_id, "activity_start": activity_start,
                "notify_tax_deadlines": notify_tax_deadlines,
            })

        if not update_data:
            current_data = without_company_personal_identifiers(await api.arequest("GET", company_url))
            return {"message": "No fields provided for update.", "company": current_data}
        
        updated_company = without_company_personal_identifiers(
            api._make_request("PATCH", company_url, json_data=update_data)
        )
        if isinstance(updated_company, dict) and updated_company.get("error"):
            return updated_company
        return {"message": "Company updated successfully", "company": updated_company}

    @mcp.tool(
        title="List Company Categories",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_company_categories(
        ctx: Context,
        cashflow_type: Optional[str] = Field(default=None, description="Filter by cashflow type: INCOME or EXPENSE"),
        chart_template: Optional[str] = Field(
            default=None,
            description="Keep only rows provisioned from this chart of accounts: 'skr03', 'skr04', 'PL_FULL'",
        ),
        include_inactive: bool = Field(
            default=False,
            description="Also return hidden categories (isActive=false). Needed before unhiding anything.",
        ),
    ) -> Dict[str, Any]:
        """
        List categories from the selected company chart (SKR03/SKR04, PL_KPIR or PL_FULL).
        Use these company-specific IDs whenever usesCompanyChart or isSme is true.
        Each category has a code (e.g. '4200'), name, cashflow type, and sourceTemplate —
        the chart of accounts it was provisioned from ('' for hand-made ones). A company
        showing both SKR03 and SKR04 accounts can be cleaned up with
        set_company_categories_visibility.

        Hidden categories are omitted unless include_inactive=true.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        categories_url = urljoin(
            config.api_base_url,
            "api/v1/accounting/company-categories/"
        )
        
        params = {"pageSize": 200}
        if cashflow_type:
            params["cashflowType"] = cashflow_type
        if chart_template:
            params["chartTemplate"] = chart_template
        if include_inactive:
            params["includeInactive"] = "true"
        
        return await api.arequest("GET", categories_url, params=params)

    @mcp.tool(
        title="List Company Category Templates",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_coa_templates(ctx: Context) -> Dict[str, Any]:
        """List available Chart of Accounts templates (e.g. SKR03, SKR04, PL_KPIR, PL_FULL) supported for the selected company."""
        api = ctx.request_context.lifespan_context["api"]
        
        templates_url = urljoin(
            config.api_base_url,
            "api/v1/accounting/company-categories/templates/"
        )
        
        # The API answers with a bare list of templates.
        return as_object(await api.arequest("GET", templates_url))

    @mcp.tool(
        title="Trigger DATEV Export",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def trigger_datev_export(
        ctx: Context,
        date_from: str = Field(description="Start date for export in YYYY-MM-DD format"),
        date_to: str = Field(description="End date for export in YYYY-MM-DD format"),
        include_documents: bool = Field(default=True, description="Whether to include attached documents in the ZIP"),
        advisor_number: Optional[str] = Field(
            default=None,
            description="DATEV advisor number; uses the value saved on the company when omitted",
        ),
        client_number: Optional[str] = Field(
            default=None,
            description="DATEV client/Mandant number; uses the value saved on the company when omitted",
        ),
        skr_variant: Optional[str] = Field(
            default=None,
            description="SKR03 or SKR04; uses the company's chart of accounts when omitted",
        ),
        source: Literal["auto", "ledger", "transactions"] = "auto",
    ) -> Dict[str, Any]:
        """
        Export DATEV and return a downloadUrl valid for one hour. By default GmbH/UG
        use the complete Ledger, including opening, manual, payroll, depreciation and
        closing entries; other companies use finalized transactions. Ledger exports
        are structurally checked before download; show validation findings to the user.
        include_documents adds a ZIP with receipts. Nothing is sent to DATEV or an advisor.
        Use source=transactions only when the user explicitly wants that narrower export.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        company = await api.arequest("GET", company_url)
        if company.get("error"):
            return company

        resolved_advisor_number = advisor_number or company.get("datevAdvisorNumber")
        resolved_client_number = client_number or company.get("datevClientNumber")
        if not resolved_advisor_number or not resolved_client_number:
            return {
                "error": "DATEV advisor number and client number are required.",
                "action": (
                    "Provide advisor_number and client_number, or save them on the company "
                    "with update_company_details first."
                ),
            }

        # The company serializes its chart as {"publicId", "name", "code"}; the
        # object itself used to be stringified here, which rejected every SME
        # with a chart unless skr_variant was passed explicitly.
        chart = company.get("chartOfAccounts")
        chart_code = chart.get("code") if isinstance(chart, dict) else chart
        resolved_skr_variant = str(skr_variant or chart_code or "SKR04").upper()
        if resolved_skr_variant not in {"SKR03", "SKR04"}:
            return {"error": "skr_variant must be SKR03 or SKR04."}

        use_ledger = source == "ledger" or (source == "auto" and company.get("isSme"))
        if use_ledger:
            if skr_variant and resolved_skr_variant != str(chart_code or "").upper():
                return {"error": "Ledger export uses the company's chart; a different skr_variant cannot be applied."}
            export_url = urljoin(
                config.api_base_url,
                f"api/v1/companies/{company_id}/accounting/ledger/datev-export/",
            )
            # Do not fall back to a transactions-only export if the API is old or
            # preflight fails: that would silently omit Ledger-only sources.
            return await api.arequest("POST", export_url, json_data={
                "dateFrom": date_from, "dateTo": date_to,
                "advisorNumber": resolved_advisor_number, "clientNumber": resolved_client_number,
                "kind": "journal", "includeDocuments": include_documents,
                "responseFormat": "download_url",
            })

        export_url = urljoin(config.api_base_url, "api/v1/accounting/datev-export/")
        
        export_data = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "includeDocuments": include_documents,
            "advisorNumber": resolved_advisor_number,
            "clientNumber": resolved_client_number,
            "skrVariant": resolved_skr_variant,
            # A ZIP cannot travel through a JSON tool result (the client used to
            # replace it with {"success": true}); the API stores the file and
            # returns a one-hour download link instead.
            "responseFormat": "download_url",
        }
        
        return await api.arequest("POST", export_url, json_data=export_data)
