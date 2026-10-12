"""Client declarations waiting for their tax advisor's signature."""

from norman_mcp.server import mcp as server
from tests.mcp_harness import FakeApi, call_tool, structured

BASE = "/api/v1/tax-advisor/pending-signatures/"
REQUEST = {
    "public_id": "sig-1", "companyId": "company-9", "companyName": "Muster Design", "declaration_type": "advance_vat",
    "label": "UStVA Q3 2026", "status": "pending", "transferticket": "", "error_message": "",
    "requestedByEmail": "max@muster.de", "signed_at": None, "rejected_at": None, "created": "2026-10-12T08:00:00Z",
}
UNLABELLED = {**REQUEST, "public_id": "sig-2", "label": "", "declaration_type": "euer"}


def respond(routes):
    """Answer each request by the first route whose path the URL ends with."""

    def answer(method, url, kwargs):  # noqa: ANN001, ANN202
        for (route_method, path), body in routes.items():
            if method == route_method and url.split("?")[0].endswith(path):
                return body(kwargs) if callable(body) else body
        raise AssertionError(f"unexpected {method} {url}")

    return answer


def test_the_inbox_lists_requests_with_a_label_to_confirm_and_the_certificate_state():
    api = FakeApi(respond({
        ("GET", BASE): [REQUEST, UNLABELLED],
        ("GET", "/api/v1/tax-advisor/elster-certificate/"): {"fingerprint": "ab", "valid_until": "2028-01-31"},
    }))

    result = structured(call_tool("list_signature_requests", {}, api))

    assert [r["label"] for r in result["requests"]] == ["UStVA Q3 2026", "EÜR Muster Design"]
    assert result["requests"][0]["clientCompanyName"] == "Muster Design"
    assert result["certificate"] == {"uploaded": True, "validUntil": "2028-01-31"}
    assert api.requests[0][2]["params"] == {"status": "pending"}


def test_a_missing_certificate_is_reported_before_anyone_tries_to_sign():
    api = FakeApi(respond({
        ("GET", BASE): [REQUEST],
        ("GET", "/api/v1/tax-advisor/elster-certificate/"): {"error": "Resource not found", "status_code": 404},
    }))

    result = structured(call_tool("list_signature_requests", {}, api))

    assert result["certificate"]["uploaded"] is False
    assert "ELSTER certificate" in result["certificate"]["hint"]


def test_signing_needs_the_confirmed_label_and_sends_nothing_otherwise():
    api = FakeApi(respond({("GET", BASE): [REQUEST]}))

    result = structured(call_tool("sign_and_submit_declaration", {"request_id": "sig-1", "label": "UStVA Q2 2026"}, api))

    assert "does not match" in result["error"]
    assert result["requestLabel"] == "UStVA Q3 2026"
    assert [method for method, _, _ in api.requests] == ["GET"]


def test_signing_submits_and_returns_the_transfer_ticket():
    signed = {**REQUEST, "status": "signed", "transferticket": "et-123", "signed_at": "2026-10-12T09:00:00Z"}
    api = FakeApi(respond({("GET", BASE): [REQUEST], ("POST", BASE + "sig-1/sign/"): signed}))

    result = structured(call_tool("sign_and_submit_declaration", {"request_id": "sig-1", "label": " ustva q3 2026 "}, api))

    assert (result["status"], result["transferticket"]) == ("signed", "et-123")
    assert api.requests[1][0] == "POST"


def test_a_request_that_is_not_pending_is_never_signed():
    api = FakeApi(respond({("GET", BASE): []}))

    result = structured(call_tool("sign_and_submit_declaration", {"request_id": "sig-1", "label": "UStVA Q3 2026"}, api))

    assert "not waiting for your signature" in result["error"]
    assert len(api.requests) == 1


def test_signing_without_a_certificate_explains_the_one_time_upload():
    api = FakeApi(respond({
        ("GET", BASE): [REQUEST],
        ("POST", BASE + "sig-1/sign/"): {"error": "Request failed: 400", "status_code": 400,
                                          "detail": {"detail": "Upload your ELSTER certificate before signing",
                                                     "code": "no_certificate"}},
    }))

    result = structured(call_tool("sign_and_submit_declaration", {"request_id": "sig-1", "label": "UStVA Q3 2026"}, api))

    assert "Upload the certificate" in result["error"]


def test_rejecting_sends_the_reason():
    rejected = {**REQUEST, "status": "rejected", "error_message": "Bitte Belege für September nachreichen."}
    api = FakeApi(respond({("POST", BASE + "sig-1/reject/"): rejected}))

    result = structured(call_tool("reject_signature_request", {"request_id": "sig-1",
                                                               "reason": "Bitte Belege für September nachreichen."}, api))

    assert api.requests[0][2]["json_data"] == {"reason": "Bitte Belege für September nachreichen."}
    assert result["status"] == "rejected"


def test_annotations_tell_a_binding_submission_from_a_read():
    tools = server._tool_manager._tools  # noqa: SLF001

    def hints(name):  # noqa: ANN001, ANN202
        a = tools[name].annotations
        return (a.read_only_hint, a.open_world_hint, a.destructive_hint)

    assert hints("list_signature_requests") == (True, False, False)
    assert hints("sign_and_submit_declaration") == (False, True, True)
    assert hints("reject_signature_request") == (False, False, True)
