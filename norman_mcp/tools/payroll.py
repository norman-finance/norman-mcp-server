"""Payroll (Lohnabrechnung) for GmbH/UG companies.

People, the monthly payroll, social insurance, payments, the Lohnsteuer-Anmeldung
and AAG reimbursement, read from the Norman API. Payroll is part of the Max plan
and open to the company's owner and its tax advisor; the API enforces both.

Government identifiers (Steuer-ID, Rentenversicherungsnummer), birth data, home
addresses and employees' bank details stay in the authenticated Norman app: the
tools withhold them, and an IBAN is reduced to its last four characters. Dates of
sickness or maternity absences are withheld too; amounts and day counts remain.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import urljoin
from uuid import uuid4

from mcp.types import ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context
from norman_mcp.tools.results import as_object

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False)
# Approving, correcting or recording a filing changes booked data; only a correction undoes it.
DESTRUCTIVE_WRITE = ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=True)
# A binding transmission to the tax office.
EXTERNAL_IRREVERSIBLE_WRITE = ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=True)

NO_COMPANY_ERROR = {"error": "No company available. Please authenticate first."}

# Withheld from every person record: identifiers, birth data, address and bank details.
_PRIVATE_PERSON_FIELDS = frozenset({
    "taxIdNr", "insuranceNumber", "dateOfBirth", "birthName", "birthPlace", "gender",
    "street", "houseNumber", "postalCode", "city", "iban", "bic", "accountHolder",
})


def _snake(key: str) -> str:
    """API camelCase (``u1ReimbursementRate``) back to the request's snake_case."""
    return re.sub(r"([A-Z])", r"_\1", key).lower()


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
    """A month review or correction with every line reduced, including a pending correction's."""
    if _failed(review) or not isinstance(review, dict):
        return _failed(review) or as_object(review)
    cleaned = dict(review)
    if "lines" in cleaned:
        cleaned["lines"] = [_line(line) for line in cleaned.get("lines") or []]
    pending = cleaned.get("pendingCorrection")
    if isinstance(pending, dict) and "lines" in pending:
        cleaned["pendingCorrection"] = {**pending, "lines": [_line(line) for line in pending.get("lines") or []]}
    return cleaned


def _link(result: Any) -> dict[str, Any] | None:
    """The one-hour download link of an API document answer, if it carries one."""
    if isinstance(result, dict) and result.get("downloadUrl"):
        return {key: result.get(key) for key in ("downloadUrl", "fileName", "expiresInSeconds")}
    return None


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
        last four characters only. Nothing is paid here: `payUrl` opens the month in the
        Norman app, where "Monat bezahlen" sends one collective transfer that the user
        confirms at the bank.
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
        # Paying stays in the app: one collective transfer the user confirms at the bank.
        return {**result, "payouts": payouts, "payUrl": _app_url(f"payroll?view=month&year={year}&month={month}")}

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

    # --- Recording data (reversible: a later record or a correction supersedes it) ---

    async def _post(ctx: Context, path: str, body: dict[str, Any], params: dict[str, Any] | None = None) -> Any:
        api = _api(ctx)
        return await api.arequest("POST", _payroll_url(api.company_id, path), params=params, json_data=body)

    @mcp.tool(title="Record Salary Change", annotations=WRITE)
    async def record_salary_change(
        ctx: Context,
        person_id: str = Field(description="publicId of the person, from list_payroll_people"),
        effective_from: date = Field(description="First day of the new monthly salary (YYYY-MM-DD)"),
        monthly_gross: Decimal = Field(gt=0, description="New contractual gross per month in EUR"),
        note: str = Field(default="", max_length=255, description="Reason, e.g. 'Raise per agreement of 12.01.2027'"),
    ) -> dict[str, Any]:
        """Record a new monthly gross salary from a date (raise, reduction, new agreement).

        Earlier months keep their salary. An approved month is not changed: correct it in
        the Norman app. Recalculate affected draft months afterwards (calculate_payroll_month).
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _post(ctx, f"gf-salaries/{person_id}/salary-changes/", {
            "effective_from": effective_from.isoformat(), "monthly_gross": f"{monthly_gross:.2f}", "note": note,
        })
        return _failed(result) or as_object(result)

    @mcp.tool(title="Record Tax Profile Change", annotations=WRITE)
    async def record_tax_profile_change(
        ctx: Context,
        person_id: str = Field(description="publicId of the person, from list_payroll_people"),
        effective_from: date = Field(description="First day the new tax data applies (YYYY-MM-DD)"),
        tax_class: int = Field(ge=1, le=6, description="Steuerklasse 1-6"),
        church: Literal["", "EV", "RK"] = Field(description="Kirchensteuer: '' none, 'EV' Protestant, 'RK' Catholic"),
        church_rate: Literal["8", "9"] = Field(description="Kirchensteuer rate: 8 in Bavaria and Baden-Württemberg, else 9"),
        child_allowance_factor: Decimal = Field(ge=0, description="Kinderfreibeträge, e.g. 0, 0.5, 1.0"),
        source: Literal["ELSTAM_NOTICE", "TAX_OFFICE_CERTIFICATE"] = Field(
            description="Where the data comes from: the ELStAM notice or a tax office certificate",
        ),
        note: str = Field(min_length=1, max_length=255, description="Reference to that notice, e.g. its date"),
    ) -> dict[str, Any]:
        """Record changed wage tax data (ELStAM) of a person from a date.

        Use the values of the ELStAM notice or the tax office certificate. Recalculate
        affected draft months afterwards.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _post(ctx, f"gf-salaries/{person_id}/tax-profile-changes/", {
            "effective_from": effective_from.isoformat(), "tax_class": tax_class, "church": church,
            "church_rate": church_rate, "child_allowance_factor": f"{child_allowance_factor:.1f}",
            "source": source, "note": note,
        })
        return _failed(result) or as_object(result)

    @mcp.tool(title="Set Employment End", annotations=WRITE)
    async def set_employment_end(
        ctx: Context,
        person_id: str = Field(description="publicId of the person, from list_payroll_people"),
        employment_end: date | None = Field(description="Last day of employment (YYYY-MM-DD); null to remove it"),
    ) -> dict[str, Any]:
        """Record the last day of a person's employment, or remove it.

        The final month is prorated by calendar days. A date inside an approved month is
        refused; correct that month in the Norman app. The deregistration (Abmeldung) is
        sent by the user through the SV-Meldeportal.
        """
        api = _api(ctx)
        if not api.company_id:
            return NO_COMPANY_ERROR
        result = await api.arequest(
            "PATCH", _payroll_url(api.company_id, f"gf-salaries/{person_id}/"),
            json_data={"employment_end": employment_end.isoformat() if employment_end else None},
        )
        if _failed(result):
            return _failed(result)
        # The PATCH answer is not the stored record; read it back.
        person = await _get(ctx, f"gf-salaries/{person_id}/")
        return _failed(person) or _person(as_object(person))

    @mcp.tool(title="Record Statutory Insurance", annotations=WRITE)
    async def record_statutory_insurance(
        ctx: Context,
        person_id: str = Field(description="publicId of the person, from list_payroll_people"),
        effective_from: date = Field(description="First day these data apply (YYYY-MM-DD)"),
        fund_name: str = Field(max_length=120, description="Krankenkasse, e.g. 'Techniker Krankenkasse'"),
        fund_number: str = Field(pattern=r"^[0-9]{8}$", description="8-digit Betriebsnummer of the Krankenkasse"),
        health_insurance_extra_rate: Decimal = Field(ge=0, description="Zusatzbeitrag of that fund in %, e.g. 2.69"),
        u2_rate: Decimal = Field(ge=0, description="U2 levy rate of the fund in %"),
        care_insurance_surcharge: bool = Field(description="True if the childless surcharge on PV applies"),
        pv_children_under25: int = Field(ge=0, le=5, description="Children under 25 for the PV reduction (0-5)"),
        saxony: bool = Field(description="True if the place of employment is in Saxony"),
        standard_case_confirmed: bool = Field(
            description="The user confirms an ordinary case: fully insured in KV, RV, AV and PV, no special group",
        ),
        source: Literal["INSURER_NOTICE", "ADVISOR_REVIEW"] = Field(description="Where the data comes from"),
        note: str = Field(min_length=1, max_length=255, description="Reference, e.g. 'Mitgliedsbescheinigung TK vom 02.01.2027'"),
        u1_rate: Decimal | None = Field(default=None, ge=0, description="U1 levy rate in % if the employer takes part in U1"),
    ) -> dict[str, Any]:
        """Record the social insurance data of an employee with statutory insurance.

        Needed before the first month can be calculated, and again when the fund, the
        Zusatzbeitrag or the children change. Midijobs (up to €2,000) use this too; the
        transition zone is applied automatically.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _post(ctx, f"gf-salaries/{person_id}/social-insurance-profiles/", {
            "effective_from": effective_from.isoformat(), "fund_name": fund_name, "fund_number": fund_number,
            "health_insurance_extra_rate": f"{health_insurance_extra_rate:.2f}", "u2_rate": f"{u2_rate:.2f}",
            "u1_rate": f"{u1_rate:.2f}" if u1_rate is not None else None,
            "care_insurance_surcharge": care_insurance_surcharge, "pv_children_under25": pv_children_under25,
            "saxony": saxony, "standard_case_confirmed": standard_case_confirmed, "source": source, "note": note,
        })
        return _failed(result) or as_object(result)

    @mcp.tool(title="Record Minijob Details", annotations=WRITE)
    async def record_minijob_details(
        ctx: Context,
        person_id: str = Field(description="publicId of a person with the MINIJOB insurance profile"),
        effective_from: date = Field(description="First day these data apply (YYYY-MM-DD)"),
        health_insured: bool = Field(description="True if the person has statutory health insurance (flat 13 % KV)"),
        pension_exempt: bool = Field(description="True only with the person's written request for RV exemption"),
        other_employment: bool = Field(description="True if the person has another job with pension insurance"),
        u1_participation: bool = Field(description="True if the employer takes part in the U1 levy"),
        standard_case_confirmed: bool = Field(
            description="The user confirms a commercial minijob with fixed pay, not a private household",
        ),
        note: str = Field(min_length=1, max_length=255, description="Reference to the documents, e.g. the exemption request"),
    ) -> dict[str, Any]:
        """Record the minijob details of a commercial minijob (up to €603 a month in 2026).

        These decide the flat contributions to the Minijob-Zentrale: KV 13 % only with
        statutory health insurance, RV 15 % plus 3.6 % from the person unless exempt.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _post(ctx, f"gf-salaries/{person_id}/social-insurance-profiles/", {
            "effective_from": effective_from.isoformat(), "minijob_health_insured": health_insured,
            "minijob_pension_exempt": pension_exempt, "minijob_other_employment": other_employment,
            "u1_participation": u1_participation, "standard_case_confirmed": standard_case_confirmed,
            "source": "EMPLOYEE_DOCUMENTS", "note": note,
        })
        return _failed(result) or as_object(result)

    @mcp.tool(title="Record Work Schedule", annotations=WRITE)
    async def record_work_schedule(
        ctx: Context,
        person_id: str = Field(description="publicId of the person, from list_payroll_people"),
        effective_from: date = Field(description="First day of the schedule (YYYY-MM-DD)"),
        daily_hours: list[Decimal] = Field(
            min_length=7, max_length=7,
            description="Agreed hours Monday to Sunday, 0 for days off, e.g. [8, 8, 8, 8, 8, 0, 0]",
        ),
        source_reference: str = Field(min_length=1, max_length=255, description="Where it is agreed, e.g. the contract"),
    ) -> dict[str, Any]:
        """Record the agreed weekly working hours of a person from a date.

        Absences (vacation, sickness) are counted against this schedule, so it must cover
        their dates. A date inside an approved month is refused.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        period = {"year": effective_from.year, "month": effective_from.month}
        review = await _get(ctx, f"gf-salaries/{person_id}/work-schedules/", params=period)
        if _failed(review) or not isinstance(review, dict):
            return _failed(review) or as_object(review)
        result = await _post(ctx, f"gf-salaries/{person_id}/work-schedules/", {
            "expected_revision": review.get("latestRevision", 0),
            "reviewed_employment": review.get("employmentFingerprint"),
            "effective_from": effective_from.isoformat(),
            "daily_hours": [f"{hours:.2f}" for hours in daily_hours],
            "source_reference": source_reference,
        }, params=period)
        return _failed(result) or as_object(result)

    @mcp.tool(title="Record Absence", annotations=WRITE)
    async def record_absence(
        ctx: Context,
        person_id: str = Field(description="publicId of the person, from list_payroll_people"),
        kind: Literal["PAID_VACATION", "SICKNESS"] = Field(description="Paid vacation or ordinary sickness"),
        start_date: date = Field(description="First full day of the absence (YYYY-MM-DD)"),
        end_date: date = Field(description="Last full day of the absence (YYYY-MM-DD)"),
        source_reference: str = Field(
            min_length=1, max_length=255,
            description="Evidence without a diagnosis, e.g. 'Vacation request of 02.03.' or 'AU certificate of 05.03.'",
        ),
        vacation_pay_confirmed: bool = Field(
            default=False, description="Vacation: the user confirms that the fixed salary covers the vacation pay",
        ),
        incapacity_start: date | None = Field(
            default=None, description="Sickness: first day of this uninterrupted incapacity, if earlier than start_date",
        ),
        prior_used_days: int = Field(
            default=0, ge=0, le=42,
            description="Sickness: continued-pay days already used for the same illness before this incapacity",
        ),
        prior_illnesses_reviewed: bool = Field(
            default=False, description="Sickness: the user confirms prior and overlapping illnesses were checked",
        ),
        sick_note_reviewed: bool = Field(
            default=False,
            description="Sickness: the user confirms the sick note was checked and the ordinary statutory claim applies",
        ),
        fixed_salary_covers_sick_pay: bool = Field(
            default=False, description="Sickness: the user confirms the fixed salary covers the continued pay",
        ),
        no_work_on_first_day: bool = Field(
            default=False, description="Sickness: the user confirms no work was done on the first day",
        ),
    ) -> dict[str, Any]:
        """Record paid vacation or an ordinary sickness of a person, full days only.

        Sickness is paid for up to six weeks under § 3 EFZG after four weeks of employment;
        ask the user to confirm each sickness statement, never assume it. Never put a
        diagnosis in source_reference. A work schedule must cover the dates. Other kinds
        (unpaid leave, Krankengeld, employment ban, parental leave) are recorded in the
        Norman app. Recalculate the affected month afterwards.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        data: dict[str, Any] = {
            "start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "kind": kind,
            "status": "ACTIVE", "source_reference": source_reference,
            "fixed_salary_confirmed": kind == "PAID_VACATION" and vacation_pay_confirmed,
        }
        if kind == "PAID_VACATION" and not vacation_pay_confirmed:
            return {"error": "Ask the user to confirm that the fixed salary covers the vacation pay."}
        if kind == "SICKNESS":
            confirmations = (prior_illnesses_reviewed, sick_note_reviewed, fixed_salary_covers_sick_pay,
                             no_work_on_first_day)
            if not all(confirmations):
                return {"error": "Ask the user to confirm each sickness statement (prior illnesses, sick note, "
                                 "fixed salary, no work on the first day), or record it in the Norman app."}
            data["sickness"] = {
                "incapacity_start": (incapacity_start or start_date).isoformat(), "prior_used_days": prior_used_days,
                "history_reviewed": True, "entitlement_confirmed": True, "fixed_salary_confirmed": True,
                "first_day_full_absence_confirmed": True,
            }
        period = {"year": start_date.year, "month": start_date.month}
        review = await _get(ctx, f"gf-salaries/{person_id}/absences/", params=period)
        if _failed(review) or not isinstance(review, dict):
            return _failed(review) or as_object(review)
        result = await _post(ctx, f"gf-salaries/{person_id}/absences/", {
            "absence_id": str(uuid4()), "expected_revision": review.get("latestRevision", 0),
            "reviewed_employment": review.get("employmentFingerprint"),
            "reviewed_work_schedule_revision": review.get("workScheduleRevision", 0), **data,
        }, params=period)
        if _failed(result):
            return _failed(result)
        return {"recorded": True, "kind": kind, "startDate": start_date.isoformat(), "endDate": end_date.isoformat()}

    @mcp.tool(title="Update Employer Payroll Setup", annotations=WRITE)
    async def update_employer_payroll_setup(
        ctx: Context,
        employer_number: str | None = Field(default=None, description="Betriebsnummer of the employer (8 digits)"),
        employer_notice_date: date | None = Field(default=None, description="Date of the Betriebsnummer notice"),
        employer_notice_reference: str | None = Field(default=None, description="Reference of that notice"),
        uv_insurer_name: str | None = Field(default=None, description="Berufsgenossenschaft (accident insurance)"),
        uv_insurer_number: str | None = Field(default=None, description="Betriebsnummer of the Berufsgenossenschaft"),
        uv_company_number: str | None = Field(default=None, description="Unternehmensnummer at the Berufsgenossenschaft"),
        uv_notice_date: date | None = Field(default=None, description="Date of the membership notice"),
        uv_notice_reference: str | None = Field(default=None, description="Reference of that notice"),
        contact_first_name: str | None = Field(default=None, description="Payroll contact, first name"),
        contact_last_name: str | None = Field(default=None, description="Payroll contact, last name"),
        contact_email: str | None = Field(default=None, description="Payroll contact e-mail"),
        contact_phone: str | None = Field(default=None, description="Payroll contact phone"),
        umlage_scope: Literal["SICKNESS_AND_MATERNITY", "MATERNITY_ONLY"] | None = Field(
            default=None, description="U1 and U2 (up to 30 employees) or U2 only",
        ),
        u1_reimbursement_rate: Decimal | None = Field(
            default=None, ge=40, le=100, description="U1 reimbursement rate from the fund's Satzung, in %",
        ),
        u1_employer_contribution_treatment: Literal["INCLUDED", "FLAT_SURCHARGE", "EXCLUDED"] | None = Field(
            default=None, description="How the fund reimburses employer contributions on continued pay",
        ),
        aag_notice_reference: str | None = Field(default=None, description="Notice or Satzung the AAG terms come from"),
    ) -> dict[str, Any]:
        """Update the employer data payroll needs; omitted fields keep their value.

        Values come from the Federal Employment Agency's Betriebsnummer notice, the
        Berufsgenossenschaft's membership notice and the Krankenkasse's Satzung. Nothing is
        registered or sent anywhere.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        review = await _get(ctx, "employer-setup/")
        if _failed(review) or not isinstance(review, dict):
            return _failed(review) or as_object(review)
        current = review.get("current") or {}
        changes = {
            "employer_number": employer_number, "employer_notice_date": employer_notice_date,
            "employer_notice_reference": employer_notice_reference, "uv_insurer_name": uv_insurer_name,
            "uv_insurer_number": uv_insurer_number, "uv_company_number": uv_company_number,
            "uv_notice_date": uv_notice_date, "uv_notice_reference": uv_notice_reference,
            "contact_first_name": contact_first_name, "contact_last_name": contact_last_name,
            "contact_email": contact_email, "contact_phone": contact_phone, "umlage_scope": umlage_scope,
            "u1_reimbursement_rate": f"{u1_reimbursement_rate:.2f}" if u1_reimbursement_rate is not None else None,
            "u1_employer_contribution_treatment": u1_employer_contribution_treatment,
            "aag_notice_reference": aag_notice_reference,
        }
        data = {_snake(key): value for key, value in (current.get("data") or {}).items()}
        data.update({key: value.isoformat() if isinstance(value, date) else value
                     for key, value in changes.items() if value is not None})
        result = await _post(ctx, "employer-setup/", {
            "expected_revision": current.get("revision", 0),
            "reviewed_identity": review.get("identityFingerprint"),
            "data": data,
        })
        if _failed(result) or not isinstance(result, dict):
            return _failed(result) or as_object(result)
        return {"revision": (result.get("current") or {}).get("revision"), "dataComplete": result.get("dataComplete"),
                "issues": result.get("issues", [])}

    @mcp.tool(title="Save Contribution Plan", annotations=WRITE)
    async def save_contribution_plan(
        ctx: Context,
        year: int = Field(ge=2025, le=2026, description="Calendar year (2025 or 2026)"),
        month: int = Field(ge=1, le=12, description="Month 1-12"),
        first_month_confirmed: bool = Field(
            default=False,
            description="Required for the first plan in Norman: the user confirms balances from earlier "
                        "payroll software are not included",
        ),
    ) -> dict[str, Any]:
        """Save the Beitragsnachweis estimate of a month as shown by get_contribution_plan.

        Saving fixes the amounts the user reports to each Krankenkasse or the
        Minijob-Zentrale through the SV-Meldeportal; Norman sends nothing. Next month's
        plan carries the difference to the actual contributions.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        preview = await _get(ctx, "payroll-months/contribution-plan/", params={"year": year, "month": month})
        if _failed(preview) or not isinstance(preview, dict):
            return _failed(preview) or as_object(preview)
        if preview.get("status") != "PREVIEW":
            return {"error": "This month's plan is already saved.", "id": preview.get("id")}
        first = not (preview.get("snapshot") or {}).get("plans")
        if first and not first_month_confirmed:
            return {"error": "This is the first plan in Norman. Ask the user to confirm that balances from "
                             "earlier payroll software are not included, then call again with "
                             "first_month_confirmed=true."}
        result = await _post(ctx, "payroll-months/contribution-plan/", {
            "year": year, "month": month, "reviewed_fingerprint": preview.get("fingerprint"),
            "request_id": str(uuid4()), "starts_series": first,
        })
        if _failed(result) or not isinstance(result, dict):
            return _failed(result) or as_object(result)
        snapshot = result.get("snapshot") or {}
        return {key: value for key, value in result.items() if key != "snapshot"} | {"funds": snapshot.get("funds", [])}

    @mcp.tool(title="Prepare Wage Tax Return", annotations=WRITE)
    async def prepare_wage_tax_return(
        ctx: Context,
        year: int = Field(ge=2025, le=2100, description="Calendar year"),
        zeitraum: Literal["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12",
                          "41", "42", "43", "44", "19"] = Field(
            description="Filing period as ELSTER codes it: '01'-'12' a month, '41'-'44' a quarter, '19' the year. "
                        "It follows the company's filing frequency for wage tax.",
        ),
    ) -> dict[str, Any]:
        """Compute (or recompute) the draft Lohnsteuer-Anmeldung of a filing period.

        Every month of the period must be approved first. Nothing is transmitted; review
        it with get_wage_tax_return.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _post(ctx, "payroll-runs/compute/", {"year": year, "zeitraum": zeitraum})
        return _failed(result) or _run(as_object(result))

    # --- Binding steps: each needs the reviewed version and the user's explicit go-ahead ---

    @mcp.tool(title="Approve Payroll Month", annotations=DESTRUCTIVE_WRITE)
    async def approve_payroll_month(
        ctx: Context,
        year: int = Field(ge=2025, le=2100, description="Calendar year"),
        month: int = Field(ge=1, le=12, description="Month 1-12"),
        revision: int = Field(ge=1, description="`revision` from get_payroll_month that the user reviewed"),
        fingerprint: str = Field(
            pattern=r"^[a-f0-9]{64}$", description="`fingerprint` from get_payroll_month that the user reviewed",
        ),
    ) -> dict[str, Any]:
        """Approve a calculated payroll month: its version is frozen and booked to the ledger.

        Only after the user has seen the month's people and amounts (get_payroll_month,
        status CALCULATED, no issues) and explicitly asked to approve it. Afterwards the
        month changes only through a correction. Approving pays nothing and files nothing:
        payslips, the Lohnsteuer-Anmeldung and payments follow separately. A changed month
        is refused because its fingerprint no longer matches; show it again.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _post(ctx, "payroll-months/approve/", {
            "year": year, "month": month, "revision": revision, "reviewed_fingerprint": fingerprint,
        })
        return _month(result)

    @mcp.tool(title="Prepare Payroll Correction", annotations=WRITE)
    async def prepare_payroll_correction(
        ctx: Context,
        year: int = Field(ge=2025, le=2100, description="Calendar year of the approved month"),
        month: int = Field(ge=1, le=12, description="Month 1-12"),
        revision: int = Field(ge=1, description="`revision` of the approved month from get_payroll_month"),
        fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$", description="`fingerprint` from get_payroll_month"),
        reason: str = Field(min_length=1, max_length=500, description="Why the month is corrected"),
        changes: list[dict[str, Any]] = Field(
            min_length=1,
            description="Corrected monthly gross per person: [{\"person_id\": \"...\", \"monthly_gross\": \"4200.00\"}]",
        ),
    ) -> dict[str, Any]:
        """Prepare a correction of an approved month's gross salaries, as a draft.

        Returns the corrected month with `pendingCorrection` (its id and fingerprint) for
        the user to review. Nothing is booked until approve_payroll_correction; a prepared
        correction can be discarded with cancel_payroll_correction.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        rows = []
        for change in changes:
            person_id = change.get("person_id") or change.get("salary")
            try:
                gross = Decimal(str(change.get("monthly_gross")))
            except InvalidOperation:
                gross = Decimal(0)
            if not person_id or gross <= 0:
                return {"error": "Each change needs person_id and a positive monthly_gross."}
            rows.append({"salary": person_id, "monthly_gross": f"{gross:.2f}"})
        result = await _post(ctx, "payroll-months/prepare-correction/", {
            "year": year, "month": month, "revision": revision, "reviewed_fingerprint": fingerprint,
            "request_id": str(uuid4()), "reason": reason, "changes": rows,
        })
        return _month(result)

    @mcp.tool(title="Approve Payroll Correction", annotations=DESTRUCTIVE_WRITE)
    async def approve_payroll_correction(
        ctx: Context,
        correction_id: str = Field(description="id of the pending correction from prepare_payroll_correction"),
        fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$", description="Fingerprint of the reviewed correction"),
    ) -> dict[str, Any]:
        """Approve a prepared correction: the corrected version is booked as reversal plus new postings.

        Only after the user has reviewed the corrected amounts and explicitly asked to
        approve. A Lohnsteuer-Anmeldung already filed for the period must then be corrected
        too; the app shows that.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _post(ctx, "payroll-months/approve-correction/", {
            "correction_id": correction_id, "reviewed_fingerprint": fingerprint,
        })
        return _month(result)

    @mcp.tool(title="Cancel Payroll Correction", annotations=DESTRUCTIVE_WRITE)
    async def cancel_payroll_correction(
        ctx: Context,
        correction_id: str = Field(description="id of the pending correction to discard"),
    ) -> dict[str, Any]:
        """Discard a prepared, not yet approved correction. The approved month stays as it was."""
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        return _month(await _post(ctx, "payroll-months/cancel-correction/", {"correction_id": correction_id}))

    @mcp.tool(title="Test Wage Tax Return with ELSTER", annotations=WRITE)
    async def preview_wage_tax_return(
        ctx: Context,
        run_id: str = Field(description="publicId of the Lohnsteuer-Anmeldung, from list_wage_tax_returns"),
    ) -> dict[str, Any]:
        """Send the Lohnsteuer-Anmeldung to ELSTER as a test transmission; nothing is filed.

        ELSTER validates it like a real filing; a rejection comes back as an error with
        ELSTER's reason. On success `protocol` is a one-hour link to ELSTER's protocol PDF.
        Show the user the result before submit_wage_tax_return.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _post(ctx, f"payroll-runs/{run_id}/preview/", {}, params={"response_format": "download_url"})
        if _failed(result):
            return _failed(result)
        return {"accepted": True, "filed": False, "protocol": _link(result)}

    @mcp.tool(title="Submit Wage Tax Return", annotations=EXTERNAL_IRREVERSIBLE_WRITE)
    async def submit_wage_tax_return(
        ctx: Context,
        run_id: str = Field(description="publicId of the Lohnsteuer-Anmeldung, from list_wage_tax_returns"),
    ) -> dict[str, Any]:
        """File the Lohnsteuer-Anmeldung with the tax office through ELSTER. Binding.

        Only after the user has reviewed the return (get_wage_tax_return), its test
        transmission passed (preview_wage_tax_return) and the user explicitly asked to file
        it. Every month of the period must be approved. A 403 means filing is not available
        for this account. Payment of the wage tax is separate.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _post(ctx, f"payroll-runs/{run_id}/submit/", {}, params={"response_format": "download_url"})
        if isinstance(result, dict) and result.get("status_code") == 403:
            return {"error": "Filing is not available for this account right now; file it in the Norman app.",
                    "status_code": 403, "url": _app_url("payroll?view=reports")}
        if _failed(result):
            return _failed(result)
        # The status says what happened: FILED, or SUBMITTING while ELSTER has not confirmed yet.
        run = await _get(ctx, f"payroll-runs/{run_id}/")
        return {"protocol": _link(result), "status": run.get("status") if isinstance(run, dict) else None,
                "submittedAt": run.get("submittedAt") if isinstance(run, dict) else None}

    @mcp.tool(title="Mark Wage Tax Return Filed Elsewhere", annotations=DESTRUCTIVE_WRITE)
    async def mark_wage_tax_return_filed(
        ctx: Context,
        run_id: str = Field(description="publicId of the Lohnsteuer-Anmeldung, from list_wage_tax_returns"),
        filed_on: date = Field(description="Date it was filed outside Norman (YYYY-MM-DD)"),
    ) -> dict[str, Any]:
        """Record that this Lohnsteuer-Anmeldung was filed outside Norman, e.g. in Mein ELSTER.

        Only when the user says it was filed elsewhere; Norman then never files it again.
        """
        if not _api(ctx).company_id:
            return NO_COMPANY_ERROR
        result = await _post(ctx, f"payroll-runs/{run_id}/mark-filed/", {
            "confirmed": True, "filed_on": filed_on.isoformat(),
        })
        return _failed(result) or _run(as_object(result))
