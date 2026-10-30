from typing import Any, Literal

from pydantic import Field

from norman_mcp.context import Context
from norman_mcp.tools.accounting import READ_ONLY, WRITE, _api_and_company, _compact, _company_url

PATH = "accounting/verfahrensdokumentation/"


def register_verfahrensdokumentation_tools(mcp: Any) -> None:
    @mcp.tool(title="Get Verfahrensdokumentation Answers", annotations=READ_ONLY)
    async def get_verfahrensdokumentation(ctx: Context) -> dict[str, Any]:
        """Read the company's saved answers for its GoBD Verfahrensdokumentation. German companies only.

        Norman creates the PDF fresh at each download from these answers and the company's current data. It is free on
        every plan. The user downloads it in the app: Export on the transactions page, or Export GoBD in the ledger.
        There is no link to it. Say plainly that the document stays the customer's own, nobody at Norman reviews it
        and Norman holds no GoBD attestation.
        """
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await api.arequest("GET", _company_url(company_id, PATH))

    @mcp.tool(title="Update Verfahrensdokumentation Answers", annotations=WRITE)
    async def update_verfahrensdokumentation(  # noqa: PLR0913
        ctx: Context,
        documents_captured_by: str | None = Field(default=None, description="Who captures documents in Norman"),
        bookings_checked_by: str | None = Field(default=None, description="Who checks and finalizes the bookings"),
        capture_rhythm: Literal["daily", "weekly", "monthly", ""] | None = Field(
            default=None, description="How often documents are captured and checked",
        ),
        paper_originals: Literal["no_paper", "kept", "destroyed", ""] | None = Field(
            default=None, description="What happens to paper documents after capture",
        ),
        paper_storage: str | None = Field(default=None, description="Where kept paper originals are stored"),
        other_systems: str | None = Field(default=None, description="Systems used outside Norman, such as a till"),
    ) -> dict[str, Any]:
        """Save the answers the user states for the GoBD Verfahrensdokumentation. German companies only.

        Send only what the user said; omitted answers stay as they are. Never guess a process for the user. Norman logs
        each change. The user then downloads the PDF in the app.
        """
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await api.arequest(
            "PATCH",
            _company_url(company_id, PATH),
            json_data=_compact({
                "documentsCapturedBy": documents_captured_by,
                "bookingsCheckedBy": bookings_checked_by,
                "captureRhythm": capture_rhythm,
                "paperOriginals": paper_originals,
                "paperStorage": paper_storage,
                "otherSystems": other_systems,
            }),
        )
