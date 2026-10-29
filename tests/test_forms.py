import asyncio

import pytest

from norman_mcp.server import mcp
from tests.mcp_harness import FakeApi, call_tool, structured


def test_catalog_and_detail_do_not_read_company_or_change_country():
    api = FakeApi({"forms": []}, company_id=None)
    assert structured(call_tool("list_polish_forms", {"query": "UPL-1", "locale": "uk"}, api)) == {
        "forms": []
    }
    assert api.requests[0][1].endswith("/api/v1/toolkits/forms/")
    assert api.requests[0][2]["params"] == {"q": "UPL-1", "locale": "uk"}
    call_tool("get_polish_form", {"form_id": "upl-1"}, api)
    assert len(api.requests) == 2
    assert api.requests[-1][1].endswith("/forms/upl-1/")


def test_preparation_passes_exact_fields_version_and_only_calls_generation():
    output = {
        "status": "draft",
        "previewText": "Example",
        "downloadUrl": "https://example.test/file",
        "expiresIn": 600,
    }
    api = FakeApi(output)
    fields = {"issuer": "Synthetic Example", "amount": "10.50"}
    result = structured(
        call_tool(
            "generate_polish_document",
            {
                "form_id": "payment-request",
                "version": "2026-10-28.1",
                "fields": fields,
                "output_format": "docx",
            },
            api,
        )
    )
    assert result == output
    assert len(api.requests) == 1
    method, url, kwargs = api.requests[0]
    assert method == "POST" and url.endswith("/forms/payment-request/generate/")
    assert kwargs["json_data"] == {
        "version": "2026-10-28.1",
        "format": "docx",
        "fields": fields,
    }


def test_sdk_rejects_official_form_generation_and_unsafe_ids():
    api = FakeApi({})
    for form_id in ["upl-1", "pit-11", "zus-pel", "../companies", "unknown"]:
        result = call_tool(
            "generate_polish_document",
            {"form_id": form_id, "version": "v1", "fields": {}},
            api,
        )
        assert result.is_error
    assert not api.requests


@pytest.mark.parametrize("form_id", ["annual-leave-request", "payment-receipt"])
def test_new_generators_are_callable_through_the_real_mcp_schema(form_id):
    api = FakeApi({"status": "draft", "formId": form_id}, company_id=None)
    call_tool("get_polish_form", {"form_id": form_id}, api)
    result = call_tool(
        "generate_polish_document",
        {"form_id": form_id, "version": "2026-10-29.1", "fields": {"place": "Synthetic Test"}},
        api,
    )
    assert not result.is_error
    assert structured(result)["formId"] == form_id
    assert len(api.requests) == 2
    assert api.requests[-1][1].endswith(f"/forms/{form_id}/generate/")


@pytest.mark.parametrize(
    "form_id",
    [
        "pit-2",
        "pit-11",
        "pit-28",
        "pit-36",
        "pit-36l",
        "pit-37",
        "pit-4r",
        "pit-8ar",
        "vat-z",
        "vat-26",
        "ord-in",
        "nip-8",
        "zus-zua",
        "zus-zza",
        "zus-zwua",
        "zus-zcna",
        "zus-rca",
        "zus-pel",
    ],
)
def test_new_official_forms_can_be_retrieved(form_id):
    api = FakeApi({"id": form_id, "kind": "official"}, company_id=None)
    result = call_tool("get_polish_form", {"form_id": form_id}, api)
    assert not result.is_error
    assert structured(result)["id"] == form_id
    assert api.requests[0][1].endswith(f"/forms/{form_id}/")


def test_annotations_are_truthful_and_api_errors_stay_errors():
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert tools["list_polish_forms"].annotations.read_only_hint
    generate = tools["generate_polish_document"].annotations
    assert (
        not generate.read_only_hint
        and not generate.destructive_hint
        and not generate.idempotent_hint
    )
    result = call_tool(
        "generate_polish_document",
        {"form_id": "payment-request", "version": "old", "fields": {}},
        FakeApi({"error": "Request failed", "status_code": 409}),
    )
    assert result.is_error
