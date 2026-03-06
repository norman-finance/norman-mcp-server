import logging
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
from pydantic import Field

from mcp.types import ToolAnnotations
from norman_mcp.context import Context
from norman_mcp import config

logger = logging.getLogger(__name__)


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
            company = api._make_request("GET", company_url)
            overview["company"] = {
                "name": company.get("name"),
                "accountType": company.get("accountType"),
                "isSme": company.get("isSme"),
                "chartOfAccounts": company.get("chartOfAccounts"),
                "taxState": company.get("taxState"),
                "vatId": company.get("vatId"),
                "taxId": company.get("taxId"),
            }
        except Exception as e:
            logger.warning("Could not fetch company details: %s", e)
            overview["company"] = {"error": str(e)}

        balance_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/balance/")
        try:
            overview["balance"] = api._make_request("GET", balance_url)
        except Exception as e:
            logger.warning("Could not fetch balance: %s", e)
            overview["balance"] = {"error": str(e)}

        stats_url = urljoin(
            config.api_base_url,
            f"api/v1/tax-advisor/clients/{company_id}/stats/",
        )
        try:
            overview["transactionStats"] = api._make_request("GET", stats_url)
        except Exception as e:
            logger.warning("Could not fetch transaction stats: %s", e)
            overview["transactionStats"] = {"error": str(e)}

        tax_stats_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/company-tax-statistic/",
        )
        try:
            overview["taxStatistics"] = api._make_request("GET", tax_stats_url)
        except Exception as e:
            logger.warning("Could not fetch tax statistics: %s", e)
            overview["taxStatistics"] = {"error": str(e)}

        reports_url = urljoin(config.api_base_url, "api/v1/taxes/reports/")
        try:
            reports = api._make_request("GET", reports_url)
            report_list = reports.get("results", reports) if isinstance(reports, dict) else reports
            if isinstance(report_list, list):
                pending = [r for r in report_list if r.get("status") in ("draft", "DRAFT", "pending", "PENDING")]
                submitted = [r for r in report_list if r.get("status") in ("submitted", "SUBMITTED", "filed", "FILED")]
                overview["taxReports"] = {
                    "total": len(report_list),
                    "pending": len(pending),
                    "submitted": len(submitted),
                    "pendingReports": [
                        {"id": r.get("publicId"), "type": r.get("type"), "period": r.get("period"), "status": r.get("status")}
                        for r in pending[:10]
                    ],
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
            inv_resp = api._make_request("GET", invoices_url, params={"status": "sent"})
            inv_list = inv_resp.get("results", inv_resp) if isinstance(inv_resp, dict) else inv_resp
            if isinstance(inv_list, list):
                overview["outstandingInvoices"] = {
                    "count": len(inv_list),
                    "totalAmount": sum(float(i.get("totalGross", 0)) for i in inv_list),
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
        List all transactions without receipts for a client company,
        grouped by month and category with amounts.
        Useful for tax advisors to know what documents to request from the client.

        Returns:
            Summary with total missing count, grouped by month, and a flat list
            of the top missing transactions ordered by amount.
        """
        api = ctx.request_context.lifespan_context["api"]

        txns_url = urljoin(
            config.api_base_url,
            f"api/v1/tax-advisor/clients/{company_id}/transactions/",
        )
        params: Dict[str, Any] = {"page_size": 200}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to

        try:
            resp = api._make_request("GET", txns_url, params=params)
        except Exception as e:
            return {"error": str(e)}

        results = resp.get("results", []) if isinstance(resp, dict) else resp
        missing = [tx for tx in results if not tx.get("hasAttachment", tx.get("has_attachment", False))]

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
                        "category": tx.get("categoryName", tx.get("category_name")),
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
                    "category": tx.get("categoryName", tx.get("category_name")),
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

        reports_url = urljoin(config.api_base_url, "api/v1/taxes/reports/")
        try:
            reports_resp = api._make_request("GET", reports_url)
            report_list = reports_resp.get("results", reports_resp) if isinstance(reports_resp, dict) else reports_resp

            if isinstance(report_list, list):
                draft = []
                submitted = []
                for r in report_list:
                    st = (r.get("status") or "").lower()
                    entry = {
                        "id": r.get("publicId"),
                        "type": r.get("type"),
                        "period": r.get("period"),
                        "status": r.get("status"),
                        "dueDate": r.get("dueDate"),
                        "amount": r.get("amount"),
                    }
                    if st in ("draft", "pending"):
                        draft.append(entry)
                    elif st in ("submitted", "filed"):
                        submitted.append(entry)

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
            result["taxSettings"] = api._make_request("GET", tax_settings_url)
        except Exception as e:
            result["taxSettings"] = {"error": str(e)}

        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        try:
            company = api._make_request("GET", company_url)
            result["registration"] = {
                "taxId": company.get("taxId"),
                "vatId": company.get("vatId"),
                "taxState": company.get("taxState"),
                "hasTaxId": bool(company.get("taxId")),
                "hasVatId": bool(company.get("vatId")),
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
            destructiveHint=False,
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
                resp = api._make_request("POST", ping_url)
                succeeded.append({"transactionId": tx_id, "detail": resp.get("detail", "Sent")})
            except Exception as e:
                failed.append({"transactionId": tx_id, "error": str(e)})

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
            clients = api._make_request("GET", clients_url)
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

        api.set_company(company_id)

        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        try:
            company = api._make_request("GET", company_url)
            return {
                "previousCompanyId": previous_id,
                "activeCompanyId": company_id,
                "company": {
                    "name": company.get("name"),
                    "accountType": company.get("accountType"),
                    "isSme": company.get("isSme"),
                },
            }
        except Exception as e:
            return {
                "previousCompanyId": previous_id,
                "activeCompanyId": company_id,
                "warning": f"Switched, but could not fetch company details: {e}",
            }
