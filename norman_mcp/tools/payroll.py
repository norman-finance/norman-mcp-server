"""Payroll (Lohnabrechnung) for GmbH/UG companies.

People, the monthly payroll, social insurance, payments, the Lohnsteuer-Anmeldung
and AAG reimbursement, read from the Norman API. Payroll is part of the Max plan
and open to the company's owner and its tax advisor; the API enforces both.

Government identifiers (Steuer-ID, Rentenversicherungsnummer), birth data, home
addresses and employees' bank details stay in the authenticated Norman app: the
tools withhold them, and an IBAN is reduced to its last four characters. Dates of
sickness or maternity absences are withheld too; amounts and day counts remain.
"""

from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin

from mcp.types import ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context
from norman_mcp.tools.results import as_object

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False)

NO_COMPANY_ERROR = {"error": "No company available. Please authenticate first."}

# Withheld from every person record: identifiers, birth data, address and bank details.
_PRIVATE_PERSON_FIELDS = frozenset({
    "taxIdNr", "insuranceNumber", "dateOfBirth", "birthName", "birthPlace", "gender",
    "street", "houseNumber", "postalCode", "city", "iban", "bic", "accountHolder",
})


def _payroll_url(company_id: str, path: str = "") -> str:
    return urljoin(config.api_base_url, f"api/v1/companies/{company_id}/payroll/{path}")


def _app_url(path: str = "") -> str:
    base = (
        "https://app.norman.finance/"
        if config.NORMAN_ENVIRONMENT.lower() == "production"
        else "https://dev.norman.finance/"
    )
    return urljoin(base, path)


def _failed(result: Any) -> dict[str, Any] | None:
    """The API's error payload, with a 403 explained; None when the call succeeded."""
    if not isinstance(result, dict) or not result.get("error"):
        return None
    if result.get("status_code") == 403:
        return {
            "error": "Payroll is available on the Max plan to the company's owner and its tax advisor.",
            "status_code": 403,
            "url": _app_url("payroll"),
        }
    return result


def _amount(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else 0))
    except InvalidOperation:
        return Decimal(0)


def _masked_iban(iban: Any) -> str | None:
    compact = "".join(str(iban or "").split())
    return f"…{compact[-4:]}" if len(compact) >= 8 else None


def _without_dates(value: Any) -> Any:
    """Drop absence date lists (sickness, employment ban) at any depth; counts stay."""
    if isinstance(value, dict):
        return {key: _without_dates(item) for key, item in value.items() if not str(key).endswith("Dates")}
    if isinstance(value, list):
        return [_without_dates(item) for item in value]
    return value


def _person(record: Any) -> Any:
    if not isinstance(record, dict):
        return record
    person = {key: value for key, value in record.items() if key not in _PRIVATE_PERSON_FIELDS}
    person["bankAccount"] = _masked_iban(record.get("iban"))
    return person


def _line(line: Any) -> Any:
    """One person's payroll month without the frozen personal snapshot.

    The snapshot holds identifiers, the address and absence records; only the
    employment period and the contractual gross are kept from it.
    """
    if not isinstance(line, dict):
        return line
    snapshot = line.get("snapshot") or {}
    reduced = _without_dates({key: value for key, value in line.items() if key != "snapshot"})
    if isinstance(reduced.get("socialInsurance"), dict):
        reduced["socialInsurance"] = {k: v for k, v in reduced["socialInsurance"].items() if k != "note"}
    if snapshot.get("employment"):
        reduced["employment"] = snapshot["employment"]
    if snapshot.get("contractualGross") is not None:
        reduced["contractualGross"] = snapshot["contractualGross"]
    taxes = sum((_amount(line.get(key)) for key in ("lohnsteuer", "soli", "kirchensteuer")), Decimal(0))
    payout = (_amount(line.get("gross")) - taxes - _amount(line.get("svEmployee"))
              + _amount(line.get("kvZuschuss")) + _amount(line.get("pvZuschuss")))
    reduced["taxes"] = f"{taxes:.2f}"
    reduced["payout"] = f"{payout:.2f}"
    return reduced


def _month(review: Any) -> dict[str, Any]:
    if _failed(review) or not isinstance(review, dict):
        return _failed(review) or as_object(review)
    return {**review, "lines": [_line(line) for line in review.get("lines") or []]}


def _run(run: Any) -> Any:
    if not isinstance(run, dict):
        return run
    return {**run, "lines": [_line(line) for line in run.get("lines") or []]}


def register_payroll_tools(mcp):
    """Register the payroll (Lohnabrechnung) tools."""

    def _api(ctx: Context) -> Any:
        return ctx.request_context.lifespan_context["api"]

    async def _get(ctx: Context, path: str, params: dict[str, Any] | None = None) -> Any:
        api = _api(ctx)
        return await api.arequest("GET", _payroll_url(api.company_id, path), params=params)

    @mcp.tool(title="Get Payroll Overview", annotations=READ_ONLY)
    async def get_payroll_overview(ctx: Context) -> dict[str, Any]:
        """Where the company stands with payroll (Lohnabrechnung).

        Returns whether the employer data is complete, the number of people, the
        approved months and the latest one, and whether its Lohnsteuer-Anmeldung was
        filed and the month paid. Payroll covers the managing director and employees of
        a GmbH/UG (statutory, private, midijob and commercial minijob); it is part of the
        Max plan. Start here, then use get_payroll_month for a month's numbers.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _get(ctx, "payroll-months/progress/")
        return _failed(result) or as_object(result)

    @mcp.tool(title="List Payroll People", annotations=READ_ONLY)
    async def list_payroll_people(
        ctx: Context,
        include_inactive: bool = Field(default=False, description="Also list people whose employment ended"),
    ) -> dict[str, Any]:
        """List the managing directors and employees on the payroll.

        Each person has `publicId` (use it as person_id), `directorName`,
        `employmentKind` (DIRECTOR or EMPLOYEE), `insuranceProfile` (STATUTORY,
        PRIVATE_NO_SV for a controlling shareholder-director, or MINIJOB), the current
        monthly gross, the tax profile, the employment dates and `bankAccount` (last four
        characters of the IBAN). Steuer-ID, birth data, address and bank details are
        withheld; they are entered in the Norman app.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _get(ctx, "gf-salaries/", params={"pageSize": 1000})
        if _failed(result):
            return _failed(result)
        people = result.get("results", []) if isinstance(result, dict) else list(result or [])
        if not include_inactive:
            people = [person for person in people if person.get("isActive", True)]
        return {"count": len(people), "results": [_person(person) for person in people]}

    @mcp.tool(title="Get Payroll Person", annotations=READ_ONLY)
    async def get_payroll_person(
        ctx: Context,
        person_id: str = Field(description="publicId of the person, from list_payroll_people"),
    ) -> dict[str, Any]:
        """One person on the payroll with salary and tax history and social insurance.

        Includes the salary changes, tax profile changes and the recorded social
        insurance profiles (health fund or Minijob-Zentrale, contribution rates, minijob
        details). Identifiers, birth data, address and bank details are withheld.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        person = await _get(ctx, f"gf-salaries/{person_id}/")
        if _failed(person):
            return _failed(person)
        result = _person(as_object(person))
        if result.get("employmentKind") == "EMPLOYEE" or result.get("insuranceProfile") in ("STATUTORY", "MINIJOB"):
            profiles = await _get(ctx, f"gf-salaries/{person_id}/social-insurance-profiles/")
            if not _failed(profiles):
                rows = profiles if isinstance(profiles, list) else as_object(profiles).get("results", [])
                result["socialInsuranceProfiles"] = [
                    {key: value for key, value in row.items() if key != "note"} for row in rows
                ]
        return result

    @mcp.tool(title="Get Payroll Month", annotations=READ_ONLY)
    async def get_payroll_month(
        ctx: Context,
        year: int = Field(ge=2024, le=2100, description="Calendar year, e.g. 2026"),
        month: int = Field(ge=1, le=12, description="Month 1-12"),
    ) -> dict[str, Any]:
        """The payroll of one month: status, people, totals and what blocks it.

        `status` is NOT_CALCULATED, CALCULATED (a draft, not approved yet),
        RECALCULATION_REQUIRED (recorded data changed since) or APPROVED. Each line has gross, Lohnsteuer, Soli,
        Kirchensteuer, `taxes`, employee and employer social insurance, `payout` (what the
        person receives) and, for insured people, `socialInsurance` with the fund, the
        Beitragsgruppe and the contributions. `issues` say what must be fixed in the
        Norman app before the month can be calculated or approved. `revision` and
        `fingerprint` identify the reviewed version.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        return _month(await _get(ctx, "payroll-months/inspect/", params={"year": year, "month": month}))

    @mcp.tool(title="Calculate Payroll Month", annotations=WRITE)
    async def calculate_payroll_month(
        ctx: Context,
        year: int = Field(ge=2024, le=2100, description="Calendar year, e.g. 2026"),
        month: int = Field(ge=1, le=12, description="Month 1-12"),
    ) -> dict[str, Any]:
        """Calculate (or recalculate) the draft payroll of one month.

        Uses the people, salaries, tax and social insurance data and absences recorded
        in Norman; nothing is approved, booked, paid or filed. An approved month cannot be
        recalculated: it changes only through a correction in the Norman app. Returns the
        same review as get_payroll_month; when it reports `issues`, tell the user what to
        complete in the app.
        """
        api = _api(ctx)
        if not api.company_id:
            return NO_COMPANY_ERROR
        result = await api.arequest(
            "POST", _payroll_url(api.company_id, "payroll-months/calculate/"),
            json_data={"year": year, "month": month},
        )
        return _month(result)

    @mcp.tool(title="Get Social Insurance Contributions", annotations=READ_ONLY)
    async def get_social_insurance_contributions(
        ctx: Context,
        year: int = Field(ge=2024, le=2100, description="Calendar year, e.g. 2026"),
        month: int = Field(ge=1, le=12, description="Month 1-12"),
    ) -> dict[str, Any]:
        """Social insurance contributions of one month, per person and per collecting body.

        `funds` totals what goes to each Krankenkasse or to the Minijob-Zentrale
        (Betriebsnummer 98000006); `rows` give each person's Personengruppe,
        Beitragsgruppe and contributions (for a minijob the flat charges and the 2 % flat
        tax). Before approval it is a preview from the recorded data; afterwards it comes
        from the approved version. Nothing is reported or paid.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _get(ctx, "payroll-months/social-insurance-preview/", params={"year": year, "month": month})
        if _failed(result) or not isinstance(result, dict):
            return _failed(result) or as_object(result)
        rows = [{key: value for key, value in row.items() if key != "note"} for row in result.get("rows") or []]
        return _without_dates({**result, "rows": rows})

    @mcp.tool(title="Get Contribution Plan", annotations=READ_ONLY)
    async def get_contribution_plan(
        ctx: Context,
        year: int = Field(ge=2024, le=2100, description="Calendar year, e.g. 2026"),
        month: int = Field(ge=1, le=12, description="Month 1-12"),
    ) -> dict[str, Any]:
        """The Beitragsnachweis estimate of one month, per Krankenkasse or Minijob-Zentrale.

        Contributions are due before the month's payroll is final, so the employer reports
        an estimate. `funds` gives each collecting body's estimate, the prior month's
        difference carried over and the planned amount. `status` PREVIEW means nothing is
        saved yet; a saved plan has an `id`. The contribution statement is sent by the user
        through the SV-Meldeportal; Norman does not transmit it.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _get(ctx, "payroll-months/contribution-plan/", params={"year": year, "month": month})
        if _failed(result) or not isinstance(result, dict):
            return _failed(result) or as_object(result)
        snapshot = result.get("snapshot") or {}
        return {
            **{key: value for key, value in result.items() if key != "snapshot"},
            "start": snapshot.get("start"),
            "funds": snapshot.get("funds", []),
        }

    @mcp.tool(title="Get Payroll Payments", annotations=READ_ONLY)
    async def get_payroll_payments(
        ctx: Context,
        year: int = Field(ge=2024, le=2100, description="Calendar year, e.g. 2026"),
        month: int = Field(ge=1, le=12, description="Month 1-12"),
    ) -> dict[str, Any]:
        """What the approved month still has to pay, and to whom.

        `payouts` are net salaries per person, `funds` the social insurance per
        Krankenkasse or Minijob-Zentrale, `wageTax` the Lohnsteuer to the Finanzamt. Each
        item has the amount due, what is in flight or already matched to the bank
        statement, its state and the transfer purpose. Employees' IBANs are shown as their
        last four characters only. Nothing is paid here.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _get(ctx, "payroll-months/transfers/", params={"year": year, "month": month})
        if _failed(result) or not isinstance(result, dict):
            return _failed(result) or as_object(result)
        payouts = [
            {**{key: value for key, value in item.items() if key not in ("iban", "bic")},
             "bankAccount": _masked_iban(item.get("iban"))}
            for item in result.get("payouts") or []
        ]
        return {**result, "payouts": payouts}

    @mcp.tool(title="List Wage Tax Returns", annotations=READ_ONLY)
    async def list_wage_tax_returns(
        ctx: Context,
        year: int | None = Field(default=None, ge=2024, le=2100, description="Only this year; omit for all"),
    ) -> dict[str, Any]:
        """List the Lohnsteuer-Anmeldungen (wage tax returns) with their status.

        Each return covers a filing period (`zeitraum`: month, quarter or year), the
        number of people, gross, Lohnsteuer, Soli and Kirchensteuer, and `status` (DRAFT,
        SUBMITTING while ELSTER confirms, FILED; `filedOutsideNorman` when it was filed
        elsewhere). Minijobs with the 2 % flat
        tax count as people but carry no Lohnsteuer here.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _get(ctx, "payroll-runs/", params={"pageSize": 1000})
        if _failed(result):
            return _failed(result)
        runs = result.get("results", []) if isinstance(result, dict) else list(result or [])
        if year is not None:
            runs = [run for run in runs if run.get("year") == year]
        return {
            "count": len(runs),
            "results": [{key: value for key, value in run.items() if key != "lines"} for run in runs],
        }

    @mcp.tool(title="Get Wage Tax Return", annotations=READ_ONLY)
    async def get_wage_tax_return(
        ctx: Context,
        run_id: str = Field(description="publicId of the Lohnsteuer-Anmeldung, from list_wage_tax_returns"),
    ) -> dict[str, Any]:
        """One Lohnsteuer-Anmeldung with its per-person lines.

        `requiresRecalculation` or `unapprovedMonths` mean the return cannot be filed yet.
        Filing goes through ELSTER from the Norman app.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _get(ctx, f"payroll-runs/{run_id}/")
        return _failed(result) or _run(as_object(result))

    @mcp.tool(title="Get AAG Reimbursement", annotations=READ_ONLY)
    async def get_aag_claim(
        ctx: Context,
        year: int = Field(ge=2024, le=2100, description="Calendar year, e.g. 2026"),
        month: int = Field(ge=1, le=12, description="Month 1-12"),
    ) -> dict[str, Any]:
        """Prepared AAG reimbursement (U1 sick pay, U2 maternity) of an approved month.

        U1 rows show the days of continued pay and the amount the Krankenkasse
        reimburses under its own terms; a minijob is claimed from the Minijob-Zentrale and
        listed without an amount. `issues` name missing employer terms. Day counts only,
        no dates. Nothing is submitted or booked.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _get(ctx, "payroll-months/aag-claim/", params={"year": year, "month": month})
        return _failed(result) or _without_dates(as_object(result))

    @mcp.tool(title="Get Employer Payroll Setup", annotations=READ_ONLY)
    async def get_employer_payroll_setup(ctx: Context) -> dict[str, Any]:
        """The employer data payroll needs, and what is still missing.

        Betriebsnummer, accident insurance (Unfallversicherung) membership, the payroll
        contact and the AAG terms of the Krankenkasse (U1 rate and treatment of employer
        contributions). `issues` list what to complete in the Norman app; `revision` and
        `identityFingerprint` identify the reviewed version.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _get(ctx, "employer-setup/")
        if _failed(result) or not isinstance(result, dict):
            return _failed(result) or as_object(result)
        current = result.get("current") or {}
        return {
            "revision": current.get("revision"),
            "data": current.get("data"),
            "identity": result.get("identity"),
            "identityFingerprint": result.get("identityFingerprint"),
            "dataComplete": result.get("dataComplete"),
            "issues": result.get("issues", []),
            "registrationStatus": result.get("registrationStatus"),
        }

    async def _document(ctx: Context, path: str, params: dict[str, Any], label: str) -> dict[str, Any]:
        result = await _get(ctx, path, params={**params, "response_format": "download_url"})
        if _failed(result):
            return _failed(result)
        if not isinstance(result, dict) or not result.get("downloadUrl"):
            return {"error": f"The {label} could not be linked; open it in the Norman app.", "url": _app_url("payroll")}
        return result

    @mcp.tool(title="Get Payslip", annotations=READ_ONLY)
    async def get_payslip(
        ctx: Context,
        person_id: str = Field(description="publicId of the person, from list_payroll_people"),
        year: int = Field(ge=2024, le=2100, description="Calendar year, e.g. 2026"),
        month: int = Field(ge=1, le=12, description="Month 1-12"),
    ) -> dict[str, Any]:
        """A one-hour download link to the payslip (Gehaltsabrechnung) PDF of one month.

        The month must be calculated or approved. Present `downloadUrl` to the user; the
        PDF contains the person's personal data.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        return await _document(ctx, f"gf-salaries/{person_id}/payslip/", {"year": year, "month": month}, "payslip")

    @mcp.tool(title="Get Lohnkonto", annotations=READ_ONLY)
    async def get_lohnkonto(
        ctx: Context,
        person_id: str = Field(description="publicId of the person, from list_payroll_people"),
        year: int = Field(ge=2024, le=2100, description="Calendar year, e.g. 2026"),
    ) -> dict[str, Any]:
        """A one-hour download link to the Lohnkonto PDF of one year (§ 41 EStG).

        The payroll account an employer must keep per person, with every month of the
        year and the data for the annual social insurance report. Present `downloadUrl` to
        the user; the PDF contains the person's personal data.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        return await _document(ctx, f"gf-salaries/{person_id}/lohnkonto/", {"year": year}, "Lohnkonto")
