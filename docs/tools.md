# Tools

The hosted Norman MCP server offers 299 tools. Your AI client
picks them by itself; you never need to call one by name. Tools marked
**reads** only read your data.

This page is generated from the server's tool list at each release.

## Company and overview

| Tool | What it does | |
| :-- | :-- | :-- |
| `get_company_balance` | Get the current balance of the company. | reads |
| `get_company_details` | Get detailed information about the user's company. | reads |
| `get_financial_overview` | Get a financial overview in one call: company, current balances, period revenue/costs/profit, current tax estimates and next VAT period. Independent reads run concurrently. | reads |
| `list_coa_templates` | List available Chart of Accounts templates (e.g. SKR03, SKR04, PL_KPIR, PL_FULL) supported for the selected company. | reads |
| `list_companies` | List every company the user can work in: the ones they own or are a member of, and the ones they advise as a tax advisor. | reads |
| `list_company_categories` | List categories from the selected company chart (SKR03/SKR04, PL_KPIR or PL_FULL). Use these company-specific IDs whenever usesCompanyChart or isSme is true. | reads |
| `trigger_datev_export` | Germany only. Export DATEV and return a downloadUrl valid for one hour. By default GmbH/UG use the complete Ledger, including opening, manual, payroll, depreciation and closing entries; other companie… |  |
| `update_company_details` | Update company information. |  |

## Clients

| Tool | What it does | |
| :-- | :-- | :-- |
| `create_client` | Create a new client. |  |
| `delete_client` | Delete a client. |  |
| `get_client` | Get detailed information about a specific client. | reads |
| `list_clients` | Get a list of all clients for the company. | reads |
| `update_client` | Update an existing client. |  |

## Vendors

| Tool | What it does | |
| :-- | :-- | :-- |
| `create_vendor` | Create a new vendor (supplier). |  |
| `delete_vendor` | Delete a vendor. |  |
| `get_vendor` | Get detailed information about a specific vendor. | reads |
| `list_vendors` | Get a list of all vendors (suppliers) for the company. | reads |
| `update_vendor` | Update an existing vendor. Only the fields you pass are changed. |  |

## Products and services

| Tool | What it does | |
| :-- | :-- | :-- |
| `archive_product` | Archive a product: it stops being offered for new invoices; existing invoices keep their lines. Restore it later with update_product(status="active"). |  |
| `create_product` | Create a catalog product or service. |  |
| `get_product` | Get one product with its usage (how many invoices and recurring invoices use it). | reads |
| `list_products` | List the company's catalog products and services. | reads |
| `update_product` | Update a product. Only the given fields change; existing invoices are never touched. |  |

## Invoices

| Tool | What it does | |
| :-- | :-- | :-- |
| `cancel_invoice` | Reverse an issued invoice with a cancellation invoice (Stornorechnung; for a Polish company a faktura korygująca to zero). |  |
| `create_credit_note` | Credit part or all of an issued invoice with a credit note (Rechnungskorrektur; for a Polish company a faktura korygująca). |  |
| `create_delivery_note` | Make a delivery note (Lieferschein) from an issued invoice or an approved quote. |  |
| `create_invoice` | Create a new invoice. Ask for additional information if needed, for example: - If the client is not found, ask for the client details and create a new client if necessary. |  |
| `create_recurring_invoice` | Set up a recurring invoice: a template and a rule. Norman makes nothing in advance. On each run date it makes one ordinary invoice from the template, with the next number of the company's normal seque… |  |
| `duplicate_invoice` | Copy an invoice or a quote into a new draft of the same kind. |  |
| `end_recurring_invoice` | End a recurring invoice for good, including ongoing contract billing. Invoices it already made stay as they are. |  |
| `get_einvoice_xml` | Get the e-invoice XML for a specific invoice. | reads |
| `get_invoice` | Get detailed information about a specific invoice. | reads |
| `get_invoice_email_settings` | Read the company's reminder rule (steps, days, fees) and whether it gets a copy of client emails. | reads |
| `get_invoice_preview` | Get a visual preview of an invoice. | reads |
| `get_invoice_settings` | Read the active company's logo and defaults for future invoices and quotes. | reads |
| `get_recurring_invoice` | Get a recurring invoice: its template, rule, mode, status (active, paused, ended), nextRunOn, the next dates and the invoices it made. | reads |
| `link_transaction` | Pay an invoice with a transaction and finalize the transaction. |  |
| `list_invoice_email_templates` | List the email wording for each document type and reminder step in one language. | reads |
| `list_invoice_emails` | List every email to the client about an invoice or quote, newest first. | reads |
| `list_invoice_templates` | List templates, appearance choices, defaults and the active company's plan access. | reads |
| `list_invoices` | List invoices with optional filtering. | reads |
| `list_recurring_invoices` | List the company's recurring invoices with client, amount, rule, mode, status and nextRunOn. | reads |
| `make_invoice_recurring` | Repeat an existing invoice. It becomes the first of a series; Norman makes the next invoices on the rule, each billing the period after the one before. An invoice of an ended series can repeat again. |  |
| `pause_recurring_invoice` | Pause a recurring invoice: Norman makes no invoices until it is resumed. |  |
| `record_invoice_payment` | Record a payment that is not in the bank feed (cash, card, PayPal or a bank account Norman does not see) and let it pay the invoice, in one step: if the invoice cannot take it, no payment is saved. |  |
| `reset_invoice_email_template` | Delete the company's wording for one email and go back to Norman's default text. |  |
| `resume_recurring_invoice` | Resume a paused recurring invoice. It carries on from the next date; dates missed while it was paused stay skipped. |  |
| `save_invoice_email_template` | Save the company's wording for one kind of email in one language. |  |
| `send_invoice` | Send an invoice or quote to the client by email, with the PDF attached. |  |
| `send_invoice_overdue_reminder` | Send a payment reminder for an unpaid invoice by hand, one level above the last one. |  |
| `skip_invoice_reminder` | Stop a planned reminder: an email with status "scheduled" from list_invoice_emails. |  |
| `update_invoice` | Update invoice/quote fields, lines, dates, branding, payment or email settings. |  |
| `update_invoice_email_settings` | Change the company's reminder rule or its own copy of client emails. |  |
| `update_invoice_settings` | Change company defaults for future invoices and quotes. Existing documents keep their design. |  |
| `update_recurring_invoice` | Update a recurring invoice: its template, its rule or its mode. |  |

## Offers

| Tool | What it does | |
| :-- | :-- | :-- |
| `convert_offer_to_invoice` | Convert a quote into a draft invoice. |  |
| `create_offer` | Create a new offer/quote, with the same line, design, payment and sender options as create_invoice. Omit document_design, colour and font to inherit company branding. |  |
| `get_offer` | Get detailed information about a specific offer/quote. | reads |
| `list_offers` | List offers/quotes with optional filtering. | reads |
| `send_offer` | Send an offer/quote via email. |  |

## Contracts

| Tool | What it does | |
| :-- | :-- | :-- |
| `prepare_invoice_from_contract` | Contract to invoice: save a source contract and extract an editable invoice proposal. |  |

## Bills

| Tool | What it does | |
| :-- | :-- | :-- |
| `create_bill` | Record an incoming invoice/payable when the user asks to add a bill. |  |
| `delete_bill` | Delete a bill. |  |
| `get_bill` | Get detailed information about a specific bill. | reads |
| `list_bills` | Get a list of bills (incoming supplier invoices / Eingangsrechnungen). | reads |
| `mark_bill_paid` | Mark a bill as paid (``status="PAID"``) WITHOUT initiating a payment. Use this for bills that were already paid outside Norman (e.g. migrated bills) to clear them from the Bills view. |  |
| `pay_bill` | Germany only. Initiate a SEPA payment for a bill. ⚠️ This starts a REAL payment flow. Returns a ``paymentOrderId`` and a ``webformUrl`` the user must open to authorise the payment with their bank. |  |
| `scan_bill_document` | Extract supplier, amount, currency, dates and bank details from a document. | reads |
| `update_bill` | Update an existing bill. Currently supports changing the bill status — e.g. set ``status="PAID"`` to clear a migrated/already-paid bill from the Bills view. |  |

## Transactions

| Tool | What it does | |
| :-- | :-- | :-- |
| `categorize_transaction` | Detect category for a transaction using AI. | reads |
| `change_transaction_verification` | Verify or unverify a transaction (finalize or unfinalize). |  |
| `create_transaction` | Create a new manual transaction. |  |
| `delete_transaction` | Delete a transaction and its regenerable Ledger postings after confirmation. |  |
| `find_booking_payments` | German and Polish companies: what may pay an open booking, or what a payment may pay. | reads |
| `find_same_counterparty_transactions` | Before one booking's category changes: the counterparty's other open bookings still in that category. | reads |
| `get_flat_rates` | German official (BMF) flat rates Norman uses for the travel meal allowance and the home office flat rate of German sole proprietors; none apply to a Polish company. | reads |
| `get_transaction` | Get a transaction including its split items and current VAT semantics. | reads |
| `list_csv_import_jobs` | List recent CSV transaction imports for the active company. | reads |
| `pay_booking` | A payment pays an open booking made from a document or by hand. |  |
| `record_booking_payment` | Germany only. An open booking paid another way, with cash, a card, PayPal or a bank Norman does not see. |  |
| `rollback_csv_import_transactions` | Preview or roll back transactions from one exact CSV import. |  |
| `search_transactions` | Search for transactions matching specified criteria. | reads |
| `unlink_payment` | Undo what a payment pays and take its document off it. |  |
| `update_transaction` | Update an existing transaction. For SME companies, use company_category_id and payment fields. |  |

## Categories

| Tool | What it does | |
| :-- | :-- | :-- |
| `create_company_category` | Create a new custom company category for the active company. |  |
| `search_skr_by_code` | Germany only. Search the FULL SKR chart of accounts (SKR03 or SKR04) by account code. | reads |
| `set_company_categories_visibility` | Hide or unhide company categories in bulk. |  |
| `suggest_skr_category` | Germany only. Use AI to find the best matching SKR categories by name or description. | reads |

## Bookkeeping rules

| Tool | What it does | |
| :-- | :-- | :-- |
| `apply_rule_to_existing` | Run an existing rule's supported transaction actions on up to 500 matching uncategorized transactions from the last 90 days. |  |
| `approve_rule_execution` | Approve an awaiting-review execution AFTER the user explicitly confirmed it: the rule's full action chain runs (category, VAT, reminder emails, ...). |  |
| `create_rule` | Create an automation rule. Preview first with preview_rule. Send at most one of category_id / company_category_id (freelancer vs SME); a rule with mark_document_not_required may leave the category alo… |  |
| `delete_rule` | Delete an automation rule after the user confirms. Prefer disabling (update_rule with is_active=false) when the user may want it back. |  |
| `dismiss_rule_execution` | Reject an awaiting-review execution after the user said no. The target goes back through normal categorization, and this rule never re-claims the same target. |  |
| `list_agents` | The prebuilt agents shelf with each card's state and counters: AI categorization, auto-enrichment, document reconciliation, invoice chasing, bill payments with approval, VAT-return readiness, client d… | reads |
| `list_pending_approvals` | Everything an agent prepared and is waiting on the user for, in one list: review-first automations, a return the tax autopilot prepared (a German UStVA, a Polish JPK_V7M or JPK_V7K), an active workflo… | reads |
| `list_rule_executions` | Automation execution log. status=awaiting_review lists the matches a review-first rule parked for the user's approval — show each one (rule name, transaction/invoice, planned actions) and let the user… | reads |
| `list_rules` | List the company's automation rules together with usage stats and the plan's automation limit. | reads |
| `preview_rule` | Dry-run rule conditions against recent transactions BEFORE creating the rule. Show the user a few of the returned matches so they can confirm the rule catches the right things. | reads |
| `toggle_agent` | Turn a prebuilt agent on or off after the user asked for it. |  |
| `undo_rule_execution` | Put back what an automation changed, newest action first, AFTER the user asked for it. |  |
| `update_rule` | Update an automation rule. Only the provided fields change. Re-activating a rule counts against the plan's automation limit like creating one. |  |

## Documents and receipts

| Tool | What it does | |
| :-- | :-- | :-- |
| `create_attachment` | Create a new attachment with a file. |  |
| `delete_attachment` | Delete an attachment — e.g. an orphan receipt/invoice with no linked transaction (a stale self-statement left behind after the real invoice was attached). |  |
| `get_attachment_preview` | Download an attachment and return it as an inline image. | reads |
| `get_file_upload_status` | Read this user's upload panel result, including per-document direction and attachment IDs. | reads |
| `link_attachment_transaction` | Link a transaction to an attachment. |  |
| `list_attachments` | Search saved purchase invoices and receipts (not outgoing sales invoices). Prefer search for supplier discovery. Individual filters are combined with AND. | reads |
| `request_file_upload` | Open an in-chat multi-file uploader for receipts and invoices. |  |
| `upload_bulk_attachments` | Upload multiple file attachments in bulk. |  |
| `upload_structured_attachments` | Store pre-processed documents without transaction side effects. |  |

## Ledger and accounting

| Tool | What it does | |
| :-- | :-- | :-- |
| `analyze_accounting_cutover_documents` | Germany (DATEV) and Poland (sp. z o.o., PL_FULL opening balance). Analyze migration files without writing anything to the Ledger. | reads |
| `apply_accounting_cutover` | Germany (DATEV) and Poland (sp. z o.o., PL_FULL opening balance). Write previewed opening/cutover data only after explicit confirmation. |  |
| `create_annual_close` | Germany only. Create a Draft annual-close workspace; this does not lock or submit the year. |  |
| `create_annual_close_entry` | Germany only. Post a closing adjustment to a Draft annual close; locked years remain server-protected. |  |
| `create_asset` | Create an active asset, optionally linked to a Norman Transaction or split item. |  |
| `create_chart_of_accounts_account` | Create a custom Ledger account; balance-sheet accounts stay Ledger-only. |  |
| `create_manual_ledger_entry` | Germany only. Create a balanced manual posting with explicit tax semantics. |  |
| `deactivate_chart_of_accounts_account` | Soft-delete an account. Existing postings remain in the immutable Ledger. |  |
| `delete_asset` | Delete an asset only after explicit confirmation; audit/reversal rules remain server-side. |  |
| `get_accounting_setup` | Germany (DATEV) and Poland (sp. z o.o., PL_FULL opening balance). Get opening/cutover status for a fiscal year without changing the books. | reads |
| `get_annual_close` | Germany only. Get one annual-close workspace and its Draft/locked/submitted status. | reads |
| `get_annual_close_workbook` | Germany only. Review SuSa, Bilanz, GuV, BVV and blocking validations. This never locks or submits. | reads |
| `get_asset` | Get an asset including source transaction, useful life and annual depreciation. | reads |
| `get_cash_book` | Read the cash register derived from CASH transactions and the Kasse account. | reads |
| `get_ebilanz_positions` | Germany only. List the E-Bilanz positions an account of this type may be assigned (GmbH/UG, SKR03/04). | reads |
| `get_ledger_account` | Germany only. Return a Kontenblatt with postings and a running balance for one account. | reads |
| `get_ledger_balance_sheet` | Germany only. Get the balance sheet using the same mappings as Annual Close and E-Bilanz. | reads |
| `get_ledger_profit_and_loss` | Germany only. Get GuV/P&L calculated exclusively from materialized Ledger postings. | reads |
| `get_manual_ledger_entry` | Germany only. Get a manual posting and its immutable reversal links. | reads |
| `list_annual_closes` | Germany only. List fiscal-year close workspaces and their current status. | reads |
| `list_assets` | List fixed assets and their depreciation schedules. | reads |
| `list_chart_of_accounts` | Search and page through the selected company's complete account master. | reads |
| `list_chart_of_accounts_templates` | List account frameworks available for the selected company and country. | reads |
| `list_ledger_account_balances` | Germany only. Return the SuSa: debit, credit and saldo for every used account. | reads |
| `list_ledger_journal` | Germany only. Read the chronological double-entry audit trail with source and tax-treatment filters. | reads |
| `list_ledger_open_items` | Germany only. Return the derived debtor/creditor open-item list and ageing. | reads |
| `prepare_accounting_cutover_accounts` | Germany only. Create or map the source accounts a cutover preview listed for review. |  |
| `preview_accounting_cutover` | Germany (DATEV) and Poland (sp. z o.o., PL_FULL opening balance). Preview findings and reconciliation without changing the books. | reads |
| `reverse_manual_ledger_entry` | Germany only. Correct a manual posting by Storno; the original entry is never deleted or edited. |  |
| `switch_account_framework` | Germany only. Switch SKR framework with the same explicit confirmation used by the Norman UI. |  |
| `update_annual_close_entry` | Germany only. Set the tax treatment of a closing adjustment posted to a Draft annual close. |  |
| `update_asset` | Edit an asset through the audited Asset service. |  |
| `update_chart_of_accounts_account` | Edit a custom account, or hide/unhide a built-in account. |  |

## DATEV

| Tool | What it does | |
| :-- | :-- | :-- |
| `get_datev_changes_since_handoff` | Germany only. What a new DATEV file would hold differently from the newest file the tax advisor has. | reads |
| `read_datev_file` | Inspect an uploaded DATEV file without importing it or changing the books. | reads |
| `validate_ledger_datev_export` | Germany only. Preflight a complete GmbH/UG Ledger export before accountant handoff. | reads |

## Taxes and filings

| Tool | What it does | |
| :-- | :-- | :-- |
| `explain_tax_report` | Polish companies only: what a Polish tax report's figure is made of. Use it to answer "why this amount" or "where does it come from"; a German company's report is refused (read it with get_tax_report)… | reads |
| `generate_finanzamt_preview` | Germany only. Generate a test Finanzamt preview for a tax report. |  |
| `get_company_tax_statistics` | Get tax statistics for the company. | reads |
| `get_filed_report_changes` | Germany only. What changed in a filed UStVA since it was sent to ELSTER. | reads |
| `get_tax_offices` | Search German tax offices (Finanzämter) by name, town or postcode. Germany only: a Polish company's urząd skarbowy is not in this directory. | reads |
| `get_tax_report` | Retrieve a specific tax report. | reads |
| `get_vat_next_report` | The next VAT return: its period, VAT amount and deadline. A German company's UStVA; a Polish VAT payer's JPK_V7M or JPK_V7K, due the 25th (next working day); none for a Polish company exempt from VAT.… | reads |
| `get_vat_proportion` | Polish VAT payers with both taxed and VAT-exempt (art. 43) sales: the VAT deduction proportion of art. 90 by tax year. | reads |
| `list_tax_reports` | List existing tax reports, optionally scoped to a period and report type. | reads |
| `list_tax_settings` | Get list of tax settings for the current company. | reads |
| `list_tax_states` | Germany only. Get list of available tax states. | reads |
| `resend_email_confirmation` | Mail a new confirmation link to the user's login email. |  |
| `submit_tax_report` | Germany only. Submit a tax report to the Finanzamt. |  |
| `suggest_tax_office` | Find the German Finanzamt responsible for a German address (Germany only). | reads |
| `update_tax_setting` | Update a tax setting for the selected company. Read its country and supported settings first. Review the report through its country-specific tools before any submission. |  |
| `update_vat_proportion` | Set the owner's choices about the Polish VAT deduction proportion (art. 90) of one tax year. Only what is given changes. Confirm the numbers with the user first: they come from the user's records. |  |
| `validate_tax_number` | Germany only. Check a German tax number (Steuernummer) with the ELSTER validator. Slashes, spaces and the 13-digit ELSTER form are accepted. | reads |

## Poland

| Tool | What it does | |
| :-- | :-- | :-- |
| `get_ksef_status` | Poland only. A Polish company's KSeF connection: connected or not, token or delegated access, what KSeF said about the token, the last pull and whether it stalled. Never the token itself. | reads |
| `get_polish_financial_statement` | Read the workbook, statutory lines, XML issues and notes for a Polish financial statement. | reads |
| `get_polish_jpk_filing_status` | Read available filing methods, sessions, MF status and UPO availability. Only confirmed acceptance and UPO prove success; XML preparation/download does not. Does not submit or sign. | reads |
| `get_polish_jpk_register` | Read sales/purchases, totals and exclusions from the JPK register; not proof of filing. | reads |
| `get_polish_ledger_account` | Read an account's opening/running balances and paginated entries; balances are not bank balances. | reads |
| `get_polish_ledger_entry` | Read a Polish posting with its source and reversal information. | reads |
| `get_polish_pit_filing_status` | Read PIT submission status and UPO availability; does not submit or sign. | reads |
| `get_polish_tax_book` | Read a JDG tax book, totals and exclusion reasons. The API synchronizes derived entries and exchange differences before reading. Returns the selected year/month, not a paginated subset. |  |
| `get_polish_tax_book_operation` | Explain whether an operation is in KPiR and why; synchronizes derived entries first. |  |
| `get_polish_tax_estimates` | Read API-calculated PIT/ZUS or CIT estimates. May synchronize derived books; estimates are not filed returns and missing amounts must not be presented as zero. |  |
| `get_polish_trial_balance` | Read the API's complete PL_FULL trial balance in PLN, including opening and closing balances. | reads |
| `list_polish_financial_statements` | Read all prepared PL_FULL financial statements. A draft or closed year does not prove KRS filing. | reads |
| `list_polish_ledger_accounts` | Read the complete active PL_FULL chart; use these codes rather than German SKR codes. | reads |
| `list_polish_ledger_journal` | Read PL_FULL postings. Follow pagination until all pages are read before reporting totals. | reads |
| `lookup_polish_company` | Poland only. Look the selected sp. z o.o. up in the KRS and on the Ministry of Finance White list (Biała lista) by its NIP or KRS number, and propose each detail Norman lacks; the owner applies them i… |  |
| `preview_polish_accounting_export` | Preview export compatibility, blockers, warnings and snapshot. Does not download, post or file. | reads |
| `propose_tax_setting_change` | Poland only. Propose a change to a Polish company's tax settings; the owner applies it in Norman. |  |
| `search_polish_tax_offices` | Poland only. Search the Polish tax offices (urzędy skarbowe) by name, town or code. Each has its 4-digit code (KodUrzedu), which propose_tax_setting_change takes for tax_office. | reads |

## Payroll

| Tool | What it does | |
| :-- | :-- | :-- |
| `approve_payroll_correction` | Germany only. Approve a prepared correction: the corrected version is booked as reversal plus new postings. |  |
| `approve_payroll_month` | Germany only. Approve a calculated payroll month: its version is frozen and booked to the ledger. |  |
| `calculate_payroll_month` | Germany only. Calculate (or recalculate) the draft payroll of one month. |  |
| `cancel_payroll_correction` | Germany only. Discard a prepared, not yet approved correction. The approved month stays as it was. |  |
| `get_aag_claim` | Germany only. Prepared AAG reimbursement (U1 sick pay, U2 maternity) of an approved month. | reads |
| `get_contribution_plan` | Germany only. The Beitragsnachweis estimate of one month, per Krankenkasse or Minijob-Zentrale. | reads |
| `get_employer_payroll_setup` | Germany only. The employer data payroll needs, and what is still missing. | reads |
| `get_lohnkonto` | Germany only. A one-hour download link to the Lohnkonto PDF of one year (§ 41 EStG). | reads |
| `get_payroll_month` | Germany only. The payroll of one month: status, people, totals and what blocks it. | reads |
| `get_payroll_overview` | Germany only. Where the company stands with payroll (Lohnabrechnung). | reads |
| `get_payroll_payments` | Germany only. What the approved month still has to pay, and to whom. | reads |
| `get_payroll_person` | Germany only. One person on the payroll with salary and tax history and social insurance. | reads |
| `get_payslip` | Germany only. A one-hour download link to the payslip (Gehaltsabrechnung) PDF of one month. | reads |
| `get_social_insurance_contributions` | Germany only. Social insurance contributions of one month, per person and per collecting body. | reads |
| `get_wage_tax_return` | Germany only. One Lohnsteuer-Anmeldung with its per-person lines. | reads |
| `list_payroll_people` | Germany only. List the managing directors and employees on the payroll. | reads |
| `list_wage_tax_returns` | Germany only. List the Lohnsteuer-Anmeldungen (wage tax returns) with their status. | reads |
| `mark_wage_tax_return_filed` | Germany only. Record that this Lohnsteuer-Anmeldung was filed outside Norman, e.g. in Mein ELSTER. |  |
| `prepare_payroll_correction` | Germany only. Prepare a correction of an approved month's gross salaries, as a draft. |  |
| `prepare_wage_tax_return` | Germany only. Compute (or recompute) the draft Lohnsteuer-Anmeldung of a filing period. |  |
| `preview_wage_tax_return` | Germany only. Send the Lohnsteuer-Anmeldung to ELSTER as a test transmission; nothing is filed. |  |
| `record_absence` | Germany only. Record paid vacation or an ordinary sickness of a person, full days only. |  |
| `record_minijob_details` | Germany only. Record the minijob details of a commercial minijob (up to €603 a month in 2026). |  |
| `record_salary_change` | Germany only. Record a new monthly gross salary from a date (raise, reduction, new agreement). |  |
| `record_statutory_insurance` | Germany only. Record the social insurance data of an employee with statutory insurance. |  |
| `record_tax_profile_change` | Germany only. Record changed wage tax data (ELStAM) of a person from a date. |  |
| `record_work_schedule` | Germany only. Record the agreed weekly working hours of a person from a date. |  |
| `save_contribution_plan` | Germany only. Save the Beitragsnachweis estimate of a month as shown by get_contribution_plan. |  |
| `set_employment_end` | Germany only. Record the last day of a person's employment, or remove it. |  |
| `submit_wage_tax_return` | Germany only. File the Lohnsteuer-Anmeldung with the tax office through ELSTER. Binding. |  |
| `update_employer_payroll_setup` | Germany only. Update the employer data payroll needs; omitted fields keep their value. |  |

## Workflows

| Tool | What it does | |
| :-- | :-- | :-- |
| `answer_workflow_question` | Give a waiting workflow the user's answer to its question (blockedDetail). Norman stores it on the step and continues the run on its servers. |  |
| `complete_workflow_step` | Mark a manual step (blockedReason manual_step) done — or skipped — after the user says they did it or want to skip it, and let the run continue. |  |
| `confirm_routine` | Confirm a detected routine only after the user explicitly agrees. |  |
| `continue_workflow` | Try the current step again after it stopped (blockedReason step_failed), or after the user connected the missing source. Tell the user what stopped it first — the reason is in blockedDetail. |  |
| `dismiss_routine` | Dismiss a detected routine when the user says it is not useful. |  |
| `get_agent_week` | What Norman's agents did for this company in the last seven days — the numbers of the weekly email: bookings by the user's rules, transactions categorized, payment reminders sent, workflows completed,… | reads |
| `get_workflow_run` | One workflow run with its steps: which are done, which is active, each step's summary, and why the run is waiting (blockedReason: user_input, manual_step, source_required, ai_limit, step_failed). | reads |
| `list_routines` | Read detected and confirmed routines for the selected company. | reads |
| `list_workflows` | The workflows this company can run, each with its steps, its default period and its schedule if it runs by itself, plus the runs that are active now and the latest run of each workflow. | reads |
| `request_workflow_input` | Pause a workflow step when a required fact, choice or approval is missing. |  |
| `schedule_workflow` | Let Norman start a workflow by itself, after the user asked for it. Calling it again changes the timing. Norman asks the user only when a step needs them. |  |
| `start_workflow` | Start a workflow when the user asks for it; an active run of the same workflow is resumed instead of starting a second one. Norman then works through the steps on its servers. |  |
| `stop_workflow` | Stop an active run when the user no longer wants it. Steps not yet started will not run; a step in progress may finish first. Completed work stays, and the workflow can be run again later. |  |
| `unschedule_workflow` | Stop starting a workflow by itself when the user asks. A run already started is not affected, and the workflow can still be run by hand. |  |

## Interactive apps

| Tool | What it does | |
| :-- | :-- | :-- |
| `get_document_review_data` | Use this when reviewing extracted documents or finding unmatched receipts. | reads |
| `get_ledger_explorer_data` | Use this when exploring a German GmbH/UG's SKR account balances and drilling into Ledger postings (Germany only; a Polish sp. z o.o. uses get_polish_trial_balance). | reads |
| `get_norman_approval_data` | Read one execution and its current transaction before the user decides. Show every planned action, including external effects. No inferred changes or automatic approval. | reads |
| `get_norman_inbox_data` | Read current bank balances, bookkeeping counts, workflow questions and approvals. Bookkeeping tasks include overdue invoices, unattached invoice/receipt documents, operations with status UNVERIFIED aw… | reads |
| `get_reconciliation_cockpit_data` | Use this when checking transactions that need documents, categories or review. | reads |
| `get_tax_filing_data` | German companies only: generate and store a temporary Finanzamt test preview and return its readiness view. A Polish JPK_V7 is read with get_polish_jpk_register instead. |  |
| `get_tax_submission_status_data` | German companies only: refresh an ELSTER filing's status after a submission attempt, without creating a new preview. A Polish JPK_V7's status: get_polish_jpk_filing_status. | reads |
| `open_norman_inbox` | Open Norman's Inbox beside the conversation or from the sidebar. Load the selected company's current state. Rendering never approves anything. | reads |
| `render_document_review` | Render the interactive Document Review. Always call get_document_review_data first and pass its complete result as payload. | reads |
| `render_ledger_explorer` | Render the interactive Ledger Explorer. Always call get_ledger_explorer_data first and pass its complete result as payload. | reads |
| `render_reconciliation_cockpit` | Render the interactive Reconciliation Cockpit. Always call get_reconciliation_cockpit_data first and pass its complete result as payload. | reads |
| `render_tax_preview` | German companies only: open a test Finanzamt preview for a tax report (a Polish JPK_V7 is read with get_polish_jpk_register). This never submits the report. |  |
| `render_tax_submission` | German companies only: open the ELSTER confirmation step for a tax report (Norman files a Polish JPK_V7 only from its app, once the owner approves it). Rendering never submits anything. |  |

## Calculators and forms

| Tool | What it does | |
| :-- | :-- | :-- |
| `calculate_public_estimate` | Calculate a what-if estimate with Norman's existing website engine, without reading an account. | reads |
| `generate_polish_document` | Prepare a Polish document at the user's request. Never send, sign, file or pay anything. |  |
| `get_polish_form` | Get a form's current version, required fields, limits, instructions and official source. | reads |
| `get_public_calculator` | Read the live inputSchema and applicability before calculating; ask only for missing facts. | reads |
| `list_polish_forms` | Find Polish forms, PIT/VAT/ZUS guides and generators for business documents. | reads |
| `list_public_calculators` | Find calculators for VAT/net/gross, JDG PIT/ZUS, depreciation, salary cost and company taxes. | reads |

## Company formation

| Tool | What it does | |
| :-- | :-- | :-- |
| `add_incorporation_shareholder` | Germany only. Section 2/5 — add a shareholder (max 3 for the statutory Musterprotokoll). |  |
| `check_incorporation_name` | Germany only. Search the German commercial register (Handelsregister) for similar company names. | reads |
| `complete_incorporation_step` | Germany only. Tick a post-notary formation roadmap step done/undone (steps 3-9 of the journey). |  |
| `create_incorporation` | Germany only. Start a new GmbH/UG incorporation for the current user. |  |
| `generate_incorporation_documents` | Germany only. Generate the founding document drafts (PDF): Musterprotokoll (when selected) and the Gesellschafterliste (§ 40 GmbHG). |  |
| `get_incorporation` | Germany only. Get the user's active company incorporation (GmbH/UG founding), if any. | reads |
| `get_incorporation_choices` | Germany only. Get valid values for incorporation enum fields (label by value). | reads |
| `get_incorporation_document_preview` | Germany only. Show the user a first-page image of a generated founding document for review. | reads |
| `invite_incorporation_shareholder` | Germany only. Send (or resend) a secure fill-your-details link to a co-founder. |  |
| `match_incorporation_notaries` | Germany only. Get up to 3 notaries matching the collected preferences (online capability, city). |  |
| `remove_incorporation_shareholder` | Germany only. Remove a shareholder. Remaining shareholders are renumbered automatically. |  |
| `request_incorporation_notary` | Germany only. Final step — request the notary hand-off. REQUIRES generated documents. |  |
| `set_incorporation_agreement` | Germany only. Section 4/5 — founding agreement type. |  |
| `suggest_incorporation_purpose` | Germany only. Reformulate a rough business purpose (Unternehmensgegenstand) into registry-ready wording. | reads |
| `update_incorporation_capital` | Germany only. Section 3/5 — share capital. Validated against the legal form. |  |
| `update_incorporation_company` | Germany only. Section 1/5 — company basics. Any subset of fields; provided fields are validated. |  |
| `update_incorporation_notary_preferences` | Germany only. Section 5/5 — notary preferences (city, online vs in person, timeframe). |  |
| `update_incorporation_shareholder` | Germany only. Update a shareholder (any subset of fields). Returns the full record. |  |

## Registrations

| Tool | What it does | |
| :-- | :-- | :-- |
| `create_corporate_tax_registration` | Germany only. Start the corporate Fragebogen. 400 if an active one already exists (use get_corporate_tax_registration). |  |
| `create_gewerbe_registration` | Germany only. Start a Gewerbeanmeldung. 400 if one already exists (use get_gewerbe_registration). |  |
| `generate_gewerbe_document` | Germany only. Generate the pre-filled GewA 1 PDF. 400 + `missing` if a section is incomplete. |  |
| `get_corporate_submission_link` | Germany only. The FINAL step: hand the user over to the Norman app to review and submit. | reads |
| `get_corporate_tax_registration` | Germany only. Get the user's corporate tax registration (Fragebogen), if any. Call this FIRST. | reads |
| `get_corporate_tax_registration_choices` | Germany only. Get the valid values for the corporate Fragebogen enum fields (value → label). | reads |
| `get_gewerbe_document_preview` | Germany only. Return the first page of the generated GewA 1 as an image for the user to review. | reads |
| `get_gewerbe_registration` | Germany only. Get the user's Gewerbeanmeldung, if any. Call this FIRST. | reads |
| `get_gewerbe_registration_choices` | Germany only. Get the valid values for the Gewerbeanmeldung enum fields (value → label). | reads |
| `get_gewerbe_trade_office` | Germany only. Resolve the responsible trade office (Gewerbeamt) for the business address. | reads |
| `set_corporate_people` | Germany only. Replace managing directors and shareholders with the complete supplied lists. |  |
| `suggest_gewerbe_activity` | Germany only. Reformulate a rough trade activity into precise, Gewerbeamt-ready wording. | reads |
| `update_corporate_company` | Germany only. Section 1 (company): name, seat, addresses, contact, activity and tax office. |  |
| `update_corporate_financials` | Germany only. Section 5 (financials): capital, start of activity, fiscal year, expected profits. |  |
| `update_corporate_registration_details` | Germany only. Section 2 (registration): notary date and Handelsregister state. |  |
| `update_corporate_vat_and_bank` | Germany only. Section 6 (VAT & bank): revenue forecast, Kleinunternehmer choice, taxation method, VAT ID and the refund bank account. |  |
| `update_gewerbe_basic` | Germany only. Section 1 (basics): when the trade starts and whether it's a head or branch office. |  |
| `update_gewerbe_business` | Germany only. Section 2 (business): legal form, name, Betriebsstätte address, activity, licence, public-sector participation and employees. |  |
| `update_gewerbe_owner` | Germany only. Section 3 (owner / authorized representative): personal data, address and main-vs-secondary occupation. |  |

## Tax advisors

| Tool | What it does | |
| :-- | :-- | :-- |
| `ask_tax_advisor` | Send a written question or message to the company's tax advisor (a German Steuerberater, a Polish company's own accountant). |  |
| `fulfill_document_request` | Answer the tax advisor's request for documents with documents uploaded to Norman. |  |
| `get_advisor_inbox` | For tax advisors: the clients with unanswered messages or open document requests. | reads |
| `get_client_messages` | For tax advisors: read a client's conversations and open document requests. | reads |
| `get_client_overview` | Get an aggregated financial health snapshot for a client company. Combines company details, balance, transaction stats, missing receipts, outstanding invoices, and tax report status into a single over… | reads |
| `get_missing_documents_summary` | Check the selected company; select company_id first when switching clients. | reads |
| `get_tax_advisor_messages` | Read the conversation with the company's tax advisor (a German Steuerberater, a Polish company's own accountant). | reads |
| `get_tax_compliance_status` | Check the tax compliance status for a client company. Identifies which tax reports are due, overdue, or unfiled, and flags any validation issues. | reads |
| `list_clients_for_period` | Each client of the tax advisor in one period, the way the advisor's client list shows it. Per client: open bookings (not finalized; an unpaid booking waits for its payment and is left out), bookings w… | reads |
| `list_signature_requests` | For tax advisors of German clients (Germany only): declarations waiting for your signature, or their history. | reads |
| `list_tax_advisor_clients` | List all client companies managed by the authenticated tax advisor. Each entry includes the company ID, name, account type, transaction count, and number of transactions missing documents. | reads |
| `ping_client_for_documents` | Send document request reminders to a client for multiple transactions at once. Each transaction triggers an email to the company owner asking them to upload the missing receipt or invoice. |  |
| `reject_signature_request` | For tax advisors of German clients: send a declaration back unsigned, with a reason the client sees. |  |
| `reply_to_client` | For tax advisors: write to a client in Norman. |  |
| `request_documents_from_client` | For tax advisors: ask a client for documents. |  |
| `sign_and_submit_declaration` | For tax advisors of German clients: sign a declaration with your ELSTER certificate and submit it to the Finanzamt (Germany only). |  |
| `switch_company` | Switch the active company context. All subsequent tool calls will operate on the selected company. Owners and members of several companies switch between them here, and tax advisors between their clie… |  |
