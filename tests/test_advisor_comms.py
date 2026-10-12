"""Messages and document requests between a client and its tax advisor."""

from norman_mcp.server import mcp as server
from tests.mcp_harness import FakeApi, call_tool, structured

COMMS = "/api/v1/tax-advisor/comms/"
CLIENT = "/api/v1/tax-advisor/clients/company-9/"
ADVISORS = {
    "advisors": [
        {"public_id": "link-1", "advisor_name": "Elena Müller", "advisor_email": "e.mueller@kanzlei.de", "status": "active"},
        {"public_id": "link-2", "advisor_name": "Former Advisor", "advisor_email": "old@kanzlei.de", "status": "revoked"},
    ],
    "pending_invitations": [],
}
THREADS = [
    {"public_id": "thread-2", "kind": "transaction", "target_id": "tx-1", "subject": "", "unread_count": 1,
     "last_message_at": "2026-10-12T10:00:00Z", "last_message_preview": "Bitte Beleg nachreichen"},
    {"public_id": "thread-1", "kind": "general", "target_id": None, "subject": "", "unread_count": 0,
     "last_message_at": "2026-10-01T09:00:00Z", "last_message_preview": "Danke!"},
]
MESSAGES = [
    {"public_id": "m-1", "body": "Ist das ein Bewirtungsbeleg?", "author_name": "Max Muster",
     "author_email": "max@muster.de", "system_kind": "", "attachments": [], "created": "2026-10-11T08:00:00Z"},
    {"public_id": "m-2", "body": "Bitte Beleg nachreichen", "author_name": "Elena Müller",
     "author_email": "e.mueller@kanzlei.de", "system_kind": "",
     "attachments": [{"public_id": "doc-1", "file_name": "hinweis.pdf", "file_url": "https://signed"}],
     "created": "2026-10-12T10:00:00Z"},
]
OPEN_REQUEST = {
    "public_id": "req-1", "thread_id": "thread-1", "title": "Kontoauszüge September", "description": "",
    "period_year": 2026, "period_month": 9, "due_at": "2026-10-20", "status": "open",
    "requested_by_name": "Elena Müller", "fulfillments": [], "created": "2026-10-12T09:00:00Z",
}


def respond(routes):
    """Answer each request by the first route whose path the URL ends with."""

    def answer(method, url, kwargs):  # noqa: ANN001, ANN202
        for (route_method, path), body in routes.items():
            if method == route_method and url.split("?")[0].endswith(path):
                return body(kwargs) if callable(body) else body
        raise AssertionError(f"unexpected {method} {url}")

    return answer


def test_a_question_goes_to_the_general_conversation_and_names_the_active_advisors():
    api = FakeApi(respond({
        ("GET", "/api/v1/tax-advisor/my-advisors/"): ADVISORS,
        ("POST", COMMS + "threads/"): {"public_id": "thread-1", "kind": "general"},
    }))

    result = structured(call_tool("ask_tax_advisor", {"message": " Kann ich mein Laptop absetzen? "}, api))

    method, _, kwargs = api.requests[1]
    assert method == "POST"
    assert kwargs["params"] == {"company_id": "company-1"}
    assert kwargs["json_data"] == {"kind": "general", "initial_body": "Kann ich mein Laptop absetzen?"}
    assert result["sent"] is True
    assert result["conversationId"] == "thread-1"
    assert result["to"] == ["Elena Müller"]


def test_a_question_about_a_document_is_pinned_to_it():
    api = FakeApi(respond({
        ("GET", "/api/v1/tax-advisor/my-advisors/"): ADVISORS,
        ("POST", COMMS + "threads/"): {"public_id": "thread-3", "kind": "attachment"},
    }))

    structured(call_tool("ask_tax_advisor", {"message": "Reicht dieser Beleg?", "document_id": "doc-7"}, api))

    assert api.requests[1][2]["json_data"] == {"kind": "attachment", "initial_body": "Reicht dieser Beleg?",
                                               "target_id": "doc-7"}


def test_one_object_per_question_and_nothing_is_sent_otherwise():
    api = FakeApi(respond({}))

    result = structured(call_tool("ask_tax_advisor", {"message": "Frage", "transaction_id": "tx-1",
                                                      "invoice_id": "inv-1"}, api))

    assert "one transaction" in result["error"]
    assert api.requests == []


def test_without_an_active_advisor_the_question_is_not_sent():
    api = FakeApi(respond({("GET", "/api/v1/tax-advisor/my-advisors/"): {"advisors": [ADVISORS["advisors"][1]]}}))

    result = structured(call_tool("ask_tax_advisor", {"message": "Hallo"}, api))

    assert "no tax advisor" in result["error"]
    assert [method for method, _, _ in api.requests] == ["GET"]


def test_messages_show_who_wrote_what_and_the_open_document_requests_without_marking_read():
    api = FakeApi(respond({
        ("GET", "/api/v1/tax-advisor/my-advisors/"): ADVISORS,
        ("GET", COMMS + "threads/"): THREADS,
        ("GET", COMMS + "threads/thread-2/messages/"): MESSAGES,
        ("GET", COMMS + "document-requests/"): [OPEN_REQUEST],
    }))

    result = structured(call_tool("get_tax_advisor_messages", {}, api))

    conversation = result["conversation"]
    assert conversation["id"] == "thread-2" and conversation["about"] == "transaction"
    assert [m["from"] for m in conversation["messages"]] == ["client", "advisor"]
    assert conversation["messages"][1]["documents"] == [{"documentId": "doc-1", "name": "hinweis.pdf"}]
    assert "https://signed" not in str(result)
    assert [c["id"] for c in result["conversations"]] == ["thread-2", "thread-1"]
    assert result["openDocumentRequests"][0]["period"] == "09/2026"
    assert result["advisors"] == ["Elena Müller"]
    assert {method for method, _, _ in api.requests} == {"GET"}
    assert api.requests[3][2]["params"] == {"company_id": "company-1", "status": "open"}


def test_an_unknown_conversation_is_an_error():
    api = FakeApi(respond({
        ("GET", "/api/v1/tax-advisor/my-advisors/"): ADVISORS,
        ("GET", COMMS + "threads/"): THREADS,
    }))

    result = structured(call_tool("get_tax_advisor_messages", {"conversation_id": "thread-x"}, api))

    assert result["error"] == "Conversation thread-x not found."


def test_uploaded_documents_answer_a_document_request():
    fulfilled = {**OPEN_REQUEST, "status": "fulfilled", "fulfillments": [{"public_id": "f-1"}]}
    api = FakeApi(respond({
        ("POST", COMMS + "document-requests/req-1/fulfill/"): {"request": fulfilled, "fulfillment_count": 1},
    }))

    result = structured(call_tool("fulfill_document_request", {"request_id": "req-1", "document_ids": ["doc-2"],
                                                               "note": "Auszug September"}, api))

    assert api.requests[0][2]["json_data"] == {"attachment_ids": ["doc-2"], "note": "Auszug September"}
    assert result["request"]["status"] == "fulfilled"
    assert result["documentsAttached"] == 1


def test_the_advisor_inbox_lists_only_clients_that_need_attention():
    api = FakeApi(respond({("GET", "/api/v1/tax-advisor/inbox/"): {
        "unread_messages": 3, "open_requests": 1,
        "per_company": [
            {"company_id": "c-1", "company_name": "Quiet GmbH", "unread_messages": 0, "open_requests": 0},
            {"company_id": "c-2", "company_name": "Waiting UG", "unread_messages": 0, "open_requests": 1},
            {"company_id": "c-3", "company_name": "Busy Freelancer", "unread_messages": 3, "open_requests": 0},
        ],
    }}))

    result = structured(call_tool("get_advisor_inbox", {}, api))

    assert [client["companyName"] for client in result["clients"]] == ["Busy Freelancer", "Waiting UG"]
    assert result["unreadMessages"] == 3


def test_an_advisor_reads_a_client_conversation():
    api = FakeApi(respond({
        ("GET", CLIENT + "threads/"): THREADS,
        ("GET", CLIENT + "threads/thread-1/messages/"): MESSAGES[:1],
        ("GET", CLIENT + "document-requests/"): [],
    }))

    result = structured(call_tool("get_client_messages", {"company_id": "company-9", "conversation_id": "thread-1"},
                                  api))

    message = result["conversation"]["messages"][0]
    assert message["authorEmail"] == "max@muster.de" and "from" not in message
    assert result["companyId"] == "company-9"
    assert {method for method, _, _ in api.requests} == {"GET"}


def test_an_advisor_replies_in_a_conversation_or_in_the_general_one():
    api = FakeApi(respond({
        ("POST", CLIENT + "threads/thread-2/messages/"): {"public_id": "m-3"},
        ("POST", CLIENT + "threads/"): {"public_id": "thread-1"},
    }))

    in_thread = structured(call_tool("reply_to_client", {"company_id": "company-9", "message": "Passt so.",
                                                         "conversation_id": "thread-2"}, api))
    general = structured(call_tool("reply_to_client", {"company_id": "company-9", "message": "Hallo!"}, api))

    assert api.requests[0][2]["json_data"] == {"body": "Passt so."}
    assert api.requests[1][2]["json_data"] == {"kind": "general", "initial_body": "Hallo!"}
    assert (in_thread["conversationId"], general["conversationId"]) == ("thread-2", "thread-1")


def test_an_advisor_requests_documents_with_only_the_fields_given():
    api = FakeApi(respond({("POST", CLIENT + "document-requests/"): OPEN_REQUEST}))

    result = structured(call_tool("request_documents_from_client", {
        "company_id": "company-9", "title": "Kontoauszüge September", "period_year": 2026, "period_month": 9,
        "due_date": "2026-10-20",
    }, api))

    assert api.requests[0][2]["json_data"] == {"title": "Kontoauszüge September", "period_year": 2026,
                                               "period_month": 9, "due_at": "2026-10-20"}
    assert result["request"]["id"] == "req-1"


def test_reads_are_read_only_and_every_message_counts_as_an_irreversible_external_write():
    tools = server._tool_manager._tools  # noqa: SLF001
    for name in ("get_tax_advisor_messages", "get_advisor_inbox", "get_client_messages"):
        annotations = tools[name].annotations
        assert (annotations.read_only_hint, annotations.open_world_hint, annotations.destructive_hint) == (
            True, False, False), name
    for name in ("ask_tax_advisor", "fulfill_document_request", "reply_to_client", "request_documents_from_client"):
        annotations = tools[name].annotations
        assert (annotations.read_only_hint, annotations.open_world_hint, annotations.destructive_hint) == (
            False, True, True), name
