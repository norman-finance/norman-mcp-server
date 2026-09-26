"""The compliance tools must read the company endpoint's real field names.

`GET /api/v1/companies/{id}/` serializes `Company.tax_number` / `vat_number`,
which the camelCase renderer emits as `taxNumber` / `vatNumber`. The tools read
`taxId` / `vatId`, which the endpoint never returns, so every company was
reported as missing both registrations and the compliance report raised
"Steuernummer fehlt" action items against companies that have one on file.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from norman_mcp.tools.tax_advisor import register_tax_advisor_tools

COMPANY_PAYLOAD = {
    "name": "Mafumo Capital Solutions GmbH",
    "accountType": 4,
    "taxState": "hessen",
    "taxNumber": "020/239/03333",
    "vatNumber": "DE462330531",
}


class _Recorder:
    """Collects the tools a register_*_tools call defines."""

    def __init__(self):
        self.tools = {}

    def tool(self, *_args, **_kwargs):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _context(api):
    return SimpleNamespace(
        request_context=SimpleNamespace(lifespan_context={"api": api}),
    )


def _api_returning(company: dict) -> MagicMock:
    api = MagicMock()

    def _request(_method, url, *_args, **_kwargs):
        if "/companies/" in url and url.rstrip("/").endswith("d93468ea"):
            return company
        if "/companies/" in url:
            return company
        return {"results": []}

    api._make_request.side_effect = _request
    api.arequest = AsyncMock(side_effect=_request)
    return api


@pytest.fixture
def tools():
    recorder = _Recorder()
    register_tax_advisor_tools(recorder)
    return recorder.tools


@pytest.mark.asyncio
async def test_compliance_reads_the_stored_registrations(tools):
    api = _api_returning(COMPANY_PAYLOAD)

    result = await tools["get_tax_compliance_status"](_context(api), company_id="d93468ea")

    registration = result["registration"]
    assert registration["taxId"] == "020/239/03333"
    assert registration["vatId"] == "DE462330531"
    assert registration["hasTaxId"] is True
    assert registration["hasVatId"] is True
    assert not [item for item in result["actionItems"] if "missing" in item]


@pytest.mark.asyncio
async def test_compliance_still_flags_a_company_without_registrations(tools):
    api = _api_returning({**COMPANY_PAYLOAD, "taxNumber": "", "vatNumber": None})

    result = await tools["get_tax_compliance_status"](_context(api), company_id="d93468ea")

    assert result["registration"]["hasTaxId"] is False
    assert result["registration"]["hasVatId"] is False
    assert len([item for item in result["actionItems"] if "missing" in item]) == 2


@pytest.mark.asyncio
async def test_client_overview_reports_the_stored_registrations(tools):
    api = _api_returning(COMPANY_PAYLOAD)

    result = await tools["get_client_overview"](_context(api), company_id="d93468ea")

    assert result["company"]["taxId"] == "020/239/03333"
    assert result["company"]["vatId"] == "DE462330531"
