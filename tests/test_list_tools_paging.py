"""List tools page the way the API pages.

The API paginates by page/page_size (default 20) and ignores "limit", so the
tools that sent limit -- or nothing -- never returned more than 20 rows and had
no way to ask for the next page.
"""

from tests.mcp_harness import FakeApi, call_tool, structured

PAGE = {"count": 0, "next": None, "results": []}


def _params(tool, arguments):  # noqa: ANN001, ANN202
    api = FakeApi(PAGE)
    structured(call_tool(tool, arguments, api))
    return api.requests[-1][2]["params"]


def test_search_transactions_pages_and_keeps_a_zero_minimum():
    assert _params("search_transactions", {}) == {"page_size": 20, "page": 1}
    assert _params("search_transactions", {"limit": 50, "page": 3, "min_amount": 0}) == {
        "minAmount": 0,
        "page_size": 50,
        "page": 3,
    }


def test_list_invoices_pages():
    assert _params("list_invoices", {}) == {"page_size": 100, "page": 1}
    assert _params("list_invoices", {"limit": 25, "page": 2})["page_size"] == 25


def test_list_offers_pages():
    params = _params("list_offers", {"page": 2})
    assert params == {"type": "quote", "page_size": 100, "page": 2}


def test_list_attachments_pages_filters_and_can_skip_download_links():
    api = FakeApi({"results": [{"publicId": "a-1", "file": "https://files/a.pdf"}]})

    structured(
        call_tool(
            "list_attachments",
            {
                "search": "Meta",
                "date_from": "2026-01-01",
                "date_to": "2026-01-31",
                "page": 2,
                "page_size": 10,
                "include_download_urls": False,
            },
            api,
        ),
    )

    assert len(api.requests) == 1
    assert api.requests[0][2]["params"] == {
        "page": 2,
        "page_size": 10,
        "date_from": "2026-01-01",
        "date_to": "2026-01-31",
        "search": "Meta",
    }


def test_list_attachments_linked_means_what_it_says():
    # The API's `linked` filter is inverted: linked=true returns UNlinked documents.
    assert _params("list_attachments", {"linked": True, "include_download_urls": False})["linked"] is False
    assert _params("list_attachments", {"linked": False, "include_download_urls": False})["linked"] is True


def test_list_attachments_adds_download_links_concurrently():
    rows = [{"publicId": f"a-{index}", "file": f"https://files/{index}.pdf"} for index in range(12)]

    def respond(_method, url, _kwargs):  # noqa: ANN001, ANN202
        if url.endswith("/download/"):
            return {"url": f"https://dl/{url.split('/')[-3]}"}
        return {"results": [dict(row) for row in rows]}

    data = structured(call_tool("list_attachments", {}, FakeApi(respond)))

    assert [row["downloadUrl"] for row in data["results"]] == [f"https://dl/a-{index}" for index in range(12)]


def test_list_tax_reports_filters_and_pages():
    api = FakeApi(PAGE)

    structured(
        call_tool(
            "list_tax_reports",
            {"date_from": "2026-01-01", "date_to": "2026-03-31", "report_type": "ADVANCED_SALEX_TAX", "status": "NOT_COMPLETED", "page": 2},
            api,
        ),
    )

    _method, url, kwargs = api.requests[-1]
    assert url.endswith("/api/v1/companies/company-1/taxes/reports/")
    assert kwargs["params"] == {
        "page": 2,
        "date_from": "2026-01-01",
        "date_to": "2026-03-31",
        "type": "ADVANCED_SALEX_TAX",
        "status": "NOT_COMPLETED",
    }
