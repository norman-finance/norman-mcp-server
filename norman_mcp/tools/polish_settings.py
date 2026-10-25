"""A Polish company's tax settings from an AI client: proposed, and applied by the owner in Norman.

The Norman API does not take a Polish company's tax settings from an OAuth client, an API key or an MCP server
(403 `tax_setting_proposal_required`). propose_tax_setting_change stores a proposal instead (POST
companies/<id>/tax-setting-proposals/), which the API validates as the settings screen does. It persists a pending
proposal, but does not apply a tax setting. The
answer carries `openUrl`: the tax settings in the Norman app with the proposal's card, where the owner applies or
cancels it. No tool here applies one, and the API refuses this server's requests to apply or cancel.

For a Polish company the settings writes of the other modules come here too: update_tax_setting,
update_company_details (NIP, EU VAT number, business start, reminders), update_vat_proportion and
update_invoice_settings (the tax office) propose instead of writing. A German company is not concerned.

lookup_polish_company reads an sp. z o.o. in the KRS and on the White list by its NIP or KRS number and proposes each
detail Norman lacks the same way (POST companies/<id>/polish-setup/registry/).

get_ksef_status reads the KSeF connection, never the token, and search_polish_tax_offices the Polish tax offices. A KSeF
token and personal government identifiers such as PESEL never go through this tool: the owner enters them in Norman.

Kept in step with the in-app assistant's tools (norman-finance-api, norman_mcp/tools/polish_settings.py): the same
arguments, values and wording, except that personal identifiers are not exposed and the owner applies a proposal
through `openUrl` instead of a card in the chat.
"""

import re
from datetime import date, datetime
from typing import Annotated, Any, Literal
from urllib.parse import urljoin

from mcp.types import ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context
from norman_mcp.tools.results import as_object

NO_COMPANY_ERROR = {"error": "No company available. Please authenticate first."}
POLISH_ONLY = {
    "error": "This tool is for a Polish company (JDG or sp. z o.o.) only.",
    "code": "polish_company_required",
}
NOTHING_PROPOSED = "Nothing to propose: give the new value of the setting."
# Opens the description of a tool for Polish companies, as "Germany only." opens the German ones'.
POLAND_ONLY_NOTE = "Poland only."
# Additive write: persists a pending proposal; only the owner can apply the setting in Norman.
PROPOSE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

SettingName = Literal[
    "tax_form",
    "cit_rate",
    "zus",
    "company_zus",
    "vat_status",
    "vat_cash_method",
    "vat_proportion",
    "nip",
    "eu_vat_number",
    "activity_start",
    "tax_office",
    "reminders",
    "ksef_auto_sync",
    "ksef_sync",
    "ryczalt_rate",
    "business_details",
    "company_register",
]

# Each setting's tool arguments, by the name the API reads them under (camelCase, as every client sends them).
ARGUMENTS: dict[str, dict[str, str]] = {
    "tax_form": {"tax_form": "taxRegime", "tax_form_from_year": "taxRegimeFrom"},
    "cit_rate": {"cit_rate": "taxRegime"},
    "zus": {
        "zus_scheme": "zusRelief",
        "zus_scheme_start": "zusSchemeStart",
        "zus_sickness_insurance": "zusSicknessInsurance",
    },
    "company_zus": {"company_zus_scope": "zusCompanyScope", "shareholder_personal_zus": "zusShareholderPersonal"},
    "vat_status": {"vat_status": "vatType", "vat_frequency": "reportingFrequency"},
    "vat_cash_method": {"cash_method_from": "vatCashMethodFrom", "cash_method_off": ""},
    "vat_proportion": {
        "proportion_year": "year",
        "estimated_percent": "estimatedPercent",
        "clear_estimate": "",
        "round_to_whole": "roundToWhole",
        "previous_taxed_turnover": "previousTaxedTurnover",
        "previous_exempt_turnover": "previousExemptTurnover",
        "fixed_asset_correction": "fixedAssetCorrection",
    },
    "nip": {"nip": "taxNumber"},
    "eu_vat_number": {"eu_vat_number": "vatNumber"},
    "activity_start": {"business_start_date": "activityStart"},
    "tax_office": {"tax_office_code": "taxOfficeCode"},
    "reminders": {"deadline_reminders": "isToNotifyTaxDeadlines"},
    "ksef_auto_sync": {"ksef_auto_import": "ksefAutoSync"},
    "ksef_sync": {},
    "ryczalt_rate": {"revenue_category": "category", "lump_sum_rate": "ryczaltRate"},
    "business_details": {
        "regon": "regon", "business_street": "address", "business_postal_code": "zipCode", "business_city": "city",
    },
    "company_register": {
        "krs_number": "krs", "register_court": "registerCourt", "share_capital": "shareCapital",
        "registered_seat": "registeredSeat",
    },
}


def proposed_message(open_url: str) -> str:
    return (
        "Proposed, not changed yet. Give the owner this link to apply or cancel it in Norman: "
        f"{open_url} . No AI client can apply it. Norman records the setting only and notifies no office."
    )


def _company_url(api: Any, suffix: str = "") -> str:
    return urljoin(config.api_base_url, f"api/v1/companies/{api.company_id}/{suffix}")


async def company_country(api: Any) -> str | None:
    """The selected company's country ("PL", "DE"), read at the call: this server serves every company."""
    if not api.company_id:
        return None
    company = await api.arequest("GET", _company_url(api))
    return company.get("country") if isinstance(company, dict) else None


async def propose(api: Any, setting: str, values: dict[str, Any]) -> dict[str, Any]:
    """Store a proposal; its card and the link to apply it in Norman, or the API's refusal as it states it."""
    if not api.company_id:
        return NO_COMPANY_ERROR
    result = await api.arequest(
        "POST", _company_url(api, "tax-setting-proposals/"), json_data={"setting": setting, "values": values},
    )
    if isinstance(result, dict) and result.get("cardType") == "tax_setting_change":
        return {"proposal": result, "openUrl": result.get("openUrl"), "message": proposed_message(result.get("openUrl"))}
    return as_object(result)


def proposal_values(setting: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """The API's values of one setting from the tool's arguments; an argument of another setting is refused."""
    names = ARGUMENTS[setting]
    stray = sorted(name for name, value in arguments.items() if value is not None and name not in names)
    if stray:
        raise ValueError(
            f"Propose one setting per call: {', '.join(stray)} belong to another setting than {setting}.",
        )
    values = {names[name]: value for name, value in arguments.items() if value is not None and names[name]}
    if arguments.get("cash_method_off"):
        values["vatCashMethodFrom"] = None
    if arguments.get("clear_estimate"):
        values["estimatedPercent"] = None
    return values


def iso_day(value: str | date | datetime | None) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def nip_digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


async def propose_company_details(api: Any, details: dict[str, Any]) -> list[dict[str, Any]]:
    """update_company_details for a Polish company: one proposal per tax setting it names."""
    results = []
    nip = details.get("tax_id")
    if nip:
        results.append(await propose(api, "nip", {"taxNumber": nip}))
    vat_id = details.get("vat_id")
    # A NIP's proposal sets the EU VAT number from it ("PL" and the NIP), as the settings screen does.
    if vat_id and not (nip and re.sub(r"\s", "", vat_id).upper() == f"PL{nip_digits(nip)}"):
        results.append(await propose(api, "eu_vat_number", {"vatNumber": vat_id}))
    if details.get("activity_start"):
        results.append(await propose(api, "activity_start", {"activityStart": iso_day(details["activity_start"])}))
    if details.get("notify_tax_deadlines") is not None:
        results.append(await propose(api, "reminders", {"isToNotifyTaxDeadlines": details["notify_tax_deadlines"]}))
    return results


async def propose_vat_status(
    api: Any, setting_url: str, *, vat_type: str | None, reporting_frequency: str | None, others: dict[str, Any],
) -> dict[str, Any]:
    """update_tax_setting for a Polish company: this year's VAT status and JPK_V7 frequency, as a proposal.

    The settings screen changes nothing else of a tax setting, and only this year's: earlier years have their own
    VAT history there.
    """
    given = sorted(
        name for name, value in others.items()
        if value not in (None, "") and not (name == "tax_type" and value == "sales")
    )
    if given:
        return {"error": (
            "For a Polish company only the VAT status and the JPK_V7 frequency change here, "
            f"not {', '.join(given)}."
        )}
    setting = await api.arequest("GET", setting_url)
    if not isinstance(setting, dict) or "error" in setting:
        return as_object(setting)
    if setting.get("taxType") != "sales" or setting.get("taxYear") != date.today().year:  # noqa: DTZ011 - local dates
        return {"error": (
            "For a Polish company only this year's VAT status changes here. Earlier years are in Norman's Settings, "
            "Taxes, VAT history."
        )}
    values = {"vatType": vat_type, "reportingFrequency": reporting_frequency}
    values = {key: value for key, value in values.items() if value}
    if not values:
        return {"error": NOTHING_PROPOSED}
    return await propose(api, "vat_status", values)


async def propose_tax_office(api: Any, company_url: str, patch: dict[str, Any]) -> dict[str, Any]:
    """update_invoice_settings for a Polish company: the tax office it names, or confirms, is proposed; the other
    invoice settings are written as before."""
    other = dict(patch)
    code = other.pop("taxOfficeCode", None)
    confirmed = other.pop("taxOfficeConfirmed", None)
    if not code and confirmed:
        # Confirming the stored office is choosing it, as the settings screen's Save does.
        stored = await api.arequest("GET", company_url + "invoices/settings/")
        code = ((stored if isinstance(stored, dict) else {}).get("invoiceSettings") or {}).get("taxOfficeCode")
    answer = summarize([await propose(api, "tax_office", {"taxOfficeCode": code})] if code else [])
    if other:
        answer["invoiceSettings"] = await api.arequest("PATCH", company_url + "invoices/settings/", json_data=other)
    if not code and not other:
        return {"error": "Give the tax office's 4-digit code from search_polish_tax_offices."}
    return answer


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Several proposals in one answer: the cards with their links, and what the API refused."""
    cards = [result["proposal"] for result in results if isinstance(result, dict) and "proposal" in result]
    refused = [result for result in results if not (isinstance(result, dict) and "proposal" in result)]
    answer: dict[str, Any] = {"proposals": cards}
    if cards:
        links = ", ".join(card.get("openUrl", "") for card in cards)
        answer["message"] = (
            f"Proposed, not changed yet. Give the owner these links to apply or cancel them in Norman: {links} . No "
            "AI client can apply them. Norman records the settings only and notifies no office."
        )
    if refused:
        answer["refused"] = refused
    return answer


async def propose_from_registry(api: Any, identifier: str | None) -> dict[str, Any]:
    """The KRS and White list details as the API proposes them, with the links where the owner applies each."""
    if not api.company_id:
        return NO_COMPANY_ERROR
    if await company_country(api) != "PL":
        return POLISH_ONLY
    body = {"identifier": identifier.strip()} if identifier and identifier.strip() else {}
    result = await api.arequest("POST", _company_url(api, "polish-setup/registry/"), json_data=body)
    if not isinstance(result, dict) or "proposals" not in result:
        return as_object(result)
    answer = {**result, **summarize([{"proposal": card} for card in result.get("proposals") or []])}
    if not answer.get("message"):
        answer.pop("message", None)
    return answer


def register_polish_settings_tools(mcp: Any) -> None:
    """The tools of a Polish company's tax settings: proposals, the KSeF connection, the tax offices."""

    @mcp.tool(title="Propose Tax Setting Change", annotations=PROPOSE)
    async def propose_tax_setting_change(  # noqa: PLR0913 - one argument per value the settings screen takes
        ctx: Context,
        setting: Annotated[SettingName, Field(description="The one setting this proposal changes.")],
        tax_form: Literal["progressive", "flat", "ryczalt"] | None = Field(
            default=None, description="tax_form (JDG): skala podatkowa, podatek liniowy or ryczałt.",
        ),
        tax_form_from_year: int | None = Field(
            default=None,
            description="tax_form: the tax year the new form applies from. Omitted: this year until 20 February, "
            "then the next one.",
        ),
        cit_rate: Literal["cit_standard", "cit_small"] | None = Field(
            default=None, description="cit_rate (sp. z o.o.): 19% (cit_standard) or 9% for a small taxpayer.",
        ),
        zus_scheme: Literal["none", "start_relief", "preferential", "small_zus_plus"] | None = Field(
            default=None,
            description="zus (JDG): pełny ZUS (none), ulga na start, preferencyjny ZUS or Mały ZUS Plus.",
        ),
        zus_scheme_start: str | None = Field(
            default=None, description="zus: the insurance start of an explicit preferential or Mały ZUS Plus period, YYYY-MM-DD. "
            "Ulga na start and full ZUS use activity_start; do not supply a duplicate start for them.",
        ),
        zus_sickness_insurance: bool | None = Field(default=None, description="zus: voluntary sickness insurance."),
        company_zus_scope: Literal["none", "employees", "board", "employees_and_board"] | None = Field(
            default=None, description="company_zus (sp. z o.o.): whom the company pays ZUS contributions for.",
        ),
        shareholder_personal_zus: bool | None = Field(
            default=None, description="company_zus: the sole shareholder pays personal ZUS separately.",
        ),
        vat_status: Literal["vat_subject", "small_business_exempt", "vat_exempt"] | None = Field(
            default=None,
            description="vat_status: active VAT payer, exempt by turnover (art. 113) or by activity (art. 43).",
        ),
        vat_frequency: Literal["monthly", "quarterly"] | None = Field(
            default=None, description="vat_status: JPK_V7M (monthly) or JPK_V7K (quarterly), active VAT payer only.",
        ),
        cash_method_from: str | None = Field(
            default=None, description="vat_cash_method: the first day of the VAT cash method, YYYY-MM-DD.",
        ),
        cash_method_off: bool | None = Field(default=None, description="vat_cash_method: true switches it off."),
        proportion_year: int | None = Field(default=None, description="vat_proportion: the tax year, e.g. 2027."),
        estimated_percent: int | None = Field(
            default=None, ge=0, le=100, description="vat_proportion: the estimated proportion of the year.",
        ),
        clear_estimate: bool | None = Field(
            default=None, description="vat_proportion: true drops the estimate (the previous year's turnover).",
        ),
        round_to_whole: bool | None = Field(
            default=None, description="vat_proportion: above 98 % as 100 %, 2 % or less as 0 % (art. 90 ust. 10).",
        ),
        previous_taxed_turnover: str | None = Field(
            default=None, description="vat_proportion: the previous year's turnover with the right to deduct, PLN.",
        ),
        previous_exempt_turnover: str | None = Field(
            default=None, description="vat_proportion: the previous year's VAT-exempt turnover, PLN.",
        ),
        fixed_asset_correction: str | None = Field(
            default=None, description="vat_proportion: the year's art. 91 ust. 2 correction, PLN, + or -.",
        ),
        nip: str | None = Field(default=None, description="nip: the 10 digits; the EU VAT number follows it."),
        eu_vat_number: str | None = Field(default=None, description="eu_vat_number, e.g. PL5260250274."),
        business_start_date: str | None = Field(default=None, description="activity_start: YYYY-MM-DD."),
        tax_office_code: str | None = Field(
            default=None, description="tax_office: the 4-digit code from search_polish_tax_offices.",
        ),
        deadline_reminders: bool | None = Field(default=None, description="reminders: on or off."),
        ksef_auto_import: bool | None = Field(
            default=None, description="ksef_auto_sync: import invoices from KSeF automatically, on or off.",
        ),
        revenue_category: str | None = Field(
            default=None,
            description="ryczalt_rate (JDG): revenue category code, e.g. 700 services, 730 goods or 750 interest.",
        ),
        lump_sum_rate: Literal["2", "3", "5.5", "8.5", "10", "12", "12.5", "14", "15", "17"] | None = Field(
            default=None,
            description="ryczalt_rate: percent. Omit to propose Norman's default for the category, based on "
            "the company's PKD, profession or description. The owner reviews its source and applies it in Norman.",
        ),
        regon: str | None = Field(default=None, description="business_details: the 9-digit REGON."),
        business_street: str | None = Field(
            default=None,
            description="business_details: the street and number of the JDG's business or the sp. z o.o.'s seat, "
            "e.g. 'ul. Testowa 1/4'.",
        ),
        business_postal_code: str | None = Field(default=None, description="business_details: e.g. 00-001."),
        business_city: str | None = Field(
            default=None, description="business_details: the town; the street, postal code and town go together.",
        ),
        krs_number: str | None = Field(
            default=None, description="company_register (sp. z o.o.): the KRS number, 10 digits, e.g. 0000123456.",
        ),
        register_court: str | None = Field(
            default=None,
            description="company_register: the register court and its department, as the KRS extract names it.",
        ),
        share_capital: str | None = Field(
            default=None, description="company_register: the share capital (kapitał zakładowy) in PLN, e.g. 5000.00.",
        ),
        registered_seat: str | None = Field(
            default=None, description="company_register: the seat (siedziba), the town, e.g. Warszawa.",
        ),
    ) -> dict[str, Any]:
        """Poland only. Propose a change to a Polish company's tax settings; the owner applies it in Norman.

        Creates a pending proposal on each call, but does not change the tax setting until the owner applies it.
        Give the owner `openUrl`, the tax settings in Norman with
        the proposal, and never say a setting is changed. No AI client can apply it, and none can change these
        settings directly. One setting per call; ksef_sync proposes an import from KSeF now.
        The API checks it as the settings screen does and states what it refuses.
        Norman records the setting and notifies no office: the owner reports a tax form in CEIDG or at the tax
        office, VAT changes on VAT-R, ZUS changes in ePłatnik or CEIDG.
        Facts only: never recommend a tax form, a CIT rate or a ZUS scheme. Explain the rules; the owner decides.
        For ryczalt_rate, supply the revenue category and optionally its rate; omit the rate to show
        Norman's default and its source for the owner to review. Never infer a rate from a category alone.
        Never ask for a KSeF token or PESEL: the owner enters these directly in Norman's settings.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return NO_COMPANY_ERROR
        if await company_country(api) != "PL":
            return POLISH_ONLY
        arguments = {
            "tax_form": tax_form, "tax_form_from_year": tax_form_from_year, "cit_rate": cit_rate,
            "zus_scheme": zus_scheme, "zus_scheme_start": zus_scheme_start,
            "zus_sickness_insurance": zus_sickness_insurance, "company_zus_scope": company_zus_scope,
            "shareholder_personal_zus": shareholder_personal_zus, "vat_status": vat_status,
            "vat_frequency": vat_frequency, "cash_method_from": cash_method_from, "cash_method_off": cash_method_off,
            "proportion_year": proportion_year, "estimated_percent": estimated_percent,
            "clear_estimate": clear_estimate, "round_to_whole": round_to_whole,
            "previous_taxed_turnover": previous_taxed_turnover, "previous_exempt_turnover": previous_exempt_turnover,
            "fixed_asset_correction": fixed_asset_correction, "nip": nip, "eu_vat_number": eu_vat_number,
            "business_start_date": business_start_date, "tax_office_code": tax_office_code,
            "deadline_reminders": deadline_reminders, "ksef_auto_import": ksef_auto_import,
            "revenue_category": revenue_category, "lump_sum_rate": lump_sum_rate, "regon": regon,
            "business_street": business_street, "business_postal_code": business_postal_code,
            "business_city": business_city, "krs_number": krs_number, "register_court": register_court,
            "share_capital": share_capital, "registered_seat": registered_seat,
        }
        try:
            values = proposal_values(setting, arguments)
        except ValueError as error:
            return {"error": str(error)}
        if not values and setting != "ksef_sync":
            return {"error": NOTHING_PROPOSED}
        return await propose(api, setting, values)

    @mcp.tool(title="Look Up Polish Company", annotations=PROPOSE)
    async def lookup_polish_company(
        ctx: Context,
        identifier: str | None = Field(
            default=None,
            description="The company's NIP (10 digits) or KRS number, as the owner gives it. Omitted: the KRS number "
            "Norman holds, else the NIP.",
        ),
    ) -> dict[str, Any]:
        """Poland only. Look the selected sp. z o.o. up in the KRS and on the Ministry of Finance White list (Biała
        lista) by its NIP or KRS number, and propose each detail Norman lacks; the owner applies them in Norman.

        Creates a pending proposal per detail on each call that finds one: the NIP; the REGON and the seat's address
        (business_details); the KRS number, register court, share capital and seat (company_register), which the
        company's invoices must state (KSH art. 206); the VAT status when the White list lists an active VAT payer.
        Give the owner each proposal's `openUrl` and never say a detail is changed. The answer has `company` (what
        the registers say; `sources` per register, where unavailable or limit_reached means try later or fill it in
        by hand), `unchanged`, `refused` and `notes` to pass on. For the selected company only: never for a client
        or a vendor.
        """
        return await propose_from_registry(ctx.request_context.lifespan_context["api"], identifier)

    @mcp.tool(title="Get KSeF Status", annotations=READ)
    async def get_ksef_status(ctx: Context) -> dict[str, Any]:
        """Poland only. A Polish company's KSeF connection: connected or not, token or delegated access, what KSeF
        said about the token, the last pull and whether it stalled. Never the token itself.

        Never ask for a KSeF token or take one: the owner pastes it in Norman's settings, the KSeF field of the tax
        settings (`settingsUrl`). To import from KSeF now, propose ksef_sync.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return NO_COMPANY_ERROR
        if await company_country(api) != "PL":
            return POLISH_ONLY
        connection = await api.arequest("GET", _company_url(api, "invoices/ksef-connection/"))
        if not isinstance(connection, dict) or "error" in connection:
            return as_object(connection)
        return {**connection, "settingsUrl": ksef_settings_url(api.company_id)}

    @mcp.tool(title="Search Polish Tax Offices", annotations=READ)
    async def search_polish_tax_offices(
        ctx: Context,
        search: Annotated[str, Field(description="Words of the office's name, town or code, e.g. 'Piaseczno'.")],
    ) -> dict[str, Any]:
        """Poland only. Search the Polish tax offices (urzędy skarbowe) by name, town or code. Each has its 4-digit
        code (KodUrzedu), which propose_tax_setting_change takes for tax_office. Norman does not guess the office: a
        sole trader's office follows the owner's residence, a company's its seat. Let the owner choose it."""
        api = ctx.request_context.lifespan_context["api"]
        offices = await api.arequest(
            "GET", urljoin(config.api_base_url, "api/v1/taxes/polish/tax-offices/"), params={"search": search},
        )
        if not isinstance(offices, list):
            return as_object(offices)
        return {"taxOffices": offices[:20], "count": len(offices)}


def ksef_settings_url(company_id: str) -> str:
    """The KSeF field of the tax settings in the Norman app, for the company."""
    return f"{config.app_base_url.rstrip('/')}/account?section=tax-settings&company={company_id}&field=ksefToken"
