import logging
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
from pydantic import Field

from mcp.types import ToolAnnotations
from norman_mcp.context import Context
from norman_mcp import config
from norman_mcp.tools.results import is_failure
from norman_mcp.tools.missing_documents import category_name, missing_document_transactions, needs_document
from norman_mcp.tools.taxes import reports_url as reports_url_for

logger = logging.getLogger(__name__)

# Report.ReportStatus values that mean "filed", as the MCP apps read them. The
# tools used to compare against "draft"/"submitted", which the API never sends,
# so every report counted as neither pending nor filed.
_FILED_REPORT_STATUSES = {"SUBMIT", "SUBMIT_AND_PAID", "SUBMITTED", "FILED"}
# Enough for years of monthly returns in one request (the API default is 20).
_OVERVIEW_PAGE_SIZE = 200


def _is_filed(report: Dict[str, Any]) -> bool:
    return str(report.get("status") or "").upper() in _FILED_REPORT_STATUSES


def _report_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    """The report fields that matter here, under the names the API really uses."""
    return {
        "id": report.get("pk") or report.get("publicId"),
        "type": report.get("type"),
        "dateFrom": report.get("dateFrom"),
        "dateTo": report.get("dateTo"),
        "status": report.get("status"),
        "dueDate": report.get("dateDue"),
        "amount": report.get("total"),
    }


def register_tax_advisor_tools(mcp):
    """Register tax-advisor-specific tools with the MCP server."""

    @mcp.tool(
        title="Get Client Overview",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_client_overview(
        ctx: Context,
        company_id: str = Field(description="Public ID of the client company to get overview for"),
    ) -> Dict[str, Any]:
        """
        Get an aggregated financial health snapshot for a client company.
        Combines company details, balance, transaction stats, missing receipts,
        outstanding invoices, and tax report status into a single overview.
        Designed for tax advisors managing multiple client companies.

        Returns:
            A structured overview with company info, financial summary,
            document completeness, and tax compliance status.
        """
        api = ctx.request_context.lifespan_context["api"]

        overview: Dict[str, Any] = {"companyId": company_id}

        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        try:
            company = await api.arequest("GET", company_url)
            if is_failure(company):
                # Read from an error result, every field below would be None.
                overview["company"] = {"error": company["error"]}
            else:
                overview["company"] = {
                    "name": company.get("name"),
                    "accountType": company.get("accountType"),
                    "isSme": company.get("isSme"),
                    "chartOfAccounts": company.get("chartOfAccounts"),
                    "taxState": company.get("taxState"),
                    # the company endpoint serializes these as taxNumber/vatNumber
                    "vatId": company.get("vatNumber"),
                    "taxId": company.get("taxNumber"),
                }
        except Exception as e:
            logger.warning("Could not fetch company details: %s", e)
            overview["company"] = {"error": str(e)}

        balance_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/balance/")
        try:
            overview["balance"] = await api.arequest("GET", balance_url)
        except Exception as e:
            logger.warning("Could not fetch balance: %s", e)
            overview["balance"] = {"error": str(e)}

        stats_url = urljoin(
            config.api_base_url,
            f"api/v1/tax-advisor/clients/{company_id}/stats/",
        )
        try:
            overview["transactionStats"] = await api.arequest("GET", stats_url)
        except Exception as e:
            logger.warning("Could not fetch transaction stats: %s", e)
            overview["transactionStats"] = {"error": str(e)}

        tax_stats_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/company-tax-statistic/",
        )
        try:
            overview["taxStatistics"] = await api.arequest("GET", tax_stats_url)
        except Exception as e:
            logger.warning("Could not fetch tax statistics: %s", e)
            overview["taxStatistics"] = {"error": str(e)}

        # The client company's own reports: the unscoped taxes/reports/ route
        # answers for the user's oldest company instead.
        reports_url = reports_url_for(company_id)
        try:
            reports = await api.arequest("GET", reports_url, params={"page_size": _OVERVIEW_PAGE_SIZE})
            report_list = reports.get("results", reports) if isinstance(reports, dict) else reports
            if isinstance(report_list, list):
                pending = [r for r in report_list if not _is_filed(r)]
                submitted = [r for r in report_list if _is_filed(r)]
                overview["taxReports"] = {
                    "total": len(report_list),
                    "pending": len(pending),
                    "submitted": len(submitted),
                    "pendingReports": [_report_summary(r) for r in pending[:10]],
                }
            else:
                overview["taxReports"] = reports
        except Exception as e:
            logger.warning("Could not fetch tax reports: %s", e)
            overview["taxReports"] = {"error": str(e)}

        invoices_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/invoices/",
        )
        try:
            inv_resp = await api.arequest(
                "GET", invoices_url, params={"status": "sent", "page_size": _OVERVIEW_PAGE_SIZE}
            )
            inv_list = inv_resp.get("results", inv_resp) if isinstance(inv_resp, dict) else inv_resp
            if isinstance(inv_list, list):
                overview["outstandingInvoices"] = {
                    "count": len(inv_list),
                    # The invoice total is fullCost; totalGross does not exist.
                    "totalAmount": sum(float(i.get("fullCost") or 0) for i in inv_list),
                }
            else:
                overview["outstandingInvoices"] = inv_resp
        except Exception as e:
            logger.warning("Could not fetch invoices: %s", e)
            overview["outstandingInvoices"] = {"error": str(e)}

        return overview

    @mcp.tool(
        title="Get Missing Documents Summary",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_missing_documents_summary(
        ctx: Context,
        company_id: str = Field(description="Public ID of the client company"),
        date_from: Optional[str] = Field(default=None, description="Start date YYYY-MM-DD"),
        date_to: Optional[str] = Field(default=None, description="End date YYYY-MM-DD"),
    ) -> Dict[str, Any]:
        """
        Check the selected company; select company_id first when switching clients.

        List all transactions without receipts for a client company,
        grouped by month and category with amounts.
        Useful for tax advisors to know what documents to request from the client.

        Returns:
            Summary with total missing count, grouped by month, and a flat list
            of the top missing transactions ordered by amount.
        """
        api = ctx.request_context.lifespan_context["api"]

        results = await missing_document_transactions(api, company_id, date_from, date_to)
        if isinstance(results, dict):
            return results
        missing = [tx for tx in results if needs_document(tx)]

        by_month: Dict[str, list] = {}
        for tx in missing:
            date_str = str(tx.get("valueDate", tx.get("value_date", "")))
            month_key = date_str[:7] if len(date_str) >= 7 else "unknown"
            by_month.setdefault(month_key, []).append(tx)

        monthly_summary = []
        for month, txns in sorted(by_month.items(), reverse=True):
            total_amount = sum(abs(float(tx.get("amount", 0))) for tx in txns)
            monthly_summary.append({
                "month": month,
                "count": len(txns),
                "totalAmount": round(total_amount, 2),
                "transactions": [
                    {
                        "id": tx.get("publicId", tx.get("public_id")),
                        "description": tx.get("description", ""),
                        "amount": tx.get("amount"),
                        "date": tx.get("valueDate", tx.get("value_date")),
                        "category": category_name(tx),
                    }
                    for tx in sorted(txns, key=lambda t: abs(float(t.get("amount", 0))), reverse=True)
                ],
            })

        top_missing = sorted(missing, key=lambda t: abs(float(t.get("amount", 0))), reverse=True)[:20]

        return {
            "companyId": company_id,
            "totalMissing": len(missing),
            "totalTransactions": len(results),
            "byMonth": monthly_summary,
            "topMissingByAmount": [
                {
                    "id": tx.get("publicId", tx.get("public_id")),
                    "description": tx.get("description", ""),
                    "amount": tx.get("amount"),
                    "date": tx.get("valueDate", tx.get("value_date")),
                    "category": category_name(tx),
                }
                for tx in top_missing
            ],
        }

    @mcp.tool(
        title="Get Tax Compliance Status",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_tax_compliance_status(
        ctx: Context,
        company_id: str = Field(description="Public ID of the client company"),
    ) -> Dict[str, Any]:
        """
        Check the tax compliance status for a client company.
        Identifies which tax reports are due, overdue, or unfiled,
        and flags any validation issues.

        Returns:
            Compliance summary with report status breakdown and action items.
        """
        api = ctx.request_context.lifespan_context["api"]

        result: Dict[str, Any] = {"companyId": company_id}

        reports_url = reports_url_for(company_id)
        try:
            reports_resp = await api.arequest("GET", reports_url, params={"page_size": _OVERVIEW_PAGE_SIZE})
            report_list = reports_resp.get("results", reports_resp) if isinstance(reports_resp, dict) else reports_resp

            if isinstance(report_list, list):
                draft = [_report_summary(r) for r in report_list if not _is_filed(r)]
                submitted = [_report_summary(r) for r in report_list if _is_filed(r)]

                result["reports"] = {
                    "total": len(report_list),
                    "unfiled": len(draft),
                    "filed": len(submitted),
                    "unfiledReports": draft,
                }
            else:
                result["reports"] = reports_resp
        except Exception as e:
            result["reports"] = {"error": str(e)}

        tax_settings_url = urljoin(config.api_base_url, "api/v1/taxes/tax-settings/")
        try:
            result["taxSettings"] = await api.arequest("GET", tax_settings_url)
        except Exception as e:
            result["taxSettings"] = {"error": str(e)}

        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        try:
            company = await api.arequest("GET", company_url)
            if is_failure(company):
                # A failed lookup must not read as "no tax number on file":
                # that raised false "missing registration" action items.
                result["registration"] = {"error": company["error"]}
            else:
                # The company endpoint serializes Company.tax_number/vat_number as
                # taxNumber/vatNumber. Reading taxId/vatId always yielded None, so
                # every company was reported as missing both registrations.
                tax_number = company.get("taxNumber")
                vat_number = company.get("vatNumber")
                result["registration"] = {
                    "taxId": tax_number,
                    "vatId": vat_number,
                    "taxState": company.get("taxState"),
                    "hasTaxId": bool(tax_number),
                    "hasVatId": bool(vat_number),
                }
        except Exception as e:
            result["registration"] = {"error": str(e)}

        action_items = []
        reg = result.get("registration", {})
        if isinstance(reg, dict) and not reg.get("error"):
            if not reg.get("hasTaxId"):
                action_items.append("Tax ID (Steuernummer) is missing — register with Finanzamt")
            if not reg.get("hasVatId"):
                action_items.append("VAT ID (USt-IdNr.) is missing — apply if EU trade is planned")

        reports_info = result.get("reports", {})
        if isinstance(reports_info, dict) and reports_info.get("unfiled", 0) > 0:
            action_items.append(f"{reports_info['unfiled']} tax report(s) are unfiled and need attention")

        result["actionItems"] = action_items

        return result

    @mcp.tool(
        title="Ping Client for Documents",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def ping_client_for_documents(
        ctx: Context,
        company_id: str = Field(description="Public ID of the client company"),
        transaction_ids: List[str] = Field(description="List of transaction public IDs to ping the client about"),
    ) -> Dict[str, Any]:
        """
        Send document request reminders to a client for multiple transactions at once.
        Each transaction triggers an email to the company owner asking them to upload
        the missing receipt or invoice.

        Returns:
            Summary of which pings succeeded and which failed.
        """
        api = ctx.request_context.lifespan_context["api"]

        succeeded = []
        failed = []

        for tx_id in transaction_ids:
            ping_url = urljoin(
                config.api_base_url,
                f"api/v1/tax-advisor/clients/{company_id}/ping/{tx_id}/",
            )
            try:
                resp = await api.arequest("POST", ping_url)
            except Exception as e:
                failed.append({"transactionId": tx_id, "error": str(e)})
                continue
            # The client reports HTTP failures as an error result rather than
            # raising, so check it: a failed ping used to be counted as sent.
            if is_failure(resp):
                failed.append({"transactionId": tx_id, **resp})
            else:
                detail = resp.get("detail", "Sent") if isinstance(resp, dict) else "Sent"
                succeeded.append({"transactionId": tx_id, "detail": detail})

        return {
            "companyId": company_id,
            "totalRequested": len(transaction_ids),
            "succeeded": len(succeeded),
            "failed": len(failed),
            "details": {
                "succeeded": succeeded,
                "failed": failed,
            },
        }

    @mcp.tool(
        title="List Tax Advisor Clients",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_tax_advisor_clients(
        ctx: Context,
    ) -> Dict[str, Any]:
        """
        List all client companies managed by the authenticated tax advisor.
        Each entry includes the company ID, name, account type, transaction count,
        and number of transactions missing documents.

        Use the returned company IDs with switch_company to change the active company,
        or pass them to other tax advisor tools like get_client_overview.
        """
        api = ctx.request_context.lifespan_context["api"]

        clients_url = urljoin(config.api_base_url, "api/v1/tax-advisor/clients/")

        try:
            clients = await api.arequest("GET", clients_url)
        except Exception as e:
            return {"error": str(e)}

        client_list = clients if isinstance(clients, list) else clients.get("results", clients)

        return {
            "count": len(client_list) if isinstance(client_list, list) else 0,
            "clients": client_list,
            "activeCompanyId": api.company_id,
        }

    @mcp.tool(
        title="Switch Active Company",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def switch_company(
        ctx: Context,
        company_id: str = Field(description="Public ID of the company to switch to. Use list_tax_advisor_clients to see available companies."),
    ) -> Dict[str, Any]:
        """
        Switch the active company context. All subsequent tool calls will operate
        on the selected company. Tax advisors can use this to switch between
        client companies; regular users can switch if they own multiple companies.
        """
        api = ctx.request_context.lifespan_context["api"]
        previous_id = api.company_id

        # Confirm the caller can actually reach this company BEFORE recording the
        # selection. The endpoint is scoped by the requesting user server-side
        # (Company.objects.for_user), so a company they have no access to comes
        # back as an error. Persisting first would let a caller pin an arbitrary
        # company id onto their own session, and that id is sent as the `company`
        # field when creating transactions.
        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        try:
            company = await api.arequest("GET", company_url)
        except Exception as e:
            return {
                "previousCompanyId": previous_id,
                "error": f"Could not switch to {company_id}: {e}",
            }

        if not isinstance(company, dict) or company.get("error"):
            detail = company.get("error") if isinstance(company, dict) else "unexpected response"
            return {
                "previousCompanyId": previous_id,
                "error": f"Could not switch to {company_id}: {detail}",
            }

        api.set_company(company_id)

        # Remember the choice server-side as well. The per-token selection above is lost
        # when the MCP token is refreshed (~24h); the API's last-active company is not,
        # and it is what a request without an X-Company-Id header resolves to.
        activate_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/activate/")
        try:
            await api.arequest("POST", activate_url)
        except Exception as e:  # noqa: BLE001 - best effort, the switch itself already happened
            logger.warning(f"Could not mark {company_id} as the last active company: {e}")

        return {
            "previousCompanyId": previous_id,
            "activeCompanyId": company_id,
            "company": {
                "name": company.get("name"),
                "accountType": company.get("accountType"),
                "isSme": company.get("isSme"),
            },
        }
