import asyncio
import base64

from mcp.server.fastmcp import FastMCP

from norman_mcp.tools.documents import register_document_tools


class _Api:
    company_id = "company-1"

    def __init__(self, response=None):
        self.calls = []
        self.response = response or {
            "created": True,
            "document": {"publicId": "attachment-1"},
        }

    async def arequest(self, method, url, params=None, json_data=None, files=None):  # noqa: ANN001, ANN201
        self.calls.append(
            {
                "method": method,
                "url": url,
                "json_data": json_data,
                "content": files["file"].read(),
            },
        )
        return self.response


class _Ctx:
    def __init__(self, api):  # noqa: ANN001
        class _RequestContext:
            lifespan_context = {"api": api}

        self.request_context = _RequestContext()


def _tool():
    server = FastMCP()
    register_document_tools(server)
    return server._tool_manager._tools["upload_structured_attachments"].fn  # noqa: SLF001


def test_structured_upload_maps_per_document_metadata_without_transaction_fields():
    api = _Api()

    result = asyncio.run(
        _tool()(
            _Ctx(api),
            documents=[
                {
                    "file_content_base64": base64.b64encode(b"%PDF-1.4 test").decode(),
                    "file_name": "invoice.pdf",
                    "source_system": "stereotrader",
                    "external_id": "invoice-123",
                    "metadata": {
                        "supplier": "Example GmbH",
                        "invoice_number": "RE-123",
                        "invoice_date": "2026-08-31",
                        "service_date": "2026-08-30",
                        "net_amount": "100.00",
                        "vat_amount": "19.00",
                        "gross_amount": "119.00",
                        "currency": "EUR",
                        "document_type": "invoice",
                        "direction": "incoming",
                        "tags": ["stereotrader", "hosting"],
                    },
                },
            ],
        ),
    )

    assert result["created"] == 1
    assert result["failed"] == 0
    assert len(api.calls) == 1
    call = api.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/companies/company-1/attachments/structured-import/")
    assert call["content"] == b"%PDF-1.4 test"
    assert call["json_data"]["external_source"] == "stereotrader"
    assert call["json_data"]["external_id"] == "invoice-123"
    assert call["json_data"]["gross_amount"] == "119.00"
    assert "transactions" not in call["json_data"]
    assert "cashflow_type" not in call["json_data"]


def test_structured_upload_rejects_unknown_metadata_before_upload():
    api = _Api()

    result = asyncio.run(
        _tool()(
            _Ctx(api),
            documents=[
                {
                    "file_content_base64": base64.b64encode(b"test").decode(),
                    "file_name": "invoice.pdf",
                    "metadata": {"invented_field": "value"},
                },
            ],
        ),
    )

    assert result["created"] == 0
    assert result["failed"] == 1
    assert "Unsupported metadata fields" in result["results"][0]["error"]
    assert api.calls == []


def test_structured_upload_counts_idempotent_retry_as_existing():
    api = _Api(response={"created": False, "document": {"publicId": "attachment-1"}})

    result = asyncio.run(
        _tool()(
            _Ctx(api),
            documents=[
                {
                    "file_content_base64": base64.b64encode(b"test").decode(),
                    "file_name": "invoice.pdf",
                    "source_system": "stereotrader",
                    "external_id": "invoice-123",
                },
            ],
        ),
    )

    assert result["created"] == 0
    assert result["existing"] == 1
    assert result["failed"] == 0
