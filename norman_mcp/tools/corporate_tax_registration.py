import logging
from typing import Any
from urllib.parse import urljoin

from norman_mcp.context import Context
from pydantic import Field

from norman_mcp import config

logger = logging.getLogger(__name__)

NORMAN_AGENT_SOURCE = "norman_agent"

# Small, stable enums — documented here rather than via a backend choices endpoint.
CORPORATE_CHOICES: dict[str, dict[str, str]] = {
    "legalForm": {"gmbh": "GmbH", "ug": "UG (haftungsbeschränkt)"},
    "taxationMethod": {
        "soll": "Sollversteuerung (VAT due when invoiced — the default)",
        "ist": "Istversteuerung (VAT due when paid)",
    },
    "bankAccountHolderRole": {"1": "The company itself", "99": "Someone else"},
    "salutation": {"1": "Herr", "2": "Frau"},
    "shareholderType": {"natural": "Natural person", "legal": "Legal entity (a company)"},
}

PERSON_SHAPE = (
    "Person dict keys (camelCase): salutation ('1' Herr / '2' Frau), firstName, lastName, "
    "dob (YYYY-MM-DD, adults only), taxId (11-digit steuerliche IdNr, optional), street, "
    "houseNumber, additional, postalCode, city, country (ISO2, default DE)"
)


def _corporate_url(path: str = "") -> str:
    return urljoin(config.api_base_url, f"api/v1/corporate-tax-registrations/{path}")


def _app_url(path: str = "") -> str:
    base = (
        "https://app.norman.finance/"
        if config.NORMAN_ENVIRONMENT.lower() == "production"
        else "https://dev.norman.finance/"
    )
    return urljoin(base, path)


def _clean(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def register_corporate_tax_registration_tools(mcp):
    """Register corporate Fragebogen zur steuerlichen Erfassung (FsE KapG) tools.

    Who files one: every newly founded GmbH/UG must register with its Finanzamt to get a
    Steuernummer (this is the corporate variant of the Fragebogen; self-employed users use the
    tax_registration tools instead). The flow is server-authoritative: every response carries
    `sections` (company / registration / representatives / shareholders / financials /
    vatAndBank, each `complete` + `missing` camelCase field names) and `status`
    (data_collection → data_complete → submitted). Navigate by `sections.missing`; never track
    progress yourself.

    Orchestration: get_corporate_tax_registration → create_corporate_tax_registration
    (link the incorporation if there is one — it prefills most of the form) → fill the
    sections (update_corporate_company / update_corporate_registration_details /
    set_corporate_people / update_corporate_financials / update_corporate_vat_and_bank) →
    get_corporate_submission_link. IMPORTANT: there is deliberately NO submit tool — the
    questionnaire is e-filed to the Finanzamt via ELSTER, and that final, binding step happens
    only in the Norman app where the user reviews the ELSTER preview and presses Submit
    themselves. Always finish by handing over the submission link.
    """

    @mcp.tool()
    async def get_corporate_tax_registration(ctx: Context) -> dict[str, Any]:
        """Get the user's corporate tax registration (Fragebogen), if any. Call this FIRST.

        A "not found" response means there is none — offer to start one with
        create_corporate_tax_registration. Otherwise resume from `sections.missing`.
        `status` == 'submitted' means it was already e-filed; `reportUrl` carries the
        transmission protocol PDF.
        """
        api = ctx.request_context.lifespan_context.get("api")
        return api._make_request("GET", _corporate_url("my/"))

    @mcp.tool()
    async def get_corporate_tax_registration_choices(ctx: Context) -> dict[str, Any]:
        """Get the valid values for the corporate Fragebogen enum fields (value → label)."""
        return CORPORATE_CHOICES

    @mcp.tool()
    async def create_corporate_tax_registration(
        ctx: Context,
        incorporation_public_id: str | None = Field(
            default=None,
            description=(
                "Link to the GmbH/UG incorporation (publicId) to prefill from it — "
                "always pass it when one exists."
            ),
        ),
    ) -> dict[str, Any]:
        """Start the corporate Fragebogen. 400 if an active one already exists (use
        get_corporate_tax_registration).

        When linked to an incorporation, the company data, notary date, capital, shareholders
        and managing directors are prefilled — review `sections.missing` afterwards and only
        ask the user for what is still open.
        """
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean({"source": NORMAN_AGENT_SOURCE, "incorporation": incorporation_public_id})
        return api._make_request("POST", _corporate_url(), json_data=payload)

    @mcp.tool()
    async def update_corporate_company(  # noqa: PLR0913
        ctx: Context,
        public_id: str = Field(description="Corporate tax registration publicId"),
        legal_form: str | None = Field(default=None, description="'gmbh' or 'ug'"),
        company_name: str | None = Field(default=None, description="Firma exactly as notarized"),
        seat_city: str | None = Field(default=None, description="Sitz der Gesellschaft (city)"),
        business_street: str | None = Field(default=None),
        business_house_number: str | None = Field(default=None),
        business_additional: str | None = Field(default=None),
        business_postal_code: str | None = Field(default=None),
        business_city: str | None = Field(default=None),
        management_address_same: bool | None = Field(
            default=None,
            description="True when the management (Geschäftsleitung) sits at the business address",
        ),
        management_street: str | None = Field(default=None),
        management_house_number: str | None = Field(default=None),
        management_additional: str | None = Field(default=None),
        management_postal_code: str | None = Field(default=None),
        management_city: str | None = Field(default=None),
        phone: str | None = Field(default=None, description="Company phone, international format"),
        email: str | None = Field(default=None, description="Delivery email for the confirmation PDF (not e-filed)"),
        website: str | None = Field(default=None),
        activity_description: str | None = Field(default=None, description="Gegenstand des Unternehmens"),
        tax_office: str | None = Field(default=None, description="Responsible Finanzamt as 4-digit BuFa number"),
    ) -> dict[str, Any]:
        """Section 1 (company): name, seat, addresses, contact, activity and tax office."""
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean(
            {
                "legalForm": legal_form,
                "companyName": company_name,
                "seatCity": seat_city,
                "businessStreet": business_street,
                "businessHouseNumber": business_house_number,
                "businessAdditional": business_additional,
                "businessPostalCode": business_postal_code,
                "businessCity": business_city,
                "managementAddressSame": management_address_same,
                "managementStreet": management_street,
                "managementHouseNumber": management_house_number,
                "managementAdditional": management_additional,
                "managementPostalCode": management_postal_code,
                "managementCity": management_city,
                "phone": phone,
                "email": email,
                "website": website,
                "activityDescription": activity_description,
                "taxOffice": tax_office,
            },
        )
        return api._make_request("PATCH", _corporate_url(f"{public_id}/"), json_data=payload)

    @mcp.tool()
    async def update_corporate_registration_details(  # noqa: PLR0913
        ctx: Context,
        public_id: str = Field(description="Corporate tax registration publicId"),
        notary_contract_date: str | None = Field(default=None, description="Notarization date, YYYY-MM-DD"),
        hr_application_filed: bool | None = Field(default=None, description="Handelsregister application filed?"),
        hr_application_date: str | None = Field(default=None, description="YYYY-MM-DD"),
        hr_registered: bool | None = Field(default=None, description="Already entered in the Handelsregister?"),
        hr_registration_date: str | None = Field(default=None, description="YYYY-MM-DD"),
        register_court: str | None = Field(default=None, description="e.g. 'Amtsgericht Charlottenburg'"),
        register_type: str | None = Field(default=None, description="Usually 'HRB'"),
        register_number: str | None = Field(
            default=None,
            description="Bare number without the HRB prefix, e.g. '254739 B'",
        ),
    ) -> dict[str, Any]:
        """Section 2 (registration): notary date and Handelsregister state."""
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean(
            {
                "notaryContractDate": notary_contract_date,
                "hrApplicationFiled": hr_application_filed,
                "hrApplicationDate": hr_application_date,
                "hrRegistered": hr_registered,
                "hrRegistrationDate": hr_registration_date,
                "registerCourt": register_court,
                "registerType": register_type,
                "registerNumber": register_number,
            },
        )
        return api._make_request("PATCH", _corporate_url(f"{public_id}/"), json_data=payload)

    @mcp.tool()
    async def set_corporate_people(
        ctx: Context,
        public_id: str = Field(description="Corporate tax registration publicId"),
        representatives: list[dict[str, Any]] | None = Field(
            default=None,
            description=(
                f"Managing directors (Geschäftsführer), max 9. {PERSON_SHAPE}; plus optional "
                "phone and email. REPLACES the whole list — send every entry, not a delta; "
                "omit the parameter to leave the list unchanged."
            ),
        ),
        shareholder_entries: list[dict[str, Any]] | None = Field(
            default=None,
            description=(
                f"Shareholders (Gesellschafter), max 99. {PERSON_SHAPE}; plus shareholderType "
                "('natural'/'legal'), entityName (legal entities), shareNominalAmount (EUR) and "
                "sharePercent (must sum to 100 across all entries). REPLACES the whole list; "
                "omit the parameter to leave it unchanged."
            ),
        ),
    ) -> dict[str, Any]:
        """Sections 3+4 (people): managing directors and shareholders, replace-all semantics."""
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean({"representatives": representatives, "shareholderEntries": shareholder_entries})
        return api._make_request("PATCH", _corporate_url(f"{public_id}/"), json_data=payload)

    @mcp.tool()
    async def update_corporate_financials(  # noqa: PLR0913
        ctx: Context,
        public_id: str = Field(description="Corporate tax registration publicId"),
        share_capital: str | None = Field(default=None, description="Stammkapital EUR (GmbH >= 25000, UG 1..24999)"),
        business_start_date: str | None = Field(default=None, description="Beginn der Tätigkeit, YYYY-MM-DD"),
        divergent_fiscal_year: bool | None = Field(
            default=None,
            description="Fiscal year differs from the calendar year?",
        ),
        fiscal_year_start: str | None = Field(default=None, description="YYYY-MM-DD, only when divergent"),
        expected_profit_founding_year: int | None = Field(default=None, description="Expected profit this year, EUR"),
        expected_profit_following_year: int | None = Field(default=None, description="Expected profit next year, EUR"),
    ) -> dict[str, Any]:
        """Section 5 (financials): capital, start of activity, fiscal year, expected profits."""
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean(
            {
                "shareCapital": share_capital,
                "businessStartDate": business_start_date,
                "divergentFiscalYear": divergent_fiscal_year,
                "fiscalYearStart": fiscal_year_start,
                "expectedProfitFoundingYear": expected_profit_founding_year,
                "expectedProfitFollowingYear": expected_profit_following_year,
            },
        )
        return api._make_request("PATCH", _corporate_url(f"{public_id}/"), json_data=payload)

    @mcp.tool()
    async def update_corporate_vat_and_bank(  # noqa: PLR0913
        ctx: Context,
        public_id: str = Field(description="Corporate tax registration publicId"),
        expected_revenue_founding_year: int | None = Field(default=None, description="Expected revenue this year, EUR"),
        expected_revenue_following_year: int | None = Field(
            default=None,
            description="Expected revenue next year, EUR",
        ),
        is_kleinunternehmer: bool | None = Field(
            default=None,
            description="Apply the § 19 UStG Kleinunternehmer rule (no VAT charged)?",
        ),
        kleinunternehmer_charge_vat: bool | None = Field(
            default=None,
            description="Waive the Kleinunternehmer rule and charge VAT anyway (binds for 5 years)?",
        ),
        estimated_vat_amount_founding_year: int | None = Field(
            default=None,
            description="Estimated VAT this year, EUR",
        ),
        taxation_method: str | None = Field(default=None, description="'soll' (default) or 'ist'"),
        request_vat_id: bool | None = Field(default=None, description="Request a USt-IdNr (needed for EU B2B)?"),
        bank_iban: str | None = Field(default=None, description="IBAN for tax refunds"),
        bank_account_holder_role: int | None = Field(default=None, description="1 = the company, 99 = someone else"),
        bank_account_holder_name: str | None = Field(default=None, description="Only when the holder is someone else"),
    ) -> dict[str, Any]:
        """Section 6 (VAT & bank): revenue forecast, Kleinunternehmer choice, taxation method,
        VAT ID and the refund bank account."""
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean(
            {
                "expectedRevenueFoundingYear": expected_revenue_founding_year,
                "expectedRevenueFollowingYear": expected_revenue_following_year,
                "isKleinunternehmer": is_kleinunternehmer,
                "kleinunternehmerChargeVat": kleinunternehmer_charge_vat,
                "estimatedVatAmountFoundingYear": estimated_vat_amount_founding_year,
                "taxationMethod": taxation_method,
                "requestVatId": request_vat_id,
                "bankIban": bank_iban,
                "bankAccountHolderRole": bank_account_holder_role,
                "bankAccountHolderName": bank_account_holder_name,
            },
        )
        return api._make_request("PATCH", _corporate_url(f"{public_id}/"), json_data=payload)

    @mcp.tool()
    async def get_corporate_submission_link(ctx: Context) -> dict[str, Any]:
        """The FINAL step: hand the user over to the Norman app to review and submit.

        The e-filing to the Finanzamt (via ELSTER) is a binding legal act, so it is done in the
        app only: the user opens the link, sees the rendered ELSTER preview of every answer and
        presses Submit themselves. Returns the link plus the current completeness state — if
        `readyToSubmit` is false, finish the `missing` fields first.
        """
        api = ctx.request_context.lifespan_context.get("api")
        record = api._make_request("GET", _corporate_url("my/"))
        sections = record.get("sections", {}) if isinstance(record, dict) else {}
        missing = [name for section in sections.values() for name in section.get("missing", [])]
        return {
            "url": _app_url("corporate-tax-registration"),
            "readyToSubmit": bool(sections) and not missing,
            "missing": missing,
            "status": record.get("status") if isinstance(record, dict) else None,
            "note": (
                "Open the link in the Norman app, review the ELSTER preview and press Submit "
                "there — the final e-filing to the Finanzamt is confirmed by the user in the app."
            ),
        }
