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

INCORPORATION_CHOICE_TYPES = (
    "legal-forms",
    "shareholder-types",
    "agreement-types",
    "notarization-types",
    "notarization-timeframes",
)


def _incorporations_url(path: str = "") -> str:
    return urljoin(config.api_base_url, f"api/v1/incorporations/{path}")


def _clean(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def register_incorporation_tools(mcp):
    """Register GmbH/UG incorporation tools with the MCP server.

    The flow is server-authoritative: every response carries `sections` (per-section
    `complete` + `missing` field names), `musterprotokoll` eligibility with machine-readable
    `reasons`, `status` (data_collection → data_complete → documents_generated →
    notary_requested → handed_off → notarized → capital_deposited → registered → completed),
    a post-notary `roadmap` (7 founder-completable steps), and the full record. Navigate by
    `sections.missing` and `roadmap` — never track progress yourself.

    Side effect worth telling the user about: choosing the legal form (ug/gmbh) switches their
    Norman account to that corporate type with the SKR04 chart of accounts (out of the
    freelancer default) so bookkeeping and taxes are set up correctly from the start.
    """

    @mcp.tool()
    async def get_incorporation(ctx: Context) -> dict[str, Any]:
        """Get the user's active company incorporation (GmbH/UG founding), if any.

        Call this FIRST. A "not found" response means there is no active incorporation —
        offer to start one with create_incorporation. Otherwise resume: check `sections`
        for what's missing and continue there.
        """
        api = ctx.request_context.lifespan_context.get("api")
        return api._make_request("GET", _incorporations_url("my/"))

    @mcp.tool()
    async def get_incorporation_choices(
        ctx: Context,
        choice_type: str = Field(
            description="One of: 'legal-forms', 'shareholder-types', 'agreement-types', "
            "'notarization-types', 'notarization-timeframes'",
        ),
    ) -> dict[str, Any]:
        """Get valid values for incorporation enum fields (label by value)."""
        if choice_type not in INCORPORATION_CHOICE_TYPES:
            return {"error": f"Unknown choice type. Use one of: {', '.join(INCORPORATION_CHOICE_TYPES)}"}
        api = ctx.request_context.lifespan_context.get("api")
        response = api._make_request("GET", urljoin(config.api_base_url, f"api/v1/choices/{choice_type}/"))
        if isinstance(response, list):
            return {"choices": response}
        return response

    @mcp.tool()
    async def create_incorporation(
        ctx: Context,
        legal_form: str | None = Field(default=None, description="'ug' or 'gmbh' if already known"),
        locale: str = Field(default="de", description="'de' or 'en'"),
    ) -> dict[str, Any]:
        """Start a new GmbH/UG incorporation for the current user.

        Section 1/5 begins here. Save `publicId` from the response for all subsequent calls.
        Fails with a validation error if an active incorporation already exists —
        use get_incorporation and continue it instead.
        """
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean({"legalForm": legal_form, "locale": locale, "source": NORMAN_AGENT_SOURCE})
        return api._make_request("POST", _incorporations_url(), json_data=payload)

    @mcp.tool()
    async def update_incorporation_company(
        ctx: Context,
        public_id: str = Field(description="Incorporation publicId"),
        legal_form: str | None = Field(default=None, description="'ug' or 'gmbh'"),
        company_name: str | None = Field(
            default=None,
            description="Firma. The legal suffix (GmbH / UG (haftungsbeschränkt)) is appended automatically",
        ),
        business_purpose: str | None = Field(
            default=None,
            description="Unternehmensgegenstand — a short sentence describing the activity",
        ),
        registered_office_city: str | None = Field(default=None, description="Sitz city (statutory, required)"),
        registered_office_street: str | None = Field(default=None),
        registered_office_house_number: str | None = Field(default=None),
        registered_office_additional: str | None = Field(default=None),
        registered_office_postal_code: str | None = Field(default=None, description="5-digit German PLZ"),
        registered_address_skipped: bool | None = Field(
            default=None,
            description="True if the user wants to skip the street address for now (city is still required)",
        ),
    ) -> dict[str, Any]:
        """Section 1/5 — company basics. Any subset of fields; provided fields are validated.

        After saving the company name, nudge the user to check name availability themselves
        (Handelsregister search: https://www.handelsregister.de, IHK guidance) — Norman does
        not verify the name. The address may be skipped for now but is needed before notarization.
        Check `sections.company.missing` in the response for what's still required.
        """
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean(
            {
                "legalForm": legal_form,
                "companyName": company_name,
                "businessPurpose": business_purpose,
                "registeredOfficeCity": registered_office_city,
                "registeredOfficeStreet": registered_office_street,
                "registeredOfficeHouseNumber": registered_office_house_number,
                "registeredOfficeAdditional": registered_office_additional,
                "registeredOfficePostalCode": registered_office_postal_code,
                "registeredAddressSkipped": registered_address_skipped,
            },
        )
        return api._make_request("PATCH", _incorporations_url(f"{public_id}/"), json_data=payload)

    @mcp.tool()
    async def update_incorporation_capital(
        ctx: Context,
        public_id: str = Field(description="Incorporation publicId"),
        share_capital: str = Field(
            description="Stammkapital in full euros, e.g. '25000'. GmbH ≥ 25000; UG 1-24999 (fully paid in cash)",
        ),
    ) -> dict[str, Any]:
        """Section 3/5 — share capital. Validated against the legal form.

        The per-shareholder split is set on each shareholder (share_nominal_amount) and must
        sum up to this amount — `sections.capital.missing` will contain 'shareNominalSum'
        until it does.
        """
        api = ctx.request_context.lifespan_context.get("api")
        return api._make_request(
            "PATCH",
            _incorporations_url(f"{public_id}/"),
            json_data={"shareCapital": share_capital},
        )

    @mcp.tool()
    async def add_incorporation_shareholder(
        ctx: Context,
        public_id: str = Field(description="Incorporation publicId"),
        shareholder_type: str = Field(default="natural_person", description="'natural_person' or 'legal_entity'"),
        first_name: str | None = Field(default=None, description="Natural person: first name"),
        last_name: str | None = Field(default=None, description="Natural person: last name"),
        dob: str | None = Field(default=None, description="Natural person: YYYY-MM-DD, must be 18+"),
        nationality: str | None = Field(default=None, description="ISO2, e.g. 'DE'"),
        street: str | None = Field(default=None),
        house_number: str | None = Field(default=None),
        additional: str | None = Field(default=None),
        postal_code: str | None = Field(default=None),
        city: str | None = Field(default=None),
        country: str | None = Field(default=None, description="ISO2 residence country, default DE"),
        email: str | None = Field(default=None, description="Contact email (first shareholder only, optional)"),
        phone: str | None = Field(default=None, description="Contact phone (optional)"),
        entity_name: str | None = Field(default=None, description="Legal entity: Firma"),
        entity_seat: str | None = Field(default=None, description="Legal entity: Sitz"),
        entity_register_court: str | None = Field(default=None, description="Legal entity: Registergericht"),
        entity_register_number: str | None = Field(default=None, description="Legal entity: e.g. 'HRB 12345'"),
        share_nominal_amount: str | None = Field(
            default=None,
            description="This shareholder's part of the capital in full euros (Nennbetrag)",
        ),
        is_managing_director: bool = Field(
            default=False,
            description="Exactly one shareholder must be the Geschäftsführer; setting True unsets others",
        ),
    ) -> dict[str, Any]:
        """Section 2/5 — add a shareholder (max 3 for the statutory Musterprotokoll).

        Collect all founders one by one. For natural persons: name, date of birth,
        nationality and residential address are required. For legal entities: Firma, Sitz,
        register court and register number. Returns the full record —
        check `sections.shareholders.missing` and `musterprotokoll.reasons`.
        """
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean(
            {
                "shareholderType": shareholder_type,
                "firstName": first_name,
                "lastName": last_name,
                "dob": dob,
                "nationality": nationality,
                "street": street,
                "houseNumber": house_number,
                "additional": additional,
                "postalCode": postal_code,
                "city": city,
                "country": country,
                "email": email,
                "phone": phone,
                "entityName": entity_name,
                "entitySeat": entity_seat,
                "entityRegisterCourt": entity_register_court,
                "entityRegisterNumber": entity_register_number,
                "shareNominalAmount": share_nominal_amount,
                "isManagingDirector": is_managing_director,
            },
        )
        return api._make_request("POST", _incorporations_url(f"{public_id}/shareholders/"), json_data=payload)

    @mcp.tool()
    async def update_incorporation_shareholder(
        ctx: Context,
        public_id: str = Field(description="Incorporation publicId"),
        shareholder_public_id: str = Field(description="Shareholder publicId from the record"),
        share_nominal_amount: str | None = Field(default=None, description="New Nennbetrag in full euros"),
        is_managing_director: bool | None = Field(
            default=None,
            description="True makes this shareholder the sole Geschäftsführer",
        ),
        first_name: str | None = Field(default=None),
        last_name: str | None = Field(default=None),
        dob: str | None = Field(default=None, description="YYYY-MM-DD"),
        nationality: str | None = Field(default=None),
        street: str | None = Field(default=None),
        house_number: str | None = Field(default=None),
        postal_code: str | None = Field(default=None),
        city: str | None = Field(default=None),
        country: str | None = Field(default=None),
    ) -> dict[str, Any]:
        """Update a shareholder (any subset of fields). Returns the full record."""
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean(
            {
                "shareNominalAmount": share_nominal_amount,
                "isManagingDirector": is_managing_director,
                "firstName": first_name,
                "lastName": last_name,
                "dob": dob,
                "nationality": nationality,
                "street": street,
                "houseNumber": house_number,
                "postalCode": postal_code,
                "city": city,
                "country": country,
            },
        )
        return api._make_request(
            "PATCH",
            _incorporations_url(f"{public_id}/shareholders/{shareholder_public_id}/"),
            json_data=payload,
        )

    @mcp.tool()
    async def invite_incorporation_shareholder(
        ctx: Context,
        public_id: str = Field(description="Incorporation publicId"),
        shareholder_public_id: str = Field(description="Shareholder publicId (natural person)"),
        email: str | None = Field(default=None, description="Email to send the invite to (required unless already stored)"),
    ) -> dict[str, Any]:
        """Send (or resend) a secure fill-your-details link to a co-founder.

        The invited shareholder completes their own personal data (name, date of birth,
        address) via the link — useful when the user doesn't have the co-founder's details
        at hand. Natural persons only. The link is valid for 30 days.
        """
        api = ctx.request_context.lifespan_context.get("api")
        return api._make_request(
            "POST",
            _incorporations_url(f"{public_id}/shareholders/{shareholder_public_id}/invite/"),
            json_data=_clean({"email": email}),
        )

    @mcp.tool()
    async def remove_incorporation_shareholder(
        ctx: Context,
        public_id: str = Field(description="Incorporation publicId"),
        shareholder_public_id: str = Field(description="Shareholder publicId to remove"),
    ) -> dict[str, Any]:
        """Remove a shareholder. Remaining shareholders are renumbered automatically."""
        api = ctx.request_context.lifespan_context.get("api")
        return api._make_request(
            "DELETE",
            _incorporations_url(f"{public_id}/shareholders/{shareholder_public_id}/"),
        )

    @mcp.tool()
    async def set_incorporation_agreement(
        ctx: Context,
        public_id: str = Field(description="Incorporation publicId"),
        agreement_type: str = Field(description="'musterprotokoll' or 'individual'"),
    ) -> dict[str, Any]:
        """Section 4/5 — founding agreement type.

        'musterprotokoll' (the statutory template — fastest and cheapest) is only accepted
        when `musterprotokoll.eligible` is true (≤3 shareholders, exactly one managing
        director, capital bounds, nominal split matches). Otherwise explain the `reasons`
        codes to the user and set 'individual' — the notary drafts an individual Satzung.
        """
        api = ctx.request_context.lifespan_context.get("api")
        return api._make_request(
            "PATCH",
            _incorporations_url(f"{public_id}/"),
            json_data={"agreementType": agreement_type},
        )

    @mcp.tool()
    async def update_incorporation_notary_preferences(
        ctx: Context,
        public_id: str = Field(description="Incorporation publicId"),
        notary_city: str | None = Field(default=None, description="Preferred city for the notary appointment"),
        notarization_type: str | None = Field(default=None, description="'online' (DiRUG video) or 'in_person'"),
        notarization_timeframe: str | None = Field(
            default=None,
            description="'within_7_days', 'within_2_weeks' or 'flexible'",
        ),
    ) -> dict[str, Any]:
        """Section 5/5 — notary preferences (city, online vs in person, timeframe)."""
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean(
            {
                "notaryCity": notary_city,
                "notarizationType": notarization_type,
                "notarizationTimeframe": notarization_timeframe,
            },
        )
        return api._make_request("PATCH", _incorporations_url(f"{public_id}/"), json_data=payload)

    @mcp.tool()
    async def generate_incorporation_documents(
        ctx: Context,
        public_id: str = Field(description="Incorporation publicId"),
    ) -> dict[str, Any]:
        """Generate the founding document drafts (PDF): Musterprotokoll (when selected) and
        the Gesellschafterliste (§ 40 GmbHG).

        REQUIRES sections company, shareholders, capital and agreement to be complete —
        summarize all collected data and get the user's explicit confirmation BEFORE calling.
        ALWAYS tell the user the documents are auto-generated templates to prepare the notary
        appointment — NOT legal advice; the notary produces the binding versions.
        Returns download URLs. If the user later changes data, `documentsStale` becomes true —
        offer to regenerate.
        """
        api = ctx.request_context.lifespan_context.get("api")
        response = api._make_request("POST", _incorporations_url(f"{public_id}/documents/"), json_data={})
        if isinstance(response, dict):
            for document in response.get("documents", []):
                document.pop("previewImage", None)
        return response

    @mcp.tool()
    async def get_incorporation_document_preview(
        ctx: Context,
        public_id: str = Field(description="Incorporation publicId"),
        document_type: str = Field(
            default="musterprotokoll",
            description="'musterprotokoll' or 'gesellschafterliste'",
        ),
    ) -> Any:
        """Show the user a first-page image of a generated founding document for review."""
        api = ctx.request_context.lifespan_context.get("api")
        response = api._make_request("GET", _incorporations_url(f"{public_id}/documents/"))
        for document in response.get("documents", []) if isinstance(response, dict) else []:
            if document.get("type") == document_type and document.get("previewImage"):
                return Image(data=base64.b64decode(document["previewImage"]), format="jpeg")
        return {"error": f"No preview available for '{document_type}'. Generate the documents first."}

    @mcp.tool()
    async def match_incorporation_notaries(
        ctx: Context,
        public_id: str = Field(description="Incorporation publicId"),
    ) -> dict[str, Any]:
        """Get up to 3 notaries matching the collected preferences (online capability, city).

        Present them to the user as options; they can pick one or request a match without
        picking (the Norman team assigns one).
        """
        api = ctx.request_context.lifespan_context.get("api")
        response = api._make_request("GET", _incorporations_url(f"{public_id}/notary-matches/"))
        if isinstance(response, list):
            return {"notaries": response}
        return response

    @mcp.tool()
    async def request_incorporation_notary(
        ctx: Context,
        public_id: str = Field(description="Incorporation publicId"),
        notary_public_id: str | None = Field(
            default=None,
            description="Picked notary's publicId; omit to let the Norman team match one",
        ),
        message: str = Field(default="", description="Optional message for the appointment request"),
    ) -> dict[str, Any]:
        """Final step — request the notary hand-off. REQUIRES generated documents.

        Get the user's explicit confirmation before calling. The Norman team coordinates the
        appointment and gets back to the user; nothing is sent to a notary automatically.
        """
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean({"notaryPublicId": notary_public_id, "message": message or None})
        return api._make_request(
            "POST",
            _incorporations_url(f"{public_id}/request-notary/"),
            json_data=payload,
        )

    @mcp.tool()
    async def suggest_incorporation_purpose(
        ctx: Context,
        public_id: str = Field(description="Incorporation publicId"),
        draft: str = Field(description="The founder's rough business-purpose text to reformulate"),
    ) -> dict[str, Any]:
        """Reformulate a rough business purpose (Unternehmensgegenstand) into registry-ready wording.

        Returns {"suggestion": ...} — a faithful, same-language rewrite: concrete activities, no
        catch-all phrases ("all permitted activities"), no licensable activities unless the draft
        states them, nothing invented. ALWAYS show it to the user and let them accept or keep their
        own text; never auto-apply. To use it, pass it to update_incorporation_company as
        business_purpose.
        """
        api = ctx.request_context.lifespan_context.get("api")
        return api._make_request(
            "POST",
            _incorporations_url(f"{public_id}/suggest-purpose/"),
            json_data={"draft": draft},
        )

    @mcp.tool()
    async def check_incorporation_name(
        ctx: Context,
        public_id: str = Field(description="Incorporation publicId"),
        name: str | None = Field(
            default=None,
            description="Name to check; omit to use the record's current company name",
        ),
    ) -> dict[str, Any]:
        """Search the German commercial register (Handelsregister) for similar company names.

        Returns {"status": "ok"|"unavailable", "searched", "matches": [{name, seat, register}]}.
        `status == "unavailable"` means the portal could not be queried — tell the user to check
        manually via handelsregister.de, do NOT infer the name is free. Existing matches mean a
        similar name may be rejected; the final say is with the registry court and the IHK.
        """
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean({"name": name})
        return api._make_request(
            "POST",
            _incorporations_url(f"{public_id}/check-name/"),
            json_data=payload,
        )

    @mcp.tool()
    async def complete_incorporation_step(
        ctx: Context,
        public_id: str = Field(description="Incorporation publicId"),
        step: str = Field(
            description=(
                "Roadmap step key: 'notary', 'bank_account', 'deposit', 'hrb', 'finanzamt', "
                "'gewerbeamt' or 'transparency'"
            ),
        ),
        done: bool = Field(default=True, description="Mark the step done (True) or undo it (False)"),
        register_number: str = Field(
            default="",
            description="For the 'hrb' step only: the HRB number from the Handelsregister",
        ),
        register_court: str = Field(
            default="",
            description="For the 'hrb' step only: the registering court (Amtsgericht)",
        ),
    ) -> dict[str, Any]:
        """Tick a post-notary formation roadmap step done/undone (steps 3-9 of the journey).

        The record's `roadmap` lists the 7 steps with their `done`/`active` state — drive from it.
        These are founder self-marks: they do NOT send the ops milestone emails and never move the
        official `status` backwards. The 'hrb' step optionally records the register number/court.
        Returns the full updated record (with the refreshed `roadmap`).
        """
        api = ctx.request_context.lifespan_context.get("api")
        payload = _clean(
            {
                "step": step,
                "done": done,
                "registerNumber": register_number or None,
                "registerCourt": register_court or None,
            },
        )
        return api._make_request(
            "POST",
            _incorporations_url(f"{public_id}/formation-step/"),
            json_data=payload,
        )
