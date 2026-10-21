"""Messages and document requests between a client company and its tax advisor.

Norman's client app and the advisor workspace share one channel per company: a
general conversation, conversations about one transaction, document, invoice or
tax report, and the advisor's requests for documents. Every message notifies the
other side in Norman and by email.

Client tools act for the active company. Advisor tools take the client's company
id from get_advisor_inbox or list_tax_advisor_clients.

Reading never marks a conversation as read: the reads stay truthfully read-only.
Writing does, since the API moves the sender's read pointer to their own message,
so a client or advisor who answers clears what they answered.
"""

from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from mcp.types import ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True)
# Each write emails the other side, which cannot be taken back.
EXTERNAL_IRREVERSIBLE_WRITE = ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=True)

NO_COMPANY_ERROR = {"error": "No company available. Please authenticate first."}
# The API calls a document an attachment.
ABOUT = {"attachment": "document"}


def _url(path: str) -> str:
    return urljoin(config.api_base_url, f"api/v1/tax-advisor/{path}")


def _failed(result: Any) -> Optional[Dict[str, Any]]:
    return result if isinstance(result, dict) and result.get("error") else None


def _rows(result: Any) -> List[Dict[str, Any]]:
    if isinstance(result, dict):
        result = result.get("results") or []
    return [row for row in result if isinstance(row, dict)] if isinstance(result, list) else []


def _conversation(thread: Dict[str, Any]) -> Dict[str, Any]:
    kind = thread.get("kind")
    return {
        "id": thread.get("public_id"),
        "about": ABOUT.get(kind, kind),
        "aboutId": thread.get("target_id"),
        "subject": thread.get("subject") or None,
        "lastMessageAt": thread.get("last_message_at"),
        "lastMessage": thread.get("last_message_preview") or None,
        "unread": thread.get("unread_count", 0),
    }


def _message(message: Dict[str, Any], advisor_emails: Optional[set] = None) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "author": message.get("author_name") or None,
        "text": message.get("body") or "",
        "sentAt": message.get("created"),
    }
    if advisor_emails is not None:
        entry["from"] = "advisor" if message.get("author_email") in advisor_emails else "client"
    else:
        entry["authorEmail"] = message.get("author_email")
    if message.get("system_kind"):
        entry["event"] = message["system_kind"]
    attachments = [
        {"documentId": attachment.get("public_id"), "name": attachment.get("file_name")}
        for attachment in message.get("attachments") or []
    ]
    if attachments:
        entry["documents"] = attachments
    return entry


def _document_request(request: Dict[str, Any]) -> Dict[str, Any]:
    year, month = request.get("period_year"), request.get("period_month")
    period = f"{month:02d}/{year}" if year and month else (str(year) if year else None)
    return {
        "id": request.get("public_id"),
        "title": request.get("title"),
        "description": request.get("description") or None,
        "period": period,
        "dueDate": request.get("due_at"),
        "status": request.get("status"),
        "requestedBy": request.get("requested_by_name") or None,
        "documentsUploaded": len(request.get("fulfillments") or []),
        "conversationId": request.get("thread_id"),
    }


async def _active_advisors(api: Any) -> Any:
    """The company's active advisor links, or the API's error payload."""
    result = await api.arequest("GET", _url("my-advisors/"))
    if _failed(result):
        return result
    advisors = result.get("advisors") if isinstance(result, dict) else None
    return [link for link in advisors or [] if isinstance(link, dict) and link.get("status") == "active"]


async def _read_conversation(api: Any, base: str, threads: List[Dict[str, Any]], conversation_id: Optional[str],
                             advisor_emails: Optional[set], params: Optional[Dict[str, Any]] = None) -> Any:
    """The conversation list plus the messages of the requested (or newest) conversation."""
    chosen = next((t for t in threads if t.get("public_id") == conversation_id), None) if conversation_id else (
        threads[0] if threads else None
    )
    if conversation_id and chosen is None:
        return {"error": f"Conversation {conversation_id} not found."}
    result: Dict[str, Any] = {"conversations": [_conversation(t) for t in threads], "conversation": None}
    if chosen is not None:
        messages = await api.arequest("GET", f"{base}threads/{chosen['public_id']}/messages/", params=params)
        if _failed(messages):
            return messages
        result["conversation"] = {
            **_conversation(chosen),
            "messages": [_message(m, advisor_emails) for m in _rows(messages)],
        }
    return result


def register_advisor_comms_tools(mcp):
    """Register the client and tax advisor messaging tools."""

    @mcp.tool(title="Ask Tax Advisor", annotations=EXTERNAL_IRREVERSIBLE_WRITE)
    async def ask_tax_advisor(
        ctx: Context,
        message: str = Field(description="The question or message for the tax advisor, as the client wants it sent."),
        transaction_id: Optional[str] = Field(default=None, description="Ask about this transaction."),
        document_id: Optional[str] = Field(default=None, description="Ask about this document (attachment)."),
        invoice_id: Optional[str] = Field(default=None, description="Ask about this invoice."),
        report_id: Optional[str] = Field(default=None, description="Ask about this tax report."),
    ) -> Dict[str, Any]:
        """Send a written question or message to the company's tax advisor (a German Steuerberater,
        a Polish company's own accountant).

        For questions the advisor answers in writing: a deduction, a document, a deadline, a
        bookkeeping question. Pass at most one id to ask about a specific transaction, document,
        invoice or tax report. The advisor is notified in Norman and by email; their reply shows
        up in get_tax_advisor_messages. Show the client the message and wait for their
        confirmation before sending.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return NO_COMPANY_ERROR
        if not message.strip():
            return {"error": "The message is empty."}
        # The conversation kinds of the API, one per object a question can be about.
        targets = {"transaction": transaction_id, "attachment": document_id, "invoice": invoice_id, "report": report_id}
        given = [(kind, value) for kind, value in targets.items() if value]
        if len(given) > 1:
            return {"error": "Ask about one transaction, document, invoice or tax report at a time."}

        advisors = await _active_advisors(api)
        if _failed(advisors):
            return advisors
        if not advisors:
            return {
                "error": "This company has no tax advisor connected in Norman yet. "
                "The company owner can invite their tax advisor in Norman.",
            }

        kind, target_id = given[0] if given else ("general", None)
        payload: Dict[str, Any] = {"kind": kind, "initial_body": message.strip()}
        if target_id:
            payload["target_id"] = target_id
        thread = await api.arequest("POST", _url("comms/threads/"), params={"company_id": company_id},
                                    json_data=payload)
        if _failed(thread):
            return thread
        names = [link.get("advisor_name") or link.get("advisor_email") for link in advisors]
        return {
            "sent": True,
            "conversationId": thread.get("public_id") if isinstance(thread, dict) else None,
            "to": names,
            "message": "Sent. The tax advisor is notified in Norman and by email; "
            "their reply will show up in get_tax_advisor_messages.",
        }

    @mcp.tool(title="Get Tax Advisor Messages", annotations=READ_ONLY)
    async def get_tax_advisor_messages(
        ctx: Context,
        conversation_id: Optional[str] = Field(
            default=None, description="A conversation id from an earlier call; the newest conversation if omitted.",
        ),
    ) -> Dict[str, Any]:
        """Read the conversation with the company's tax advisor (a German Steuerberater, a Polish
        company's own accountant).

        Returns the advisor's replies and the client's earlier messages, newest conversation
        first, and the advisor's open requests for documents. A conversation is either general
        or about one transaction, document, invoice or tax report.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return NO_COMPANY_ERROR
        params = {"company_id": company_id}

        advisors = await _active_advisors(api)
        if _failed(advisors):
            return advisors
        threads = await api.arequest("GET", _url("comms/threads/"), params=params)
        if _failed(threads):
            return threads
        result = await _read_conversation(
            api, _url("comms/"), _rows(threads), conversation_id,
            {link.get("advisor_email") for link in advisors},
        )
        if _failed(result):
            return result
        requests = await api.arequest("GET", _url("comms/document-requests/"), params={**params, "status": "open"})
        result["openDocumentRequests"] = [] if _failed(requests) else [_document_request(r) for r in _rows(requests)]
        result["advisors"] = [link.get("advisor_name") or link.get("advisor_email") for link in advisors]
        return result

    @mcp.tool(title="Fulfill Document Request", annotations=EXTERNAL_IRREVERSIBLE_WRITE)
    async def fulfill_document_request(
        ctx: Context,
        request_id: str = Field(description="The document request id from get_tax_advisor_messages."),
        document_ids: List[str] = Field(
            description="Documents already uploaded to Norman that answer the request (attachment ids).",
            min_length=1, max_length=20,
        ),
        note: Optional[str] = Field(default=None, description="A short note for the tax advisor."),
    ) -> Dict[str, Any]:
        """Answer the tax advisor's request for documents with documents uploaded to Norman.

        Upload the files first with the document tools, then pass their ids here. The advisor
        is notified in Norman and by email.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return NO_COMPANY_ERROR
        payload: Dict[str, Any] = {"attachment_ids": document_ids}
        if note:
            payload["note"] = note
        result = await api.arequest("POST", _url(f"comms/document-requests/{request_id}/fulfill/"),
                                    json_data=payload)
        if _failed(result):
            return result
        request = result.get("request") if isinstance(result, dict) else None
        return {
            "request": _document_request(request) if isinstance(request, dict) else None,
            "documentsAttached": result.get("fulfillment_count") if isinstance(result, dict) else None,
        }

    @mcp.tool(title="Get Advisor Inbox", annotations=READ_ONLY)
    async def get_advisor_inbox(ctx: Context) -> Dict[str, Any]:
        """For tax advisors: the clients with unanswered messages or open document requests.

        Lists only the clients that need attention, most unread messages first. Read a client's
        conversation with get_client_messages.
        """
        api = ctx.request_context.lifespan_context["api"]
        inbox = await api.arequest("GET", _url("inbox/"))
        if _failed(inbox):
            return inbox
        clients = [
            {
                "companyId": row.get("company_id"),
                "companyName": row.get("company_name"),
                "unreadMessages": row.get("unread_messages", 0),
                "openDocumentRequests": row.get("open_requests", 0),
            }
            for row in (inbox.get("per_company") or [] if isinstance(inbox, dict) else [])
            if row.get("unread_messages") or row.get("open_requests")
        ]
        clients.sort(key=lambda client: (-client["unreadMessages"], -client["openDocumentRequests"]))
        return {
            "unreadMessages": inbox.get("unread_messages", 0),
            "openDocumentRequests": inbox.get("open_requests", 0),
            "clients": clients,
        }

    @mcp.tool(title="Get Client Messages", annotations=READ_ONLY)
    async def get_client_messages(
        ctx: Context,
        company_id: str = Field(description="The client company's id from get_advisor_inbox or list_tax_advisor_clients."),
        conversation_id: Optional[str] = Field(
            default=None, description="A conversation id from an earlier call; the newest conversation if omitted.",
        ),
    ) -> Dict[str, Any]:
        """For tax advisors: read a client's conversations and open document requests.

        Returns the client's conversations, newest first, with the messages of the requested one.
        """
        api = ctx.request_context.lifespan_context["api"]
        base = _url(f"clients/{company_id}/")
        threads = await api.arequest("GET", f"{base}threads/")
        if _failed(threads):
            return threads
        result = await _read_conversation(api, base, _rows(threads), conversation_id, None)
        if _failed(result):
            return result
        requests = await api.arequest("GET", f"{base}document-requests/", params={"status": "open"})
        result["openDocumentRequests"] = [] if _failed(requests) else [_document_request(r) for r in _rows(requests)]
        result["companyId"] = company_id
        return result

    @mcp.tool(title="Reply to Client", annotations=EXTERNAL_IRREVERSIBLE_WRITE)
    async def reply_to_client(
        ctx: Context,
        company_id: str = Field(description="The client company's id."),
        message: str = Field(description="The message for the client, as the advisor wants it sent."),
        conversation_id: Optional[str] = Field(
            default=None, description="Reply in this conversation; the client's general conversation if omitted.",
        ),
    ) -> Dict[str, Any]:
        """For tax advisors: write to a client in Norman.

        The client is notified in Norman and by email. Show the advisor the message and wait
        for their confirmation before sending.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not message.strip():
            return {"error": "The message is empty."}
        base = _url(f"clients/{company_id}/")
        if conversation_id:
            result = await api.arequest("POST", f"{base}threads/{conversation_id}/messages/",
                                        json_data={"body": message.strip()})
        else:
            result = await api.arequest("POST", f"{base}threads/",
                                        json_data={"kind": "general", "initial_body": message.strip()})
        if _failed(result):
            return result
        thread_id = conversation_id or (result.get("public_id") if isinstance(result, dict) else None)
        return {"sent": True, "companyId": company_id, "conversationId": thread_id}

    @mcp.tool(title="Request Documents from Client", annotations=EXTERNAL_IRREVERSIBLE_WRITE)
    async def request_documents_from_client(
        ctx: Context,
        company_id: str = Field(description="The client company's id."),
        title: str = Field(description="What the client should send, e.g. 'Kontoauszüge Januar 2026'.", max_length=200),
        description: Optional[str] = Field(default=None, description="Details for the client."),
        period_year: Optional[int] = Field(default=None, ge=2000, le=2100, description="The year the documents cover."),
        period_month: Optional[int] = Field(default=None, ge=1, le=12, description="The month the documents cover."),
        due_date: Optional[str] = Field(default=None, description="Due date, YYYY-MM-DD."),
        conversation_id: Optional[str] = Field(
            default=None, description="Ask in this conversation; the client's general conversation if omitted.",
        ),
    ) -> Dict[str, Any]:
        """For tax advisors: ask a client for documents.

        The client is notified in Norman and by email and answers by uploading the documents.
        Show the advisor the request and wait for their confirmation before sending.
        """
        api = ctx.request_context.lifespan_context["api"]
        payload: Dict[str, Any] = {"title": title}
        optional = {"description": description, "period_year": period_year, "period_month": period_month,
                    "due_at": due_date, "thread_id": conversation_id}
        payload.update({key: value for key, value in optional.items() if value not in (None, "")})
        result = await api.arequest("POST", _url(f"clients/{company_id}/document-requests/"), json_data=payload)
        if _failed(result):
            return result
        return {"companyId": company_id, "request": _document_request(result) if isinstance(result, dict) else None}
