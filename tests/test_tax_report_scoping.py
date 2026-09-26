"""Tax report tools act on the selected company.

The unscoped api/v1/taxes/reports/ route ignores X-Company-Id and answers for
the user's oldest company. After switch_company -- or for anyone whose last
active company is not their first -- the tools listed, previewed and submitted
another company's reports. The company-scoped route is the same viewset.
"""

import pytest

from tests.mcp_harness import FakeApi, call_tool, error_payload, read_resource, structured

SCOPED = "/api/v1/companies/company-1/taxes/reports/"


@pytest.mark.parametrize(
    ("tool", "arguments", "method", "suffix"),
    [
        ("list_tax_reports", {}, "GET", ""),
        ("get_tax_report", {"report_id": "report-1"}, "GET", "report-1/"),
        ("submit_tax_report", {"report_id": "report-1"}, "POST", "report-1/submit-report/"),
    ],
)
def test_report_tools_use_the_company_scoped_route(tool, arguments, method, suffix):  # noqa: ANN001
    api = FakeApi({"pk": "report-1", "status": "NOT_COMPLETED"})

    structured(call_tool(tool, arguments, api))

    assert api.requests[0][0] == method
    assert api.requests[0][1].endswith(SCOPED + suffix)


def test_a_filed_report_links_its_pdf_through_the_scoped_route():
    def respond(_method, url, _kwargs):  # noqa: ANN001, ANN202
        if url.endswith("/download/"):
            return {"url": "https://api.norman.finance/api/v1/dl/token/"}
        return {"pk": "report-1", "status": "SUBMIT", "reportFile": "reports/r.pdf"}

    api = FakeApi(respond)
    data = structured(call_tool("get_tax_report", {"report_id": "report-1"}, api))

    assert data["downloadUrl"] == "https://api.norman.finance/api/v1/dl/token/"
    assert api.requests[-1][1].endswith(SCOPED + "report-1/download/")


def test_report_tools_need_a_company():
    result = call_tool("list_tax_reports", {}, FakeApi({}, company_id=None))

    assert error_payload(result) == {"error": "No company available. Please authenticate first."}


def test_taxes_resource_uses_the_company_scoped_route():
    api = FakeApi({"results": []})

    read_resource("taxes://list/1/50", api)

    assert api.requests[-1][1].endswith(SCOPED)


def _advisor_api(reports, invoices=None):  # noqa: ANN001, ANN202
    def respond(_method, url, _kwargs):  # noqa: ANN001, ANN202
        if "/taxes/reports/" in url:
            return {"results": reports}
        if url.endswith("/invoices/"):
            return {"results": invoices or []}
        if url.endswith("/companies/client-co/"):
            return {"name": "Client GmbH", "taxNumber": "020/239/03333", "vatNumber": "DE1"}
        return {}

    return FakeApi(respond)


REPORTS = [
    {"pk": "r-1", "type": "ADVANCED_SALEX_TAX", "status": "NOT_COMPLETED", "dateFrom": "2026-08-01", "dateTo": "2026-08-31", "dateDue": "2026-09-10", "total": "120.00"},
    {"pk": "r-2", "type": "ADVANCED_SALEX_TAX", "status": "REQUIRE_CORRECTION", "dateFrom": "2026-07-01", "dateTo": "2026-07-31", "dateDue": "2026-08-10", "total": "80.00"},
    {"pk": "r-3", "type": "ADVANCED_SALEX_TAX", "status": "SUBMIT", "dateFrom": "2026-06-01", "dateTo": "2026-06-30", "dateDue": "2026-07-10", "total": "50.00"},
    {"pk": "r-4", "type": "ADVANCED_SALEX_TAX", "status": "SUBMIT_AND_PAID", "dateFrom": "2026-05-01", "dateTo": "2026-05-31", "dateDue": "2026-06-10", "total": "40.00"},
]


def test_compliance_counts_the_statuses_the_api_sends():
    api = _advisor_api(REPORTS)

    data = structured(call_tool("get_tax_compliance_status", {"company_id": "client-co"}, api))

    assert data["reports"]["unfiled"] == 2
    assert data["reports"]["filed"] == 2
    assert data["reports"]["unfiledReports"][0] == {
        "id": "r-1",
        "type": "ADVANCED_SALEX_TAX",
        "dateFrom": "2026-08-01",
        "dateTo": "2026-08-31",
        "status": "NOT_COMPLETED",
        "dueDate": "2026-09-10",
        "amount": "120.00",
    }
    assert "2 tax report(s) are unfiled and need attention" in data["actionItems"]
    reports_request = next(request for request in api.requests if "/taxes/reports/" in request[1])
    assert reports_request[1].endswith("/api/v1/companies/client-co/taxes/reports/")
    assert reports_request[2]["params"] == {"page_size": 200}


def test_client_overview_counts_reports_and_sums_invoice_totals():
    api = _advisor_api(REPORTS, invoices=[{"fullCost": "100.50"}, {"fullCost": "49.50"}])

    data = structured(call_tool("get_client_overview", {"company_id": "client-co"}, api))

    assert data["taxReports"]["pending"] == 2
    assert data["taxReports"]["submitted"] == 2
    assert [row["id"] for row in data["taxReports"]["pendingReports"]] == ["r-1", "r-2"]
    assert data["outstandingInvoices"] == {"count": 2, "totalAmount": 150.0}
