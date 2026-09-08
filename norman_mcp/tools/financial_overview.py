"""One bounded read combines existing, company-scoped financial aggregates."""

import asyncio
from datetime import date, datetime, timezone
from typing import Any, Optional
from urllib.parse import urljoin

from mcp.types import ToolAnnotations

from norman_mcp import config
from norman_mcp.context import Context


def register_financial_overview_tools(mcp):
    @mcp.tool(
        title="Get Financial Overview",
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
    )
    async def get_financial_overview(
        ctx: Context,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict[str, Any]:
        """Get a financial overview in one call: company, current balances, period revenue/costs/profit,
        current tax estimates and next VAT period. Independent reads run concurrently.
        Defaults to the current calendar year to today (UTC). Supply BOTH dates for another period.
        Uses the same pre-aggregated BWA as Insights, not a sample of transaction rows.
        Keep the period/currency and each section's accounting basis distinct. Missing sections are
        explicitly unavailable, never zero. This overview is not a reconciliation or final tax assessment.
        """
        if bool(date_from) != bool(date_to):
            return {"error": "Supply both date_from and date_to."}
        today = datetime.now(timezone.utc).date()
        try:
            start = date.fromisoformat(date_from) if date_from else today.replace(month=1, day=1)
            end = date.fromisoformat(date_to) if date_to else today
        except (TypeError, ValueError):
            return {"error": "Dates must use YYYY-MM-DD."}
        if start > end or (end - start).days >= 366:
            return {"error": "Choose an ordered period of at most 366 days."}
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        base = f"api/v1/companies/{company_id}/"
        sections = {
            "company": ("", None, "company profile"),
            "balance": ("balance/", None, "current bank balances by currency; not period profit"),
            "profit_and_loss": (
                "accounting/insights/bwa/",
                {
                    "date_from": start.isoformat(),
                    "date_to": end.isoformat(),
                    "period_type": (
                        "month" if (start.year, start.month) == (end.year, end.month) else "year"
                    ),
                },
                "Insights BWA aggregates for the requested dates; preliminary accounting result",
            ),
            "tax_estimates": (
                "company-tax-statistic/",
                None,
                "current tax estimates; not restricted to the requested dates",
            ),
            "next_vat": (
                "vat-next-report-amount/",
                None,
                "next VAT reporting period, as returned by the source",
            ),
        }

        async def read(path, params, basis):
            try:
                data = await api.arequest(
                    "GET", urljoin(config.api_base_url, base + path), params=params
                )
            except Exception:
                return {"status": "unavailable", "basis": basis}
            if not isinstance(data, dict) or not data or data.get("error") or data.get("errors"):
                return {"status": "unavailable", "basis": basis}
            if not path:
                data = {
                    key: value
                    for key, value in data.items()
                    if key
                    in {
                        "publicId",
                        "public_id",
                        "name",
                        "currency",
                        "country",
                        "isSme",
                        "is_sme",
                        "bookkeepingType",
                    }
                }
            if path == "accounting/insights/bwa/" and isinstance(data.get("lines"), dict):
                # The summary needs line totals, not every mapped category and its children.
                data = {
                    **data,
                    "lines": {
                        key: {field: value for field, value in line.items() if field != "children"}
                        for key, line in data["lines"].items()
                        if isinstance(line, dict)
                    },
                }
            return {"status": "available", "basis": basis, "data": data}

        results = await asyncio.gather(*(read(*spec) for spec in sections.values()))
        return {
            "company_id": str(company_id),
            "period": {"from": start.isoformat(), "to": end.isoformat()},
            "as_of": datetime.now(timezone.utc).isoformat(),
            "partial": any(result["status"] != "available" for result in results),
            "sections": dict(zip(sections, results)),
        }
