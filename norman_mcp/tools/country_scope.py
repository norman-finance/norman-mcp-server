"""Guard German procedures per request; the public server is shared by companies/countries."""

import json
from functools import wraps
from inspect import cleandoc, signature
from urllib.parse import urljoin

from mcp.server.mcpserver.exceptions import ToolError

from norman_mcp import config

GERMAN_ONLY_MODULES = frozenset(
    {
        "norman_mcp.tools.corporate_tax_registration",
        "norman_mcp.tools.gewerbe_registration",
        "norman_mcp.tools.incorporation",
        "norman_mcp.tools.payroll",
        "norman_mcp.tools.tax_optimizer",
        "norman_mcp.tools.tax_registration",
    }
)

# The German tools of modules that also serve every country.
GERMAN_ONLY_TOOLS = frozenset(
    {
        # The SKR ledger and its year-end close (HGB, E-Bilanz).
        "get_ebilanz_positions",
        "list_ledger_journal",
        "list_ledger_account_balances",
        "get_ledger_account",
        "list_ledger_open_items",
        "get_ledger_profit_and_loss",
        "get_ledger_balance_sheet",
        "create_manual_ledger_entry",
        "get_manual_ledger_entry",
        "reverse_manual_ledger_entry",
        "update_manual_ledger_entry",
        "bulk_set_ledger_payment_account",
        "list_annual_closes",
        "create_annual_close",
        "get_annual_close",
        "create_annual_close_entry",
        "get_annual_close_workbook",
        # DATEV: the migration from it, the SKR03/SKR04 switch and catalog, the export.
        "get_accounting_setup",
        "prepare_accounting_cutover_accounts",
        "analyze_accounting_cutover_documents",
        "preview_accounting_cutover",
        "apply_accounting_cutover",
        "switch_account_framework",
        "search_skr_by_code",
        "suggest_skr_category",
        "trigger_datev_export",
        "validate_ledger_datev_export",
        # ELSTER and the Finanzamt.
        "generate_finanzamt_preview",
        "get_filed_report_changes",
        "submit_tax_report",
        "validate_tax_number",
        "list_tax_states",
        # SEPA bill payment.
        "list_payment_accounts",
        "pay_bill",
        # A German open booking paid another way.
        "record_booking_payment",
    }
)


# German-only tools a Polish company may call too: the accounting migration serves a PL_FULL sp. z o.o. for its
# opening balance from the previous books' trial balance (the API's polish_opening).
ALSO_POLISH = frozenset(
    {
        "get_accounting_setup",
        "analyze_accounting_cutover_documents",
        "preview_accounting_cutover",
        "apply_accounting_cutover",
    }
)
GERMANY_AND_POLAND_NOTE = "Germany (DATEV) and Poland (sp. z o.o., PL_FULL opening balance)."

# Opens every German-only tool's description. The shared server lists them for a Polish company as
# well, so the model reads plainly that they are not its tools before a call is refused.
GERMANY_ONLY_NOTE = "Germany only."


class CountryScopedTools:
    """Registration facade. Check the active company at invocation, never server startup."""

    def __init__(self, server):
        self.server = server

    def tool(self, *args, **kwargs):
        def register(fn):
            if fn.__name__ not in GERMAN_ONLY_TOOLS and fn.__module__ not in GERMAN_ONLY_MODULES:
                return self.server.tool(*args, **kwargs)(fn)
            call_signature = signature(fn, eval_str=True)

            @wraps(fn)
            async def guarded(*call_args, **call_kwargs):
                bound = call_signature.bind(*call_args, **call_kwargs)
                ctx = bound.arguments["ctx"]
                api = ctx.request_context.lifespan_context["api"]
                company_id = api.company_id
                if not company_id:
                    raise ToolError(json.dumps({"error": "No company available. Please authenticate first."}))
                company = await api.arequest("GET", urljoin(config.api_base_url, f"api/v1/companies/{company_id}/"))
                if not isinstance(company, dict) or company.get("error"):
                    raise ToolError(
                        json.dumps(company if isinstance(company, dict) else {"error": "Company unavailable."})
                    )
                countries = ("DE", "PL") if fn.__name__ in ALSO_POLISH else ("DE",)
                if company.get("country") not in countries:
                    raise ToolError(
                        json.dumps(
                            {
                                "error": "This tool requires a German company. Use the Polish bookkeeping/report tools for PL.",
                                "code": "german_company_required",
                            }
                        )
                    )
                return await fn(*call_args, **call_kwargs)

            guarded.__signature__ = call_signature
            guarded.__annotations__ = {k: v.annotation for k, v in call_signature.parameters.items()}
            guarded.__annotations__["return"] = call_signature.return_annotation
            description = kwargs.get("description") or cleandoc(fn.__doc__ or "")
            note = GERMANY_AND_POLAND_NOTE if fn.__name__ in ALSO_POLISH else GERMANY_ONLY_NOTE
            labelled = {**kwargs, "description": f"{note} {description}".strip()}
            return self.server.tool(*args, **labelled)(guarded)

        return register
