"""Tools declared to return an object keep returning one.

FastMCP validates structured output against the return annotation, so a bare
list or string from the API failed with "Input should be a valid dictionary"
although the call had succeeded. These tests go through the production
server's tools/call handler, where that validation runs.
"""

import pytest

from tests.mcp_harness import FakeApi, call_tool, structured

TEMPLATES = [{"code": "skr03", "name": "SKR03"}, {"code": "skr04", "name": "SKR04"}]
MATCHES = [{"accountNumber": "4200", "nameDe": "Raumkosten", "nameEn": "Occupancy costs"}]


def _sme_api(answer):  # noqa: ANN001, ANN202
    """An SME company whose lookup endpoints answer with ``answer``."""

    def respond(_method, url, _kwargs):  # noqa: ANN001, ANN202
        if url.endswith("/api/v1/companies/company-1/"):
            return {"isSme": True}
        return answer

    return FakeApi(respond)


@pytest.mark.parametrize("tool", ["list_coa_templates", "list_chart_of_accounts_templates"])
def test_template_lists_come_back_as_results(tool):  # noqa: ANN001
    data = structured(call_tool(tool, {}, FakeApi(TEMPLATES)))

    assert data == {"results": TEMPLATES}


def test_skr_lookup_comes_back_as_results():
    data = structured(call_tool("search_skr_by_code", {"code": "42"}, _sme_api(MATCHES)))

    assert data == {"results": MATCHES}


def test_skr_ai_suggestion_comes_back_as_results():
    data = structured(call_tool("suggest_skr_category", {"query": "office rent"}, _sme_api(MATCHES)))

    assert data == {"results": MATCHES}


def test_skr_ai_suggestion_without_matches_keeps_its_hint():
    data = structured(call_tool("suggest_skr_category", {"query": "xyz"}, _sme_api([])))

    assert data["results"] == []
    assert "No matching categories found" in data["message"]


def test_valid_tax_number():
    data = structured(
        call_tool("validate_tax_number", {"tax_number": "30/441/24107", "region_code": "BE"}, FakeApi("Tax number is valid"))
    )

    assert data == {"valid": True, "message": "Tax number is valid"}


@pytest.mark.parametrize(
    "detail",
    ["Tax number is not valid", ["Tax number is not valid"], {"tax_number": ["Tax number is not valid"]}],
)
def test_invalid_tax_number_is_a_result_not_an_error(detail):  # noqa: ANN001
    api = FakeApi({"error": "Request failed: 400 Client Error", "status_code": 400, "detail": detail})

    data = structured(call_tool("validate_tax_number", {"tax_number": "1", "region_code": "BE"}, api))

    assert data == {"valid": False, "message": "Tax number is not valid"}


def test_other_failures_pass_through_unchanged():
    api = FakeApi({"error": "Connection error. Please check your network connection."})

    data = structured(call_tool("validate_tax_number", {"tax_number": "1", "region_code": "BE"}, api))

    assert data == {"error": "Connection error. Please check your network connection."}
