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


def test_annotations_are_truthful():
    server = MCPServer()
    register_payroll_tools(server)
    tools = server._tool_manager._tools  # noqa: SLF001
    writes = {"calculate_payroll_month"}
    for name, tool in tools.items():
        hints = (tool.annotations.read_only_hint, tool.annotations.open_world_hint, tool.annotations.destructive_hint)
        assert hints == ((False, False, False) if name in writes else (True, False, False)), name
        assert tool.title, name
