import logging
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
from pydantic import Field

from mcp.types import ToolAnnotations
from norman_mcp.context import Context
from norman_mcp import config
from norman_mcp.tools.taxes import reports_url as company_reports_url
from norman_mcp.tools.missing_documents import (
    category_name,
    documents_without_booking,
    missing_document_transactions,
    needs_document,
)
from norman_mcp.tools.advisor_signatures import register_advisor_signature_tools

logger = logging.getLogger(__name__)


def register_tax_advisor_tools(mcp):
    """Register tax-advisor-specific tools with the MCP server."""

    register_advisor_signature_tools(mcp)

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
                "country": company.get("country"),
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

        reports_endpoint = company_reports_url(company_id)
        try:
            reports = api._make_request("GET", reports_endpoint)
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
        Check the selected company; select company_id first when switching clients.

        List all transactions without receipts for a client company,
        grouped by month and category with amounts, and count the client's
        receipts and invoices that no booking holds yet, by month.
        Useful for tax advisors to know what documents to request from the client
        and which periods miss bookings.

        Returns:
            Summary with total missing count, grouped by month, a flat list
            of the top missing transactions ordered by amount, and the documents
            without a booking by month.
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
            "documentsWithoutBooking": await documents_without_booking(api, company_id, date_from, date_to),
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

        reports_endpoint = company_reports_url(company_id)
        try:
            reports_resp = api._make_request("GET", reports_endpoint)
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
            result["taxSettings"] = api._make_request("GET", tax_settings_url, company_id=company_id)
        except Exception as e:
            result["taxSettings"] = {"error": str(e)}

        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        try:
            company = api._make_request("GET", company_url)
            # The company endpoint serializes Company.tax_number/vat_number as
            # taxNumber/vatNumber. Reading taxId/vatId always yielded None, so
            # every company was reported as missing both registrations.
            tax_number = company.get("taxNumber")
            vat_number = company.get("vatNumber")
            result["registration"] = {
                # A Polish client's registration is named in Polish terms, never the Finanzamt's.
                "country": company.get("country"),
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
                action_items.append(
                    "Tax ID (NIP) is missing"
                    if reg.get("country") == "PL"
                    else "Tax ID (Steuernummer) is missing — register with Finanzamt"
                )
            if not reg.get("hasVatId"):
                action_items.append(
                    "EU VAT number (PL + NIP, VAT-UE registration) is missing — needed only for EU trade"
                    if reg.get("country") == "PL"
                    else "VAT ID (USt-IdNr.) is missing — apply if EU trade is planned"
                )

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
        title="List Clients for a Period",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_clients_for_period(
        ctx: Context,
        date_from: str = Field(description="First day of the period, YYYY-MM-DD: a month, a quarter or a year"),
        date_to: str = Field(description="Last day of the period, YYYY-MM-DD"),
    ) -> Dict[str, Any]:
        """
        Each client of the tax advisor in one period, the way the advisor's client list shows it.
        Per client: open bookings (not finalized; an unpaid booking waits for its payment and is left
        out), bookings without a document, documents without a booking of the period (by their
        date, else their upload date), the newest DATEV file the advisor has of exactly this period
        with the number of changes since it (file), else the newest file of an earlier period
        (earlierFile), and the VAT return of the period: the UStVA or the Polish JPK_V7, due with its
        earliest due date or filed with its newest filing date. A Kleinunternehmer or a VAT-exempt
        company has one only for a period with tax, such as reverse charge; otherwise none, as
        for a yearly filer.

        close says whether the advisor closed the period: closed, closedAt, by, changes (changes
        since the close), period (the client's VAT period that closes from here, null if the
        picked period spans several) and canChange. year comes only when the picked period is a
        calendar year: closed and what it still lacks (missing). A self-employed year is closed
        when its last period is closed and the EUeR and, where due, the annual VAT return are
        filed; a GmbH's or UG's when its annual close is locked.

        status is one of: changed (changed since the DATEV file or since the close),
        missing_documents, in_progress, ready (ready to hand over), handed_over (nothing open and
        nothing changed since the file), period_closed (the advisor closed the period), closed
        (bookkeeping is not opened for the advisor). Clients that need the advisor come first.
        closedBlocks names the parts of the books the client or the firm has not opened for the
        advisor (bookkeeping, documents, datev, taxes_prepare); their facts are null.
        """
        api = ctx.request_context.lifespan_context["api"]
        url = urljoin(config.api_base_url, "api/v1/tax-advisor/clients/period/")
        try:
            rows = api._make_request("GET", url, params={"date_from": date_from, "date_to": date_to})
        except Exception as e:
            return {"error": str(e)}
        return {"dateFrom": date_from, "dateTo": date_to, "clients": rows}

    @mcp.tool(
        title="Close a Client's Period",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def close_client_period(
        ctx: Context,
        company_id: str = Field(description="Public ID of the client company"),
        date_from: str = Field(description="First day of the client's VAT period, YYYY-MM-DD"),
        date_to: str = Field(description="Last day of the client's VAT period, YYYY-MM-DD"),
    ) -> Dict[str, Any]:
        """
        Close one VAT period of a German client: its month, quarter or year, as close.period of
        list_clients_for_period names it. Norman keeps a record of the bookings and documents the
        period holds now. Closing locks nothing and asks for nothing: open items stay open, the
        client can still change the period and sees nothing of the close, and each later change
        shows to the advisor as a change after the close. Closing again takes a new record.
        A period under a GmbH's or UG's locked annual close does not close here: code year_closed.
        Before you call it, name what is still open in the period and ask the advisor.

        Returns:
            The client's row of list_clients_for_period for this period.
        """
        api = ctx.request_context.lifespan_context["api"]
        url = urljoin(config.api_base_url, f"api/v1/tax-advisor/clients/{company_id}/period/close/")
        try:
            return api._make_request("POST", url, json_data={"date_from": date_from, "date_to": date_to})
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool(
        title="Reopen a Client's Period",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def reopen_client_period(
        ctx: Context,
        company_id: str = Field(description="Public ID of the client company"),
        date_from: str = Field(description="First day of the closed VAT period, YYYY-MM-DD"),
        date_to: str = Field(description="Last day of the closed VAT period, YYYY-MM-DD"),
    ) -> Dict[str, Any]:
        """
        Reopen a VAT period the advisor closed. Ask the advisor first. A GmbH's or UG's annual
        close does not reopen here, and a period under it answers code year_closed.

        Returns:
            The client's row of list_clients_for_period for this period.
        """
        api = ctx.request_context.lifespan_context["api"]
        url = urljoin(config.api_base_url, f"api/v1/tax-advisor/clients/{company_id}/period/reopen/")
        try:
            return api._make_request("POST", url, json_data={"date_from": date_from, "date_to": date_to})
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool(
        title="Get Changes After a Period's Close",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_client_period_close_changes(
        ctx: Context,
        company_id: str = Field(description="Public ID of the client company"),
        date_from: str = Field(description="First day of the period, YYYY-MM-DD"),
        date_to: str = Field(description="Last day of the period, YYYY-MM-DD"),
    ) -> Dict[str, Any]:
        """
        What changed after the advisor closed a client's period: for each closed VAT period in the
        range, the new, changed and removed bookings and the new documents since its close. A new
        booking counts even before it is finalized. The document facts are null while the client's
        documents are closed to the advisor. A period under a locked annual close returns nothing.
        """
        api = ctx.request_context.lifespan_context["api"]
        url = urljoin(config.api_base_url, f"api/v1/tax-advisor/clients/{company_id}/period/close-changes/")
        try:
            periods = api._make_request("GET", url, params={"date_from": date_from, "date_to": date_to})
        except Exception as e:
            return {"error": str(e)}
        return {"companyId": company_id, "periods": periods}

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
        company_id: str = Field(description="Public ID of the company to switch to. Use list_companies to see the companies you can switch to."),
    ) -> Dict[str, Any]:
        """
        Switch the active company context. All subsequent tool calls will operate
        on the selected company. Owners and members of several companies switch
        between them here, and tax advisors between their client companies;
        list_companies returns the ids.
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
            company = api._make_request("GET", company_url)
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
            api._make_request("POST", activate_url)
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
