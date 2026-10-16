"""A filing blocked by the email gate says so, and the agent can mail a new link.

Every 403 used to read "Subscription required", so a paying user with an
unconfirmed address was told to buy a plan they already had.
"""

import json

import pytest
import requests

from tests.mcp_harness import GermanApi as FakeApi
from tests.mcp_harness import call_tool, structured


def _forbidden(code: str):  # noqa: ANN202
    response = requests.Response()
    response.status_code = 403
    response._content = json.dumps({"code": code}).encode()  # noqa: SLF001

    def respond(*_):  # noqa: ANN002, ANN202
        raise requests.HTTPError(response=response)

    return respond


@pytest.mark.parametrize(
    ("code", "error"),
    [("email_not_verified", "Email not confirmed"), ("subscription_required", "Subscription required")],
)
def test_a_blocked_submission_names_its_gate(code, error):  # noqa: ANN001
    data = structured(call_tool("submit_tax_report", {"report_id": "report-1"}, FakeApi(_forbidden(code))))

    assert data["error"] == error


def test_resend_asks_the_api_for_a_new_link():
    api = FakeApi({"verified": False})

    assert structured(call_tool("resend_email_confirmation", {}, api)) == {"verified": False}
    assert api.requests[0][0] == "POST"
    assert api.requests[0][1].endswith("/api/v1/auth/resend-confirmation/")
