"""Personal identifiers stay in Norman, while company bookkeeping fields remain usable."""

from copy import deepcopy

import pytest

from tests.mcp_harness import FakeApi, call_tool, read_resource, structured


COMPANY = {
    "publicId": "company-1",
    "name": "Sample business",
    "pesel": "synthetic-personal-id",
    "taxNumber": "business-tax-number",
    "taxId": "business-tax-id",
    "vatNumber": "business-vat-number",
    "iban": "business-iban",
    "currency": "PLN",
    "country": "PL",
    "members": [{"publicId": "member-1", "PESEL": "synthetic-member-id"}],
}


@pytest.mark.parametrize(
    "tool, arguments, method",
    [
        ("get_company_details", {}, "GET"),
        ("update_company_details", {}, "GET"),
        ("update_company_details", {"name": "New name", "tax_id": "business-tax-number"}, "PATCH"),
    ],
)
def test_company_responses_withhold_personal_ids_without_changing_business_fields_or_writes(tool, arguments, method):
    stored = deepcopy(COMPANY)
    api = FakeApi(stored)
    result = structured(call_tool(tool, arguments, api))
    company = result["company"] if "company" in result else result

    assert company == {
        **{key: value for key, value in COMPANY.items() if key not in {"pesel", "members"}},
        "members": [{"publicId": "member-1"}],
    }
    assert stored == COMPANY
    assert len(api.requests) == 1
    assert api.requests[0][0] == method
    if method == "PATCH":
        assert api.requests[0][2]["json_data"] == {"name": "New name", "taxNumber": "business-tax-number"}


def test_company_resource_does_not_disclose_personal_id_even_in_upstream_error_object():
    data = read_resource("company://current", FakeApi({**COMPANY, "error": "unavailable"}))
    assert "synthetic-personal-id" not in data
    assert "synthetic-member-id" not in data
    assert "unavailable" in data


def test_financial_overview_keeps_its_existing_minimal_company_projection():
    result = structured(call_tool("get_financial_overview", {}, FakeApi(COMPANY)))
    assert result["sections"]["company"]["data"] == {
        "publicId": "company-1", "name": "Sample business", "currency": "PLN", "country": "PL"
    }


def test_company_resource_preserves_business_tax_number():
    data = read_resource("company://current", FakeApi(COMPANY))
    assert "business-tax-number" in data
    assert "synthetic-personal-id" not in data


@pytest.mark.parametrize("identifier", ["pe_sel", "PE-SEL"])
def test_company_response_withholds_separator_normalized_pesel(identifier):
    stored = {"publicId": "company-1", identifier: "synthetic-personal-id"}
    result = structured(call_tool("get_company_details", {}, FakeApi(stored)))
    assert result == {"publicId": "company-1"}
    assert stored[identifier] == "synthetic-personal-id"
