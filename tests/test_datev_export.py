"""trigger_datev_export returns a download link instead of a lost file.

Without responseFormat=download_url the API answers with the ZIP itself, which
a JSON tool result cannot carry: the client replaced it with a bare
{"success": true}. The company's chart of accounts is serialized as an object,
which the tool stringified, rejecting every SME unless skr_variant was passed.
"""

import pytest

from tests.mcp_harness import FakeApi, call_tool, error_payload, structured

LINK = {
    "downloadUrl": "https://api.norman.finance/api/v1/dl/token/",
    "fileName": "Norman_DATEV_Export_20260926.zip",
    "mimeType": "application/zip",
    "expiresInSeconds": 3600,
}


def _company(chart):  # noqa: ANN001, ANN202
    return {"datevAdvisorNumber": "1234", "datevClientNumber": "5678", "chartOfAccounts": chart}


def _api(company):  # noqa: ANN001, ANN202
    return FakeApi(lambda method, _url, _kw: company if method == "GET" else LINK)


PERIOD = {"date_from": "2026-01-01", "date_to": "2026-06-30"}


@pytest.mark.parametrize(
    ("chart", "variant"),
    [
        ({"publicId": "coa-1", "name": "SKR 03", "code": "skr03"}, "SKR03"),
        ({"publicId": "coa-2", "name": "SKR 04", "code": "skr04"}, "SKR04"),
        (None, "SKR04"),
    ],
)
def test_the_export_asks_for_a_download_link_with_the_saved_chart(chart, variant):  # noqa: ANN001
    api = _api(_company(chart))

    data = structured(call_tool("trigger_datev_export", PERIOD, api))

    assert data == LINK
    method, url, kwargs = api.requests[-1]
    assert method == "POST"
    assert url.endswith("/api/v1/accounting/datev-export/")
    assert kwargs["json_data"] == {
        "dateFrom": "2026-01-01",
        "dateTo": "2026-06-30",
        "includeDocuments": True,
        "advisorNumber": "1234",
        "clientNumber": "5678",
        "skrVariant": variant,
        "responseFormat": "download_url",
    }


def test_an_explicit_variant_is_accepted_in_any_case():
    api = _api(_company(None))

    call_tool("trigger_datev_export", {**PERIOD, "skr_variant": "skr03"}, api)

    assert api.requests[-1][2]["json_data"]["skrVariant"] == "SKR03"


def test_a_non_skr_chart_is_refused_before_exporting():
    api = _api(_company({"publicId": "coa-3", "name": "Polish", "code": "PL_FULL"}))

    result = call_tool("trigger_datev_export", PERIOD, api)

    assert error_payload(result) == {"error": "skr_variant must be SKR03 or SKR04."}
    assert [method for method, _url, _kw in api.requests] == ["GET"]


def test_missing_datev_numbers_are_a_tool_error():
    api = _api({"chartOfAccounts": None})

    payload = error_payload(call_tool("trigger_datev_export", PERIOD, api))

    assert payload["error"] == "DATEV advisor number and client number are required."
