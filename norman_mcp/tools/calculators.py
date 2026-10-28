"""Public estimates through the website's existing engines, without account credentials."""

import json
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

CALCULATOR_URL = "https://norman.finance/api/calculators"
MAX_REQUEST_BYTES = 16_384
MAX_RESPONSE_BYTES = 262_144
CalculatorName = Literal[
    "pl_vat",
    "pl_jdg_annual",
    "pl_zus_monthly",
    "pl_depreciation",
    "pl_spolka_dividend",
    "pl_sole_shareholder_zus",
    "pl_employer_cost",
    "de_vat",
    "de_income_tax",
    "de_self_employed",
    "de_company_tax",
    "de_trade_tax",
    "de_depreciation",
]
READ = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


async def _request(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    # Never use the company API client here: its token and company header must not reach the website.
    try:
        async with (
            httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client,
            client.stream(method, CALCULATOR_URL, json=payload) as response,
        ):
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ToolError(
                        "Calculator service response is too large. No estimate is available."
                    )
            data = json.loads(body)
            if not response.is_success:
                detail = (
                    data.get("error", "Request failed")
                    if isinstance(data, dict)
                    else "Request failed"
                )
                raise ToolError(
                    f"Calculator service HTTP {response.status_code}: {str(detail)[:500]}"
                )
            if not isinstance(data, dict):
                raise ToolError("Unexpected calculator service response. No estimate is available.")
            return data
    except (httpx.HTTPError, ValueError):
        raise ToolError(
            "Norman calculator service is unavailable. No estimate was calculated; retry later."
        ) from None


async def _catalog() -> dict[str, Any]:
    data = await _request("GET")
    entries = data.get("calculators")
    if not isinstance(entries, list) or not data.get("version"):
        raise ToolError("Calculator catalog is unavailable.")
    known = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("name") not in CalculatorName.__args__:
            continue
        if (
            entry.get("country") != entry["name"][:2].upper()
            or not isinstance(entry.get("inputSchema"), dict)
            or not all(isinstance(entry.get(key), str) for key in ("title", "description"))
        ):
            raise ToolError("Calculator catalog has an invalid schema.")
        known.append(entry)
    return {"version": data["version"], "calculators": known}


async def _get_calculator(name: str) -> dict[str, Any]:
    catalog = await _catalog()
    for entry in catalog["calculators"]:
        if entry["name"] == name:
            return {"catalogVersion": catalog["version"], **entry}
    raise ToolError(
        "This calculator is not available in the current catalog. Do not substitute another country/year."
    )


def _validated_inputs(schema: dict[str, Any], inputs: dict[str, Any]) -> None:
    try:
        encoded = json.dumps(inputs, allow_nan=False)
    except (TypeError, ValueError):
        raise ToolError(
            "Calculator inputs must be finite JSON numbers, booleans and the schema's enums."
        ) from None
    if len(encoded.encode()) > MAX_REQUEST_BYTES:
        raise ToolError("Calculator inputs exceed the request limit.")
    # Decimal arithmetic avoids rejecting valid cents (e.g. 361.13) on binary-float multipleOf checks.
    instance = json.loads(encoded, parse_float=Decimal)
    exact_schema = json.loads(json.dumps(schema), parse_float=Decimal)
    errors = list(Draft202012Validator(exact_schema).iter_errors(instance))
    if errors:
        # Never echo supplied values or send invalid/extra fields to the public calculation endpoint.
        fields = sorted({".".join(map(str, error.absolute_path)) or "inputs" for error in errors})
        raise ToolError(
            "Invalid or missing calculator inputs: "
            + ", ".join(fields)
            + ". Read the current inputSchema.",
        )


def register_calculator_tools(mcp: Any) -> None:
    @mcp.tool(title="Find Norman calculators", annotations=READ)
    async def list_public_calculators(country: Literal["PL", "DE"] | None = None) -> dict[str, Any]:
        """Find calculators for VAT/net/gross, JDG PIT/ZUS, depreciation, salary cost and company taxes.

        Triggers: kalkulator, netto/brutto, amortyzacja, калькулятор, розрахунок, податки, Rechner.
        Public what-if estimates only. For the selected company's actual tax due, use tax-report tools.
        Country is the requested tax jurisdiction, never inferred from the chat language.
        """
        catalog = await _catalog()
        return {
            "version": catalog["version"],
            "calculators": [
                {key: entry[key] for key in ("name", "title", "country", "description")}
                for entry in catalog["calculators"]
                if country is None or entry["country"] == country
            ],
        }

    @mcp.tool(title="Get calculator inputs and scope", annotations=READ)
    async def get_public_calculator(calculator: CalculatorName) -> dict[str, Any]:
        """Read the live inputSchema and applicability before calculating; ask only for missing facts.

        Confirm requested country, year, legal form, tax regime and relief eligibility where required.
        Never invent defaults or assume JDG and sp. z o.o. use the same calculation. Do not pass names,
        NIP/PESEL, tax identifiers, account IDs, documents or whole conversations to calculators.
        """
        return await _get_calculator(calculator)

    @mcp.tool(title="Calculate a public estimate", annotations=READ)
    async def calculate_public_estimate(
        calculator: CalculatorName, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Calculate a what-if estimate with Norman's existing website engine, without reading an account.

        First get_public_calculator. Send only schema fields: numbers, booleans and listed enums.
        Amounts are major units (PLN/EUR), not cents/grosze; rates follow the schema's units.
        Preserve returned country/year/currency, source and assumptions in the answer. This does not
        create a document, change tax settings, prepare/file a return or pay anything. For actual
        company liabilities use list_tax_reports/get_tax_report or get_polish_tax_estimates instead.
        """
        entry = await _get_calculator(calculator)
        _validated_inputs(entry["inputSchema"], inputs)
        result = await _request("POST", {"calculator": calculator, "inputs": inputs})
        source = urlsplit(str(result.get("source", "")))
        expected_currency = "PLN" if entry["country"] == "PL" else "EUR"
        if (
            result.get("kind") != "estimate"
            or result.get("calculator") != calculator
            or result.get("country") != entry["country"]
            or result.get("year") != inputs.get("year")
            or result.get("currency") != expected_currency
            or result.get("amountUnit") != "major"
            or not isinstance(result.get("result"), dict)
            or not isinstance(result.get("assumptions"), list)
            or not result["assumptions"]
            or source.scheme != "https"
            or source.netloc != "norman.finance"
        ):
            raise ToolError(
                "Calculator response does not match the requested scope. Do not use this result."
            )
        return result
