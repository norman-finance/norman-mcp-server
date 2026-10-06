"""Payroll tools: company-scoped reads, withheld identifiers and truthful annotations."""

from mcp.server.mcpserver import MCPServer

from norman_mcp.tools.payroll import register_payroll_tools
from tests.mcp_harness import FakeApi, call_tool, structured

BASE = "/api/v1/companies/company-1/payroll/"

PERSON = {
    "publicId": "person-1", "directorName": "Sara Mini", "employmentKind": "EMPLOYEE",
    "firstName": "Sara", "lastName": "Mini", "taxIdNr": "12345678904", "dateOfBirth": "2003-09-03",
    "gender": "W", "street": "Ahornweg", "houseNumber": "7", "postalCode": "10115", "city": "Berlin",
    "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "accountHolder": "Sara Mini",
    "monthlyGross": "538.00", "insuranceProfile": "MINIJOB", "isActive": True,
}
LINE = {
    "salary": "person-1", "director": "Sara Mini", "gross": "538.00", "lohnsteuer": "0.00",
    "soli": "0.00", "kirchensteuer": "0.00", "svEmployee": "19.37", "svEmployer": "167.69",
    "kvZuschuss": "0.00", "pvZuschuss": "0.00",
    "socialInsurance": {"fundNumber": "98000006", "beitragsgruppe": "6100", "note": "AOK letter",
                        "unpaidCalendarDates": ["2026-12-15"]},
    "snapshot": {
        "person": {"taxIdNr": "12345678904", "street": "Ahornweg"},
        "absences": {"records": [{"kind": "SICKNESS", "days": [{"date": "2026-12-15"}]}]},
        "employment": {"start": "2026-12-01", "end": "2026-12-31", "calendarDays": 31},
        "contractualGross": "538.00",
    },
}


def respond(routes):
    """Answer each request by the first route whose path the URL ends with."""

    def answer(method, url, kwargs):  # noqa: ANN001, ANN202
        for (route_method, path), body in routes.items():
            if method == route_method and url.split("?")[0].endswith(path):
                return body(kwargs) if callable(body) else body
        raise AssertionError(f"unexpected {method} {url}")

    return answer


def test_people_withhold_identifiers_address_and_bank_details():
    inactive = {**PERSON, "publicId": "person-2", "isActive": False}
    api = FakeApi(respond({("GET", BASE + "gf-salaries/"): {"count": 2, "results": [PERSON, inactive]}}))
    result = structured(call_tool("list_payroll_people", {}, api))
    assert [person["publicId"] for person in result["results"]] == ["person-1"]
    person = result["results"][0]
    for field in ("taxIdNr", "dateOfBirth", "gender", "street", "houseNumber", "postalCode", "city",
                  "iban", "bic", "accountHolder"):
        assert field not in person
    assert person["bankAccount"] == "…2051"
    assert person["monthlyGross"] == "538.00"
    assert api.requests[0][2]["params"] == {"pageSize": 1000}


def test_a_person_brings_social_insurance_profiles_without_evidence_notes():
    profile = {"publicId": "profile-1", "fundNumber": "98000006", "minijobHealthInsured": True, "note": "AOK letter"}
    api = FakeApi(respond({
        ("GET", BASE + "gf-salaries/person-1/"): PERSON,
        ("GET", BASE + "gf-salaries/person-1/social-insurance-profiles/"): [profile],
    }))
    result = structured(call_tool("get_payroll_person", {"person_id": "person-1"}, api))
    assert "taxIdNr" not in result
    assert result["socialInsuranceProfiles"] == [{"publicId": "profile-1", "fundNumber": "98000006",
                                                  "minijobHealthInsured": True}]


def test_month_lines_drop_the_snapshot_and_absence_dates_and_derive_the_payout():
    review = {"year": 2026, "month": 12, "status": "APPROVED", "revision": 1, "fingerprint": "f",
              "lines": [LINE], "totals": {"payout": "518.63"}, "issues": []}
    api = FakeApi(respond({("GET", BASE + "payroll-months/inspect/"): review}))
    result = structured(call_tool("get_payroll_month", {"year": 2026, "month": 12}, api))
    line = result["lines"][0]
    assert "snapshot" not in line
    assert line["employment"] == {"start": "2026-12-01", "end": "2026-12-31", "calendarDays": 31}
    assert line["socialInsurance"] == {"fundNumber": "98000006", "beitragsgruppe": "6100"}
    assert (line["taxes"], line["payout"]) == ("0.00", "518.63")
    assert "12345678904" not in str(result) and "SICKNESS" not in str(result)
    assert api.requests[0][2]["params"] == {"year": 2026, "month": 12}


def test_calculating_posts_the_period_and_returns_the_review():
    api = FakeApi(respond({("POST", BASE + "payroll-months/calculate/"): {"status": "CALCULATED", "lines": [LINE]}}))
    result = structured(call_tool("calculate_payroll_month", {"year": 2026, "month": 12}, api))
    assert result["status"] == "CALCULATED"
    assert api.requests[0][2]["json_data"] == {"year": 2026, "month": 12}
    assert "snapshot" not in result["lines"][0]


def test_payments_mask_employee_ibans_but_keep_the_collecting_bodies():
    transfers = {
        "payouts": [{"salaryId": "person-1", "name": "Sara Mini", "iban": "DE02120300000000202051", "bic": "X",
                     "payable": "518.63"}],
        "funds": {"items": [{"fundNumber": "98000006", "iban": "DE86180400000156606600", "payable": "180.80"}]},
        "wageTax": {"due": "0.00"},
    }
    api = FakeApi(respond({("GET", BASE + "payroll-months/transfers/"): transfers}))
    result = structured(call_tool("get_payroll_payments", {"year": 2026, "month": 12}, api))
    assert result["payouts"] == [{"salaryId": "person-1", "name": "Sara Mini", "payable": "518.63",
                                  "bankAccount": "…2051"}]
    assert result["funds"]["items"][0]["iban"] == "DE86180400000156606600"


def test_aag_keeps_day_counts_but_not_the_dates():
    claim = {"u1": {"rows": [{"director": "Sara Mini", "coveredCalendarDays": 5,
                              "coveredCalendarDates": ["2026-12-15"], "reason": "MINIJOB_ZENTRALE"}]},
             "u2": {"rows": [{"employmentBanCalendarDays": 3, "employmentBanCalendarDates": ["2026-12-01"]}]}}
    api = FakeApi(respond({("GET", BASE + "payroll-months/aag-claim/"): claim}))
    result = structured(call_tool("get_aag_claim", {"year": 2026, "month": 12}, api))
    assert result["u1"]["rows"][0] == {"director": "Sara Mini", "coveredCalendarDays": 5, "reason": "MINIJOB_ZENTRALE"}
    assert result["u2"]["rows"][0] == {"employmentBanCalendarDays": 3}


def test_wage_tax_returns_filter_by_year_and_drop_the_lines():
    runs = {"count": 2, "results": [{"publicId": "run-1", "year": 2026, "zeitraum": "12", "lines": [LINE]},
                                    {"publicId": "run-0", "year": 2025, "zeitraum": "12", "lines": []}]}
    api = FakeApi(respond({("GET", BASE + "payroll-runs/"): runs}))
    result = structured(call_tool("list_wage_tax_returns", {"year": 2026}, api))
    assert result == {"count": 1, "results": [{"publicId": "run-1", "year": 2026, "zeitraum": "12"}]}


def test_documents_are_one_hour_links_and_never_raw_bytes():
    link = {"downloadUrl": "https://api.example/api/v1/dl/token/", "fileName": "a.pdf", "expiresInSeconds": 3600}
    api = FakeApi(respond({("GET", BASE + "gf-salaries/person-1/payslip/"): link}))
    result = structured(call_tool("get_payslip", {"person_id": "person-1", "year": 2026, "month": 12}, api))
    assert result == link
    assert api.requests[0][2]["params"] == {"year": 2026, "month": 12, "response_format": "download_url"}
    # An API that streams the PDF instead answers {"success": true} through the client.
    old = FakeApi(respond({("GET", BASE + "gf-salaries/person-1/lohnkonto/"): {"success": True}}))
    result = structured(call_tool("get_lohnkonto", {"person_id": "person-1", "year": 2026}, old))
    assert "could not be linked" in result["error"]


def test_a_company_without_max_learns_why():
    api = FakeApi({"error": "Access forbidden. Check your account permissions.", "status_code": 403})
    result = structured(call_tool("get_payroll_overview", {}, api))
    assert result["error"].startswith("Payroll is available on the Max plan")
    assert result["url"].endswith("/payroll")


def test_no_company_means_no_request():
    api = FakeApi({}, company_id=None)
    result = structured(call_tool("get_payroll_month", {"year": 2026, "month": 12}, api))
    assert result == {"error": "No company available. Please authenticate first."}
    assert api.requests == []


WRITES = {
    "calculate_payroll_month", "record_salary_change", "record_tax_profile_change", "set_employment_end",
    "record_statutory_insurance", "record_minijob_details", "record_work_schedule", "record_absence",
    "update_employer_payroll_setup", "save_contribution_plan", "prepare_wage_tax_return",
    "prepare_payroll_correction", "preview_wage_tax_return",
}
BINDING = {"approve_payroll_month", "approve_payroll_correction", "cancel_payroll_correction",
           "mark_wage_tax_return_filed"}


def test_annotations_are_truthful():
    server = MCPServer()
    register_payroll_tools(server)
    tools = server._tool_manager._tools  # noqa: SLF001
    for name, tool in tools.items():
        hints = (tool.annotations.read_only_hint, tool.annotations.open_world_hint, tool.annotations.destructive_hint)
        if name == "submit_wage_tax_return":
            expected = (False, True, True)
        elif name in BINDING:
            expected = (False, False, True)
        elif name in WRITES:
            expected = (False, False, False)
        else:
            expected = (True, False, False)
        assert hints == expected, name
        assert tool.title, name
    assert len(tools) == 31


def test_sickness_needs_every_confirmation_before_anything_is_sent():
    api = FakeApi(respond({}))
    result = structured(call_tool("record_absence", {
        "person_id": "person-1", "kind": "SICKNESS", "start_date": "2026-12-15", "end_date": "2026-12-19",
        "source_reference": "AU certificate of 15.12.", "prior_illnesses_reviewed": True,
    }, api))
    assert "confirm each sickness statement" in result["error"]
    assert api.requests == []


def test_a_confirmed_sickness_is_sent_against_the_reviewed_versions():
    review = {"latestRevision": 4, "employmentFingerprint": "e" * 64, "workScheduleRevision": 2}
    api = FakeApi(respond({
        ("GET", BASE + "gf-salaries/person-1/absences/"): review,
        ("POST", BASE + "gf-salaries/person-1/absences/"): review,
    }))
    result = structured(call_tool("record_absence", {
        "person_id": "person-1", "kind": "SICKNESS", "start_date": "2026-12-15", "end_date": "2026-12-19",
        "source_reference": "AU certificate of 15.12.", "prior_illnesses_reviewed": True,
        "sick_note_reviewed": True, "fixed_salary_covers_sick_pay": True, "no_work_on_first_day": True,
    }, api))
    assert result == {"recorded": True, "kind": "SICKNESS", "startDate": "2026-12-15", "endDate": "2026-12-19"}
    method, _, kwargs = api.requests[1]
    body = kwargs["json_data"]
    assert method == "POST" and kwargs["params"] == {"year": 2026, "month": 12}
    assert (body["expected_revision"], body["reviewed_employment"], body["reviewed_work_schedule_revision"]) == (
        4, "e" * 64, 2)
    assert body["sickness"] == {"incapacity_start": "2026-12-15", "prior_used_days": 0, "history_reviewed": True,
                                "entitlement_confirmed": True, "fixed_salary_confirmed": True,
                                "first_day_full_absence_confirmed": True}
    assert body["fixed_salary_confirmed"] is False and len(body["absence_id"]) == 36


def test_vacation_needs_the_pay_confirmation():
    api = FakeApi(respond({}))
    result = structured(call_tool("record_absence", {
        "person_id": "person-1", "kind": "PAID_VACATION", "start_date": "2026-12-21", "end_date": "2026-12-23",
        "source_reference": "Vacation request",
    }, api))
    assert "vacation pay" in result["error"] and api.requests == []


def test_the_first_contribution_plan_needs_an_explicit_confirmation():
    preview = {"status": "PREVIEW", "fingerprint": "f" * 64, "snapshot": {"plans": [], "funds": []}}
    saved = {"status": "SAVED", "id": "plan-1", "snapshot": {"plans": [], "funds": [{"fundNumber": "98000006"}]}}
    api = FakeApi(respond({
        ("GET", BASE + "payroll-months/contribution-plan/"): preview,
        ("POST", BASE + "payroll-months/contribution-plan/"): saved,
    }))
    refused = structured(call_tool("save_contribution_plan", {"year": 2026, "month": 12}, api))
    assert "first plan in Norman" in refused["error"] and len(api.requests) == 1
    result = structured(call_tool("save_contribution_plan", {"year": 2026, "month": 12,
                                                              "first_month_confirmed": True}, api))
    assert result == {"status": "SAVED", "id": "plan-1", "funds": [{"fundNumber": "98000006"}]}
    body = api.requests[-1][2]["json_data"]
    assert (body["reviewed_fingerprint"], body["starts_series"]) == ("f" * 64, True)


def test_employer_setup_keeps_omitted_fields_and_sends_the_reviewed_identity():
    review = {"current": {"revision": 2, "data": {"employerNumber": "12345671", "u1ReimbursementRate": "70.00",
                                                  "contactEmail": "a@b.de"}},
              "identityFingerprint": "i" * 64}
    api = FakeApi(respond({
        ("GET", BASE + "employer-setup/"): review,
        ("POST", BASE + "employer-setup/"): {"current": {"revision": 3}, "dataComplete": True, "issues": []},
    }))
    result = structured(call_tool("update_employer_payroll_setup", {"u1_reimbursement_rate": 80}, api))
    assert result == {"revision": 3, "dataComplete": True, "issues": []}
    body = api.requests[-1][2]["json_data"]
    assert (body["expected_revision"], body["reviewed_identity"]) == (2, "i" * 64)
    assert body["data"] == {"employer_number": "12345671", "u1_reimbursement_rate": "80.00", "contact_email": "a@b.de"}


def test_approval_and_corrections_carry_the_reviewed_version():
    approved = {"status": "APPROVED", "lines": [LINE],
                "pendingCorrection": {"id": "c-1", "fingerprint": "c" * 64, "lines": [LINE]}}
    api = FakeApi(respond({
        ("POST", BASE + "payroll-months/approve/"): approved,
        ("POST", BASE + "payroll-months/prepare-correction/"): {"id": "c-1", "lines": [LINE], "changes": []},
    }))
    result = structured(call_tool("approve_payroll_month", {"year": 2026, "month": 12, "revision": 1,
                                                             "fingerprint": "a" * 64}, api))
    assert "snapshot" not in result["lines"][0] and "snapshot" not in result["pendingCorrection"]["lines"][0]
    assert api.requests[0][2]["json_data"] == {"year": 2026, "month": 12, "revision": 1,
                                               "reviewed_fingerprint": "a" * 64}
    structured(call_tool("prepare_payroll_correction", {
        "year": 2026, "month": 12, "revision": 1, "fingerprint": "a" * 64, "reason": "Raise was late",
        "changes": [{"person_id": "person-1", "monthly_gross": 560}],
    }, api))
    body = api.requests[1][2]["json_data"]
    assert body["changes"] == [{"salary": "person-1", "monthly_gross": "560.00"}] and body["reason"] == "Raise was late"


def test_a_refused_filing_points_to_the_app():
    api = FakeApi({"error": "Access forbidden. Check your account permissions.", "status_code": 403})
    result = structured(call_tool("submit_wage_tax_return", {"run_id": "run-1"}, api))
    assert result["error"].startswith("Filing is not available") and result["status_code"] == 403


def test_the_employment_end_is_read_back_after_the_patch():
    stored = {**PERSON, "employmentEnd": "2027-06-30"}
    api = FakeApi(respond({
        ("PATCH", BASE + "gf-salaries/person-1/"): {"directorName": "", "employmentEnd": None},
        ("GET", BASE + "gf-salaries/person-1/"): stored,
    }))
    result = structured(call_tool("set_employment_end", {"person_id": "person-1", "employment_end": "2027-06-30"}, api))
    assert (result["directorName"], result["employmentEnd"]) == ("Sara Mini", "2027-06-30")
    assert api.requests[0][2]["json_data"] == {"employment_end": "2027-06-30"} and "taxIdNr" not in result


def test_filing_returns_the_protocol_link_and_the_resulting_status():
    link = {"downloadUrl": "https://api.example/api/v1/dl/t/", "fileName": "lsta-protokoll-2026-12.pdf",
            "mimeType": "application/pdf", "expiresInSeconds": 3600}
    api = FakeApi(respond({
        ("POST", BASE + "payroll-runs/run-1/preview/"): link,
        ("POST", BASE + "payroll-runs/run-1/submit/"): link,
        ("GET", BASE + "payroll-runs/run-1/"): {"status": "FILED", "submittedAt": "2027-01-08T10:00:00", "lines": []},
    }))
    test = structured(call_tool("preview_wage_tax_return", {"run_id": "run-1"}, api))
    assert test == {"accepted": True, "filed": False, "protocol": {
        "downloadUrl": link["downloadUrl"], "fileName": link["fileName"], "expiresInSeconds": 3600}}
    assert api.requests[0][2]["params"] == {"response_format": "download_url"}
    filed = structured(call_tool("submit_wage_tax_return", {"run_id": "run-1"}, api))
    assert (filed["status"], filed["submittedAt"], filed["protocol"]["fileName"]) == (
        "FILED", "2027-01-08T10:00:00", "lsta-protokoll-2026-12.pdf")

