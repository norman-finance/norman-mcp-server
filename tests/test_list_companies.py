"""list_companies gives every user the ids that switch_company needs.

Until now only list_tax_advisor_clients listed companies, and it answers 403 for
anyone who is not a tax advisor: an owner of several companies had no way to
find the id of the other one.
"""

from norman_mcp.tools import company as company_tools
from tests.mcp_harness import FakeApi, call_tool, structured

GMBH = {
    "publicId": "co-gmbh",
    "name": "Musterfirma GmbH",
    "accountType": "GmbH",
    "country": "DE",
    "isSme": True,
    "isArchived": False,
    "iban": "DE89370400440532013000",
    "taxNumber": "30/441/24107",
    "members": [{"email": "owner@example.com"}],
}
UG = {**GMBH, "publicId": "co-ug", "name": "Musterfirma UG", "accountType": "UG"}


def pages(*pages):  # noqa: ANN001, ANN002, ANN201
    """Answer GET /companies/?page=N with the N-th page, the way DRF paginates."""
    total = sum(len(page) for page in pages)

    def respond(method, url, kwargs):  # noqa: ANN001, ANN202
        assert method == "GET" and url.endswith("/api/v1/companies/"), url
        number = kwargs["params"]["page"]
        return {
            "count": total,
            "next": f"https://api.example/api/v1/companies/?page={number + 1}" if number < len(pages) else None,
            "previous": None,
            "results": pages[number - 1],
        }

    return respond


def test_lists_every_page_and_marks_the_active_company():
    data = structured(call_tool("list_companies", {}, FakeApi(pages([GMBH], [UG]), company_id="co-ug")))

    assert data["count"] == 2
    assert data["activeCompanyId"] == "co-ug"
    assert [(item["id"], item["active"]) for item in data["companies"]] == [("co-gmbh", False), ("co-ug", True)]
    assert "note" not in data


def test_leaves_out_bank_and_tax_identifiers():
    data = structured(call_tool("list_companies", {}, FakeApi(pages([GMBH]))))

    assert data["companies"] == [
        {
            "id": "co-gmbh",
            "name": "Musterfirma GmbH",
            "legalForm": "GmbH",
            "country": "DE",
            "isSme": True,
            "isArchived": False,
            "active": False,
        }
    ]


def test_archived_companies_only_on_request():
    api = FakeApi(pages([GMBH]))

    call_tool("list_companies", {}, api)
    call_tool("list_companies", {"include_archived": True}, api)

    default, archived = (kwargs["params"] for _method, _url, kwargs in api.requests)
    assert "includeArchived" not in default
    assert archived["includeArchived"] == "true"


def test_api_error_is_passed_on():
    api = FakeApi({"error": "Request failed: 401 Client Error", "status_code": 401})

    data = structured(call_tool("list_companies", {}, api))

    assert data["error"] == "Request failed: 401 Client Error"


def test_says_so_when_it_stops_at_the_page_limit(monkeypatch):  # noqa: ANN001
    monkeypatch.setattr(company_tools, "COMPANIES_MAX_PAGES", 1)

    data = structured(call_tool("list_companies", {}, FakeApi(pages([GMBH], [UG]))))

    assert data["count"] == 2
    assert [item["id"] for item in data["companies"]] == ["co-gmbh"]
    assert "list_tax_advisor_clients" in data["note"]
