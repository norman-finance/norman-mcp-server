"""A 403 from Norman keeps its reason: paywalls must not read as a permissions problem."""

from unittest.mock import MagicMock, patch

import requests

from norman_mcp import config
from norman_mcp.api.client import NormanAPI


def _forbidden(body=None):  # noqa: ANN001, ANN202
    response = MagicMock(status_code=403)
    if body is None:
        response.json.side_effect = ValueError("no JSON")
    else:
        response.json.return_value = body
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    return response


def _call(response):  # noqa: ANN001, ANN202
    api = NormanAPI(authenticate_on_init=False)
    with patch.object(api, "_resolve_norman_token", return_value="norman-token"), \
            patch("requests.request", return_value=response):
        return api._make_request("POST", f"{config.api_base_url}api/v1/companies/")


def test_a_plan_gate_says_what_is_missing_and_keeps_its_code():
    result = _call(_forbidden({
        "detail": "Sending invoices by email is not included in your plan.",
        "code": "invoice_send_limit_reached",
    }))

    assert result == {
        "error": "Sending invoices by email is not included in your plan.",
        "status_code": 403,
        "code": "invoice_send_limit_reached",
    }


def test_a_403_without_a_reason_keeps_the_generic_message():
    assert _call(_forbidden()) == {"error": "Access forbidden. Check your account permissions.", "status_code": 403}
