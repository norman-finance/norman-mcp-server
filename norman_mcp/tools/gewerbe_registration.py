import base64
import logging
from typing import Any
from urllib.parse import urljoin

from norman_mcp.context import Context
from mcp.server.fastmcp.utilities.types import Image
from pydantic import Field

from norman_mcp import config

logger = logging.getLogger(__name__)

NORMAN_AGENT_SOURCE = "norman_agent"

# The Gewerbe enums are small and stable, so they are documented here rather than via a
# backend choices endpoint (the flow has none).
GEWERBE_CHOICES: dict[str, dict[str, str]] = {
    "legalForm": {
        "sole_proprietorship": "Sole proprietorship (Einzelunternehmen)",
        "sole_proprietor_ek": "Sole proprietor (e.K.)",
        "gbr": "GbR",
        "ug": "UG (haftungsbeschränkt)",
        "gmbh": "GmbH",
        "ggmbh": "gGmbH",
        "ag": "AG",
        "kg": "KG",
        "ohg": "oHG",
        "gmbh_co_kg": "GmbH & Co. KG",
        "ug_co_kg": "UG & Co. KG",
        "other": "Other",
    },
    "establishmentType": {"head_office": "Head office", "branch": "Branch office"},
    "businessType": {"industry": "Industry", "trade": "Trade", "craft": "Craft", "other": "Other"},
    "activityType": {"main": "Main occupation", "secondary": "Secondary occupation"},
    "residenceType": {"inland": "Germany", "ausland": "Abroad"},
    "gender": {"male": "Male", "female": "Female", "diverse": "Diverse"},
}


def _gewerbe_url(path: str = "") -> str:
    return urljoin(config.api_base_url, f"api/v1/gewerbe-registrations/{path}")


def _clean(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def register_gewerbe_registration_tools(mcp):
    """Register Gewerbeanmeldung (German trade-office registration, form GewA 1) tools.

    Who files one: Gewerbetreibende (a trade) and GmbH/UG founders — NOT Freiberufler
    (freelance professions). The flow is server-authoritative: every response carries
    `sections` (basic / business / owner, each with `complete` + `missing` camelCase field
    names) and `status` (data_collection → data_complete → documents_generated). Navigate by
    `sections.missing`; never track progress yourself.

    Orchestration: get_gewerbe_registration → create_gewerbe_registration (optionally linked to
    a GmbH/UG incorporation, which pre-fills it) → fill the three sections
    (update_gewerbe_basic / update_gewerbe_business / update_gewerbe_owner) → confirm →
    generate_gewerbe_document. Always tell the user the output is a pre-filled template they
    submit themselves to their local Gewerbeamt (not legal advice, not e-filed), and give them
    the responsible office from get_gewerbe_trade_office. The signature is added when the user
    prints the form (or in the Norman product), so the MCP-generated PDF has a blank signature
    line.
    """

    @mcp.tool()
    async def get_gewerbe_registration(ctx: Context) -> dict[str, Any]:
        """Get the user's Gewerbeanmeldung, if any. Call this FIRST.

        A "not found" response means there is none — offer to start one with
        create_gewerbe_registration. Otherwise resume from `sections.missing`.
        A non-empty `documents` list means the form was already generated.
        """
        api = ctx.request_context.lifespan_context.get("api")
        return api._make_request("GET", _gewerbe_url("my/"))

    @mcp.tool()
    async def get_gewerbe_registration_choices(ctx: Context) -> dict[str, Any]:  # noqa: ARG001
        """Get the valid values for the Gewerbeanmeldung enum fields (value → label)."""
        return GEWERBE_CHOICES

    @mcp.tool()
    async def create_gewerbe_registration(
        ctx: Context,
        incorporation_public_id: str | None = Field(
            default=None,
            description="Link to a GmbH/UG incorporation (publicId) to pre-fill from it; omit for self-employed.",
        ),
    ) -> dict[str, Any]:
        """Start a Gewerbeanmeldung. 400 if one already exists (use get_gewerbe_registration).

        If linked to an incorporation, the company, address, activity and managing directors
        are pre-filled. For self-employed users the answers from their tax-registration
        Fragebogen are carried over automatically.
        """
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean({"source": NORMAN_AGENT_SOURCE, "incorporation": incorporation_public_id})
        return api._make_request("POST", _gewerbe_url(), json_data=payload)

    @mcp.tool()
    async def update_gewerbe_basic(
        ctx: Context,
        public_id: str = Field(description="Gewerbeanmeldung publicId"),
        activity_start_date: str | None = Field(default=None, description="Start of activity, YYYY-MM-DD (<=14 days ahead)"),
        establishment_type: str | None = Field(default=None, description="'head_office' or 'branch'"),
    ) -> dict[str, Any]:
        """Section 1 (basics): when the trade starts and whether it's a head or branch office."""
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean({"activityStartDate": activity_start_date, "establishmentType": establishment_type})
        return api._make_request("PATCH", _gewerbe_url(f"{public_id}/"), json_data=payload)

    @mcp.tool()
    async def update_gewerbe_business(  # noqa: PLR0913
        ctx: Context,
        public_id: str = Field(description="Gewerbeanmeldung publicId"),
        legal_form: str | None = Field(default=None, description="See get_gewerbe_registration_choices.legalForm"),
        registered_name: str | None = Field(default=None, description="Firma / business name"),
        commercial_register_number: str | None = Field(default=None, description="HR number (legal entities only)"),
        business_type: list[str] | None = Field(default=None, description="Any of: industry, trade, craft, other"),
        business_street: str | None = Field(default=None),
        business_house_number: str | None = Field(default=None),
        business_postal_code: str | None = Field(default=None),
        business_city: str | None = Field(default=None),
        business_email: str | None = Field(default=None),
        business_phone: str | None = Field(default=None),
        activity_description: str | None = Field(default=None, description="Precise description of the trade (Feld 15)"),
        license_required: bool | None = Field(default=None),
        license_authority: str | None = Field(default=None),
        license_issue_date: str | None = Field(default=None, description="YYYY-MM-DD"),
        public_sector_participation: bool | None = Field(default=None),
        has_employees: bool | None = Field(default=None),
        employees_full_time: int | None = Field(default=None),
        employees_part_time: int | None = Field(default=None),
    ) -> dict[str, Any]:
        """Section 2 (business): legal form, name, Betriebsstätte address, activity, licence,
        public-sector participation and employees. `commercialRegisterNumber` is required for
        legal entities (GmbH/UG/AG/…); licence/employee details only when their flag is true."""
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean(
            {
                "legalForm": legal_form,
                "registeredName": registered_name,
                "commercialRegisterNumber": commercial_register_number,
                "businessType": business_type,
                "businessStreet": business_street,
                "businessHouseNumber": business_house_number,
                "businessPostalCode": business_postal_code,
                "businessCity": business_city,
                "businessEmail": business_email,
                "businessPhone": business_phone,
                "activityDescription": activity_description,
                "licenseRequired": license_required,
                "licenseAuthority": license_authority,
                "licenseIssueDate": license_issue_date,
                "publicSectorParticipation": public_sector_participation,
                "hasEmployees": has_employees,
                "employeesFullTime": employees_full_time,
                "employeesPartTime": employees_part_time,
            },
        )
        return api._make_request("PATCH", _gewerbe_url(f"{public_id}/"), json_data=payload)

    @mcp.tool()
    async def update_gewerbe_owner(  # noqa: PLR0913
        ctx: Context,
        public_id: str = Field(description="Gewerbeanmeldung publicId"),
        owner_first_names: str | None = Field(default=None),
        owner_last_name: str | None = Field(default=None),
        owner_birth_name: str | None = Field(default=None),
        owner_dob: str | None = Field(default=None, description="Date of birth, YYYY-MM-DD (>=18)"),
        owner_place_of_birth: str | None = Field(default=None),
        owner_country_of_birth: str | None = Field(default=None, description="ISO2, e.g. DE"),
        owner_nationality: str | None = Field(default=None, description="ISO2, e.g. DE"),
        owner_gender: str | None = Field(default=None, description="'male', 'female' or 'diverse'"),
        owner_email: str | None = Field(default=None),
        owner_phone: str | None = Field(default=None),
        activity_type: str | None = Field(default=None, description="'main' or 'secondary' occupation"),
        owner_address_same_as_business: bool | None = Field(default=None),
        owner_residence_type: str | None = Field(default=None, description="'inland' or 'ausland'"),
        owner_residence_street: str | None = Field(default=None),
        owner_residence_house_number: str | None = Field(default=None),
        owner_residence_postal_code: str | None = Field(default=None),
        owner_residence_city: str | None = Field(default=None),
    ) -> dict[str, Any]:
        """Section 3 (owner / authorized representative): personal data, address and
        main-vs-secondary occupation. Set `ownerAddressSameAsBusiness` true when the home is the
        business address; otherwise provide the residence fields."""
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean(
            {
                "ownerFirstNames": owner_first_names,
                "ownerLastName": owner_last_name,
                "ownerBirthName": owner_birth_name,
                "ownerDob": owner_dob,
                "ownerPlaceOfBirth": owner_place_of_birth,
                "ownerCountryOfBirth": owner_country_of_birth,
                "ownerNationality": owner_nationality,
                "ownerGender": owner_gender,
                "ownerEmail": owner_email,
                "ownerPhone": owner_phone,
                "activityType": activity_type,
                "ownerAddressSameAsBusiness": owner_address_same_as_business,
                "ownerResidenceType": owner_residence_type,
                "ownerResidenceStreet": owner_residence_street,
                "ownerResidenceHouseNumber": owner_residence_house_number,
                "ownerResidencePostalCode": owner_residence_postal_code,
                "ownerResidenceCity": owner_residence_city,
            },
        )
        return api._make_request("PATCH", _gewerbe_url(f"{public_id}/"), json_data=payload)

    @mcp.tool()
    async def suggest_gewerbe_activity(
        ctx: Context,
        public_id: str = Field(description="Gewerbeanmeldung publicId"),
        draft: str = Field(description="The user's rough trade-activity text to reformulate"),
    ) -> dict[str, Any]:
        """Reformulate a rough trade activity into precise, Gewerbeamt-ready wording.

        Returns {"suggestion": ...} — a faithful same-language rewrite (concrete activity, no
        catch-all phrases, nothing invented). Show it to the user; apply it via
        update_gewerbe_business(activity_description=...) only if they accept.
        """
        api = ctx.request_context.lifespan_context.get("api")
        return api._make_request("POST", _gewerbe_url(f"{public_id}/suggest-activity/"), json_data={"draft": draft})

    @mcp.tool()
    async def generate_gewerbe_document(
        ctx: Context,
        public_id: str = Field(description="Gewerbeanmeldung publicId"),
    ) -> dict[str, Any]:
        """Generate the pre-filled GewA 1 PDF. 400 + `missing` if a section is incomplete.

        Get the user's explicit confirmation first. The PDF is a template for self-submission
        to the Gewerbeamt (not legal advice); it carries a blank signature line for the user to
        sign on paper. Returns the download descriptor; follow with get_gewerbe_trade_office to
        tell them where to submit.
        """
        api = ctx.request_context.lifespan_context.get("api")
        return api._make_request("POST", _gewerbe_url(f"{public_id}/documents/"), json_data={})

    @mcp.tool()
    async def get_gewerbe_document_preview(
        ctx: Context,
        public_id: str = Field(description="Gewerbeanmeldung publicId"),
    ) -> Any:
        """Return the first page of the generated GewA 1 as an image for the user to review."""
        api = ctx.request_context.lifespan_context.get("api")
        response = api._make_request("GET", _gewerbe_url(f"{public_id}/documents/"))
        documents = response.get("documents", []) if isinstance(response, dict) else []
        preview = documents[0].get("previewImage") if documents else None
        if not preview:
            return {"error": "No preview available. Generate the document first."}
        return Image(data=base64.b64decode(preview), format="jpeg")

    @mcp.tool()
    async def get_gewerbe_trade_office(
        ctx: Context,
        public_id: str = Field(description="Gewerbeanmeldung publicId"),
    ) -> dict[str, Any]:
        """Resolve the responsible trade office (Gewerbeamt) for the business address.

        Returns {"office": {...}} or {"office": null} — if null, tell the user to search for
        "<their city> Gewerbeamt" to find where to submit.
        """
        api = ctx.request_context.lifespan_context.get("api")
        return api._make_request("GET", _gewerbe_url(f"{public_id}/trade-office/"))
