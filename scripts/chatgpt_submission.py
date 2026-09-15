"""Emit review metadata for the isolated ChatGPT endpoint (never include credentials).

Run from the repo with: python -m scripts.chatgpt_submission
The explicit inventory intentionally fails when tools are added without review.
"""

import asyncio
import json

from norman_mcp.chatgpt import create_chatgpt_server
from norman_mcp.server import mcp

# Reviewed effects, including optional modes and backend calls, not guesses from names.
EFFECTS = {
    "list_clients": "Retrieves the company's saved client records without changing them.",
    "get_client": "Retrieves one saved client and its details without changing the record.",
    "create_client": "Creates a client record in the selected company's address book.",
    "update_client": "Updates the selected client's supplied contact and billing fields.",
    "delete_client": "Deletes the selected client record from the company's address book.",
    "list_products": "Retrieves catalog products matching the requested filters without changing invoice lines.",
    "get_product": "Retrieves a catalog product and its invoice usage without modifying it.",
    "create_product": "Creates a reusable product or service in the company catalog.",
    "update_product": "Changes the supplied catalog-product fields without rewriting existing invoices.",
    "archive_product": "Archives a product so it is no longer offered for new invoices, retaining existing invoice lines.",
    "list_vendors": "Retrieves the company's saved supplier records without changing them.",
    "get_vendor": "Retrieves one saved supplier's details without modifying its record.",
    "create_vendor": "Creates a supplier record, including only the supplied business billing details.",
    "update_vendor": "Changes the supplied fields of a saved supplier record.",
    "delete_vendor": "Deletes the selected supplier record.",
    "list_bills": "Retrieves incoming supplier invoices without modifying their status or initiating payments.",
    "get_bill": "Retrieves one incoming bill without modifying it or contacting a bank.",
    "update_bill": "Updates the selected bill's bookkeeping status without starting a payment.",
    "mark_bill_paid": "Records that a bill was paid by changing its bookkeeping status, without moving money.",
    "delete_bill": "Deletes the selected incoming bill record.",
    "cancel_recurring_invoice": "Cancels future generation and scheduled sends for a recurring series while retaining issued invoices.",
    "prepare_invoice_from_contract": "Saves a source contract and extracts an editable proposal without creating or sending an invoice.",
    "create_invoice": "Creates an invoice and can enqueue delivery to the client when automatic sending is requested.",
    "create_recurring_invoice": "Creates a recurring invoice series that can generate and email future invoices when automatic sending is requested.",
    "get_invoice": "Retrieves an invoice and its temporary PDF download link without changing the invoice.",
    "send_invoice": "Sends the selected invoice by email to the specified client and additional recipients.",
    "send_invoice_overdue_reminder": "Sends an overdue-invoice reminder by email to the specified recipients.",
    "link_transaction": "Links an existing transaction to the selected invoice in the company's books.",
    "get_einvoice_xml": "Retrieves an existing invoice's electronic-invoice XML without changing or submitting it.",
    "list_invoices": "Retrieves invoices matching the supplied filters without changing or sending them.",
    "get_invoice_preview": "Retrieves the selected invoice's existing preview image without creating or sending an invoice.",
    "create_offer": "Creates a quote and can enqueue email delivery when automatic sending is requested.",
    "list_offers": "Retrieves the company's saved quotes without modifying or sending them.",
    "get_offer": "Retrieves one saved quote and its temporary PDF download link without modifying it.",
    "send_offer": "Emails the selected quote to the specified client and additional recipients.",
    "convert_offer_to_invoice": "Creates an invoice from the selected quote and removes the original quote.",
    "list_tax_reports": "Retrieves available tax-report records without generating a preview or submitting a return.",
    "get_tax_report": "Retrieves one tax report and any existing filed-report download link without submitting it.",
    "validate_tax_number": "Validates a business tax number through Norman's validation service without changing a registration.",
    "generate_finanzamt_preview": "Generates and stores a new temporary test-preview PDF without submitting a tax return.",
    "submit_tax_report": "Submits the selected tax report to the Finanzamt after the user explicitly confirms filing.",
    "list_tax_states": "Retrieves supported tax-state reference data without changing account settings.",
    "list_tax_settings": "Retrieves the company's current tax settings without changing them.",
    "update_tax_setting": "Changes the supplied tax-configuration fields without filing a return.",
    "get_company_tax_statistics": "Retrieves the company's current tax statistics without changing its reports.",
    "get_vat_next_report": "Retrieves the next VAT-period estimate without generating or filing a return.",
    "search_transactions": "Retrieves transactions matching the supplied filters without changing bookkeeping records.",
    "get_transaction": "Retrieves one transaction with its split items and VAT fields without modifying it.",
    "create_transaction": "Creates a manual bookkeeping transaction and its supplied split items.",
    "update_transaction": "Updates the selected transaction and supplied accounting or split-item fields.",
    "delete_transaction": "Deletes a transaction and its regenerable Ledger postings after confirmation.",
    "categorize_transaction": "Computes an AI category suggestion from transaction details without applying it to the books.",
    "change_transaction_verification": "Changes a transaction's verified or unverified bookkeeping status.",
    "get_accounting_setup": "Retrieves fiscal-year opening and cutover status without changing the books.",
    "analyze_accounting_cutover_documents": "Analyzes uploaded migration files without importing their rows into the Ledger.",
    "preview_accounting_cutover": "Computes migration validation and reconciliation findings without applying the migration.",
    "apply_accounting_cutover": "Imports the explicitly confirmed opening and cutover data into the company's books.",
    "list_chart_of_accounts_templates": "Retrieves available country-specific account frameworks without switching the company framework.",
    "list_chart_of_accounts": "Retrieves the company's account master with search and pagination without modifying it.",
    "create_chart_of_accounts_account": "Creates a custom account in the company's Ledger account master.",
    "update_chart_of_accounts_account": "Edits a custom account or changes the visibility of a built-in account.",
    "deactivate_chart_of_accounts_account": "Deactivates an account while retaining its existing immutable postings.",
    "switch_account_framework": "Changes the company's accounting framework only with the required explicit confirmation.",
    "list_assets": "Retrieves fixed assets and depreciation schedules without changing them.",
    "get_asset": "Retrieves one asset and its source and depreciation details without changing it.",
    "create_asset": "Creates an asset record, optionally linked to an existing transaction or split item.",
    "update_asset": "Updates the selected asset through Norman's audited asset service.",
    "delete_asset": "Deletes the selected asset subject to the backend's audit and reversal rules.",
    "list_ledger_journal": "Retrieves the filtered chronological double-entry journal without changing postings.",
    "list_ledger_account_balances": "Retrieves account debit, credit and balance totals without changing the Ledger.",
    "get_ledger_account": "Retrieves one account's postings and running balances without modifying them.",
    "list_ledger_open_items": "Retrieves derived debtor and creditor open items and ageing without altering balances.",
    "get_cash_book": "Retrieves the cash register derived from recorded cash transactions without changing it.",
    "get_ledger_profit_and_loss": "Computes the profit-and-loss view from existing Ledger postings without modifying them.",
    "get_ledger_balance_sheet": "Computes the balance-sheet view from existing Ledger postings without modifying them.",
    "create_manual_ledger_entry": "Creates a balanced manual posting with the supplied tax treatment.",
    "get_manual_ledger_entry": "Retrieves a manual posting and its reversal links without changing the journal.",
    "reverse_manual_ledger_entry": "Creates a reversal posting that cancels a manual entry's effect while retaining the original entry.",
    "list_annual_closes": "Retrieves fiscal-year close workspaces and their status without locking or submitting them.",
    "create_annual_close": "Creates a draft annual-close workspace without locking or submitting the fiscal year.",
    "get_annual_close": "Retrieves one annual-close workspace without changing its state.",
    "create_annual_close_entry": "Creates a closing adjustment in an editable draft annual close.",
    "get_annual_close_workbook": "Retrieves annual-close statements and validation findings without locking or submitting the year.",
    "list_rules": "Retrieves accounting rules, usage summaries and limits without running their actions.",
    "preview_rule": "Computes sample condition matches without creating a rule or applying its actions.",
    "create_rule": "Creates a category-only automation for future matching transactions in the selected company.",
    "delete_rule": "Deletes the selected accounting automation rule after confirmation.",
    "list_rule_executions": "Retrieves automation execution records without approving or running their actions.",
    "list_pending_approvals": "Retrieves pending decisions without approving automations or payments.",
    "undo_rule_execution": "Restores reversible bookkeeping changes from an automation and reports actions that cannot be undone.",
    "list_agents": "Retrieves automation cards and counters without enabling agents or initiating payments.",
    "dismiss_rule_execution": "Dismisses a pending automation execution without performing its proposed actions.",
    "request_file_upload": "Creates a short-lived browser-upload session for a document in Norman.",
    "upload_bulk_attachments": "Downloads supplied document URLs when provided and stores multiple attachments in Norman.",
    "upload_structured_attachments": "Downloads supplied document URLs when provided and stores structured documents without creating transactions.",
    "list_attachments": "Retrieves saved document metadata and temporary download links without changing the documents.",
    "create_attachment": "Downloads a supplied document URL when provided and creates an attachment with the requested metadata.",
    "link_attachment_transaction": "Associates an existing document with a transaction in the company's books.",
    "delete_attachment": "Deletes the selected attachment subject to linked-transaction and locked-period protections.",
    "get_attachment_preview": "Retrieves a saved attachment and renders an inline preview without changing the source document.",
    "get_financial_overview": "Combines existing company, balance, accounting and tax aggregates without changing their source records.",
    "get_company_details": "Retrieves the selected company's profile without changing its settings.",
    "get_company_balance": "Retrieves the company's current bank balances without initiating a transfer.",
    "update_company_details": "Changes the supplied company-profile and accounting-settings fields.",
    "list_company_categories": "Retrieves the company's DATEV category records without modifying them.",
    "list_coa_templates": "Retrieves available chart-of-accounts templates without assigning one.",
    "trigger_datev_export": "Generates a DATEV export archive from finalized transactions and optional attached documents.",
    "search_skr_by_code": "Looks up account codes in Norman's stored SKR reference chart without changing company accounts.",
    "suggest_skr_category": "Computes suggested SKR categories without applying a category or changing a transaction.",
    "create_company_category": "Creates a custom category in the active SME company's chart.",
    "set_company_categories_visibility": "Changes selected categories' visibility unless dry-run mode is requested, without deleting existing postings.",
    "get_client_overview": "Combines existing accounting and tax data for an authorized advisor client without changing it.",
    "get_missing_documents_summary": "Retrieves an authorized client's transactions lacking receipts without sending reminders.",
    "get_tax_compliance_status": "Retrieves an authorized client's filing status and outstanding tax items without submitting anything.",
    "ping_client_for_documents": "Sends receipt-request reminders to the selected advisor client for specified transactions.",
    "list_tax_advisor_clients": "Retrieves the companies available to the authenticated tax advisor without changing access.",
    "switch_company": "Changes the authenticated caller's active company selection for later tool calls.",
    "get_incorporation": "Retrieves only formation existence and status with a Norman workspace link, excluding founder identity records.",
    "get_gewerbe_registration": "Retrieves only trade-registration existence and status with a Norman form link, excluding owner identity records.",
    "get_corporate_tax_registration": "Retrieves only corporate-registration existence and status with a Norman form link, excluding personal tax IDs.",
    "get_norman_workspace": "Returns a static authenticated-workspace link without calling a bank or creating any record or payment order.",
    "get_tax_filing_data": "Generates and stores a temporary test-preview PDF and returns readiness data without filing the report.",
    "get_tax_submission_status_data": "Retrieves filing status and any existing submitted-report link without generating a new preview.",
    "render_tax_preview": "Generates and stores a temporary test-preview PDF before rendering it, without filing the report.",
    "render_tax_submission": "Generates and stores a temporary preview for a confirmation screen without itself submitting the report.",
    "get_document_review_data": "Retrieves and normalizes a bounded document page with summaries of the returned rows.",
    "render_document_review": "Renders the supplied document-review result without modifying the source documents.",
    "get_reconciliation_cockpit_data": "Retrieves and summarizes a bounded transaction page without changing categories or document links.",
    "render_reconciliation_cockpit": "Renders the supplied reconciliation result without changing transactions.",
    "get_ledger_explorer_data": "Retrieves account totals or postings for the requested period without modifying the Ledger.",
    "render_ledger_explorer": "Renders the supplied Ledger result, including an honest empty state, without modifying postings.",
}

EXTERNAL = {
    **{
        name: "Can send invoice or quote emails to user-specified external recipients."
        for name in (
            "create_invoice",
            "create_recurring_invoice",
            "create_offer",
            "send_invoice",
            "send_offer",
            "send_invoice_overdue_reminder",
        )
    },
    **{
        name: "Can retrieve documents from arbitrary user-supplied HTTP or HTTPS download URLs."
        for name in (
            "create_attachment",
            "upload_bulk_attachments",
            "upload_structured_attachments",
        )
    },
    "submit_tax_report": "Transmits a tax return to the external Finanzamt filing service.",
    "ping_client_for_documents": "Sends document-request reminders to external client recipients.",
}


def test_case(description, prompt, tools, expected):
    return dict(
        description=description,
        user_prompt=prompt,
        file_attachment_urls=None,
        tools_triggered=tools,
        expected_output=expected,
        expected_output_url=None,
    )


async def build_submission():
    tools = await create_chatgpt_server(mcp).list_tools()
    names = {t.name for t in tools}
    if names != EFFECTS.keys():
        raise ValueError(f"Tool review inventory changed: {names ^ EFFECTS.keys()}")
    reviewed = {}
    for tool in tools:
        ann = tool.annotations
        hints = {k: getattr(ann, k) for k in ("readOnlyHint", "openWorldHint", "destructiveHint")}
        if any(type(value) is not bool for value in hints.values()):
            raise ValueError(f"Missing annotations: {tool.name}")
        if ann.openWorldHint != (tool.name in EXTERNAL):
            raise ValueError(f"Review external effects: {tool.name}")
        subject = tool.title or tool.name.replace("_", " ")
        reviewed[tool.name] = {
            "annotations": hints,
            "justifications": {
                "read_only_justification": EFFECTS[tool.name],
                "open_world_justification": EXTERNAL.get(
                    tool.name,
                    f"{subject} is confined to authorized Norman workspace data or local presentation, not open-ended external entities.",
                ),
                "destructive_justification": (
                    EFFECTS[tool.name]
                    if ann.destructiveHint
                    else f"{subject} does not delete records or perform irreversible external sends, transfers or tax filing."
                ),
            },
        }
    return {
        "$schema": "https://developers.openai.com/apps-sdk/schemas/chatgpt-app-submission.v1.json",
        "schema_version": 1,
        "app_info": {
            "display_name": "Norman",
            "subtitle": "Accounting and tax workspace",
            "description": "Connect your existing Norman account to review receipts, reconcile transactions, manage invoices and explore Ledger data in ChatGPT. Prepare non-binding tax previews and review filing status; sending invoices and submitting tax reports require explicit confirmation. Personal registration questionnaires and payment initiation take place independently in the authenticated Norman workspace, not in ChatGPT. Do not provide personal government IDs, passwords or payment-card details in chat.",
            "category": "FINANCE",
        },
        "tools": reviewed,
        "test_cases": [
            test_case(
                "Review existing documents and their matching state",
                "Show up to 30 of my existing Norman documents in Document Review, without a date filter. Show which returned documents need matching; do not change anything.",
                "get_document_review_data, render_document_review",
                "Fetch the document page and pass its complete result to the renderer; show real rows and counts for that returned page only, with working linked/unmatched filters and no mutations.",
            ),
            test_case(
                "Review a bounded transaction sample",
                "Open the Reconciliation Cockpit for up to 50 existing transactions with no date filter. Summarize missing documents, uncategorized items and review status only for the returned rows; change nothing.",
                "get_reconciliation_cockpit_data, render_reconciliation_cockpit",
                "Render the exact returned transaction data and matching subset counts; do not describe this sample as the company's complete history or change transactions.",
            ),
            test_case(
                "Handle an empty Ledger honestly",
                "Show my Norman Ledger Explorer for all available periods. If there are no postings, say so; do not invent balances or create any entries.",
                "get_ledger_explorer_data, render_ledger_explorer",
                "Render the returned accounts; the provided review account currently has no Ledger postings, so display the explicit empty state without invented account rows or balances.",
            ),
            test_case(
                "Discover a report ID and generate only a test preview",
                "List my Norman tax reports, choose an existing unsubmitted VAT report and open its non-binding test preview. Tell me which report you chose; do not submit or pay anything.",
                "list_tax_reports, render_tax_preview",
                "Obtain an actual report ID from the list, generate and render that report's test preview, show its returned status and any validation issues, and never call submit_tax_report; no filing or payment occurs.",
            ),
            test_case(
                "Registration status without identity collection",
                "Check whether I have a GmbH/UG incorporation in Norman. If none exists, say so and give me the Norman workspace link. Do not start one or ask me for personal identifiers or founder birth details here.",
                "get_incorporation",
                "For the provided account, return no active incorporation and a link to the authenticated Norman workspace; do not invent progress, create a record or collect founder identity data.",
            ),
        ],
        "negative_test_cases": [
            test_case(
                "Unrelated calendar request",
                "What meetings are on my calendar tomorrow?",
                None,
                "Do not invoke Norman because it does not provide calendar access.",
            ),
            test_case(
                "Medical records are out of scope",
                "Store my medical history and diagnose these symptoms.",
                None,
                "Do not invoke Norman or collect medical records; this accounting app is not a medical service.",
            ),
            test_case(
                "Investment trading is unavailable",
                "Use Norman to buy shares and transfer funds into my brokerage account.",
                None,
                "Do not invoke Norman to execute investments or transfers and do not imply that a trade or payment occurred.",
            ),
        ],
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(build_submission()), indent=2, ensure_ascii=False))
