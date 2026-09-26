"""validate_tax_number: a valid number is a result, an invalid one too.

The API answers 201 with the bare JSON string "Tax number is valid", which the
tool returned unchanged, so every VALID number failed output validation. An
invalid number is a 400 with the reason as a bare string.
"""

from tests.mcp_harness import FakeApi, call_tool, structured


def test_a_valid_tax_number():
    api = FakeApi("Tax number is valid")

    data = structured(call_tool("validate_tax_number", {"tax_number": "1121081508150", "region_code": "BE"}, api))

    assert data == {"valid": True, "message": "Tax number is valid"}
    assert api.requests[-1][2]["json_data"] == {"tax_number": "1121081508150", "region_code": "BE"}


def test_an_invalid_tax_number_is_a_negative_result_not_an_error():
    api = FakeApi({"error": "Tax number is not valid", "status_code": 400, "detail": "Tax number is not valid"})

    data = structured(call_tool("validate_tax_number", {"tax_number": "123", "region_code": "BE"}, api))

    assert data == {"valid": False, "message": "Tax number is not valid"}


def test_other_failures_stay_errors():
    result = call_tool(
        "validate_tax_number",
        {"tax_number": "123", "region_code": "BE"},
        FakeApi({"error": "Your Norman session expired.", "status_code": 401}),
    )

    assert result.isError
