"""Failed writes are reported as failures, never as "done".

The API client returns an error result instead of raising, so a tool that
ignores the response -- or wraps it in a success message -- tells the user a
change happened when it did not.
"""

import pytest

from tests.mcp_harness import FakeApi, call_tool, error_payload, structured

NOT_FOUND = {"error": "Not found.", "status_code": 404, "detail": {"detail": "Not found."}}


def test_activity_start_is_sent_as_an_iso_date():
    api = FakeApi({"publicId": "company-1", "activityStart": "2024-03-01"})

    data = structured(call_tool("update_company_details", {"activity_start": "2024-03-01"}, api))

    method, _url, kwargs = api.requests[-1]
    assert method == "PATCH"
    # A datetime object here broke json.dumps; a datetime string is rejected
    # by the API's DateField.
    assert kwargs["json_data"] == {"activityStart": "2024-03-01"}
    assert data["message"] == "Company updated successfully"


def test_a_time_of_day_is_rejected_before_anything_is_sent():
    api = FakeApi({"publicId": "company-1"})

    result = call_tool("update_company_details", {"activity_start": "2024-03-01T15:30:00"}, api)

    assert result.isError
    assert api.requests == []


def test_a_failed_company_update_is_not_reported_as_success():
    failure = {"error": "Request failed with HTTP 400 (Bad Request).", "status_code": 400, "detail": {"taxNumber": ["Invalid"]}}
    api = FakeApi(failure)

    result = call_tool("update_company_details", {"tax_id": "123"}, api)

    assert error_payload(result) == failure


@pytest.mark.parametrize(
    ("tool", "arguments", "confirmation"),
    [
        ("delete_client", {"client_id": "client-1"}, {"message": "Client deleted successfully"}),
        ("delete_rule", {"rule_id": "rule-1"}, {"status": "deleted", "ruleId": "rule-1"}),
        ("delete_bill", {"bill_id": "bill-1"}, {"message": "Bill bill-1 deleted successfully."}),
        ("delete_vendor", {"vendor_id": "vendor-1"}, {"message": "Vendor vendor-1 deleted successfully."}),
    ],
)
def test_deletes_confirm_only_what_the_api_confirmed(tool, arguments, confirmation):  # noqa: ANN001
    deleted = FakeApi({})  # the client's result for an empty 204
    assert structured(call_tool(tool, arguments, deleted)) == confirmation
    assert deleted.requests[-1][0] == "DELETE"

    assert error_payload(call_tool(tool, arguments, FakeApi(NOT_FOUND))) == NOT_FOUND


def test_failed_pings_are_counted_as_failed():
    def respond(_method, url, _kwargs):  # noqa: ANN001, ANN202
        return NOT_FOUND if url.endswith("/tx-2/") else {"detail": "Reminder sent."}

    data = structured(
        call_tool(
            "ping_client_for_documents",
            {"company_id": "client-co", "transaction_ids": ["tx-1", "tx-2"]},
            FakeApi(respond),
        ),
    )

    assert data["succeeded"] == 1
    assert data["failed"] == 1
    assert data["details"]["succeeded"] == [{"transactionId": "tx-1", "detail": "Reminder sent."}]
    assert data["details"]["failed"][0]["transactionId"] == "tx-2"
    assert data["details"]["failed"][0]["status_code"] == 404


def test_a_failed_company_lookup_raises_no_false_registration_findings():
    def respond(_method, url, _kwargs):  # noqa: ANN001, ANN202
        if url.endswith("/companies/client-co/"):
            return {"error": "Access forbidden. Check your account permissions.", "status_code": 403}
        return {"results": []}

    data = structured(call_tool("get_tax_compliance_status", {"company_id": "client-co"}, FakeApi(respond)))

    assert data["registration"] == {"error": "Access forbidden. Check your account permissions."}
    assert not [item for item in data["actionItems"] if "missing" in item]


def test_a_failed_company_lookup_is_visible_in_the_client_overview():
    def respond(_method, url, _kwargs):  # noqa: ANN001, ANN202
        if url.endswith("/companies/client-co/"):
            return NOT_FOUND
        return {"results": []}

    data = structured(call_tool("get_client_overview", {"company_id": "client-co"}, FakeApi(respond)))

    assert data["company"] == {"error": "Not found."}


def test_a_refused_tax_submission_reports_the_api_reason():
    refusal = {
        "error": "Filing is not included in your plan.",
        "status_code": 403,
        "code": "subscription_required",
        "detail": {"detail": "Filing is not included in your plan.", "code": "subscription_required"},
    }

    result = call_tool("submit_tax_report", {"report_id": "report-1"}, FakeApi(refusal))

    assert error_payload(result) == refusal


def test_an_sme_tool_reports_a_failed_company_lookup_as_itself():
    expired = {"error": "Your Norman session expired.", "status_code": 401}

    result = call_tool("search_skr_by_code", {"code": "42"}, FakeApi(expired))

    # It used to say the company was a freelance account.
    assert error_payload(result) == expired
