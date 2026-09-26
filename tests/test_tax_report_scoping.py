"""Tax report tools act on the selected company.

The unscoped api/v1/taxes/reports/ route ignores X-Company-Id and answers for
the user's first company (ReportsViewSet._get_company). After switch_company,
or for anyone whose selected company is not their first, the tools listed,
previewed and submitted another company's reports. The company-scoped route
is the same viewset.
"""

import pytest

from tests.mcp_harness import FakeApi, call_tool, read_resource, structured

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


def test_preview_uses_the_company_scoped_route():
    api = FakeApi({"downloadUrl": "https://api.norman.finance/api/v1/dl/preview/", "mimeType": "image/jpeg"})

    call_tool("generate_finanzamt_preview", {"report_id": "report-1"}, api)

    assert api.requests[0][0] == "POST"
    assert api.requests[0][1].endswith(SCOPED + "report-1/generate-preview-url/")


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
    api = FakeApi({}, company_id=None)

    data = structured(call_tool("list_tax_reports", {}, api))

    assert data == {"error": "No company available. Please authenticate first."}
    assert api.requests == []


def test_taxes_resource_uses_the_company_scoped_route():
    api = FakeApi({"results": []})

    read_resource("taxes://list/1/50", api)

    assert api.requests[-1][1].endswith(SCOPED)


@pytest.mark.parametrize("tool", ["get_client_overview", "get_tax_compliance_status"])
def test_advisor_tools_read_the_client_companys_reports(tool):  # noqa: ANN001
    api = FakeApi({"results": []})

    call_tool(tool, {"company_id": "client-co"}, api)

    report_calls = [url for _method, url, _kwargs in api.requests if "/taxes/reports/" in url]
    assert report_calls
    assert all(url.endswith("/api/v1/companies/client-co/taxes/reports/") for url in report_calls)
