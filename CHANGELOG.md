# Changelog

Changes to the hosted Norman MCP server at `https://mcp.norman.finance/mcp`.
The full list of tools is in [docs/tools.md](docs/tools.md).

## Unreleased

- Accounting offices, second step:
  - A Polish office files a client's JPK_V7 as its attorney with a qualified
    signature: `prepare_client_jpk_signing` hands out the metadata to sign as a
    10-minute link (`get_client_jpk_filing_file`, also for the UPO);
    `request_signed_jpk_upload` takes the signed file back; and
    `submit_client_jpk_signed` sends it after the accountant's yes.
  - A client's own people and what they may open: `list_client_people`,
    `invite_client_person`, `update_client_person_access`,
    `remove_client_person` and `cancel_client_person_invitation`.
  - `ask_client_for_plan` asks a client to choose a plan, and
    `start_client_company` starts a new sp. z o.o. or JDG for a client.
- Accounting offices run their clients from the chat as from the office portal:
  the team (`get_firm_team`, `invite_firm_member`, `update_firm_member` with
  access none/read/write per part of the books, `remove_firm_member` with a
  hand-over, `set_member_clients`, `assign_clients_to_member`,
  `set_client_handlers`, `cancel_firm_invitation`); new clients (`add_client`
  with its tax setup, `look_up_polish_clients` on the White list,
  `import_clients`, `invite_client_owner` and its 7-day rule,
  `cancel_client_owner_invitation`); a Polish office's month
  (`list_polish_clients_jpk`, `prepare_client_jpk` for the owner's approval,
  `get_client_jpk_runs`, `approve_client_jpk_for_owner` as the client's
  attorney, `answer_client_power_of_attorney`, `list_client_ksef`,
  `connect_client_ksef`); and the inbox across clients
  (`list_client_conversations`, `start_client_conversation`,
  `archive_client_conversation`, `list_document_requests`,
  `request_documents_from_clients`, `update_document_request`,
  `cancel_document_request`). New skills `pl-office-month`, `office-team` and
  `office-client-onboarding`; the `ta-*` skills work per client of the office.
- The advisor inbox and client conversations read the API's answers correctly:
  conversation ids, unread counts and the clients needing attention were empty.
- Accounting offices (tax advisor accounts) never write into the wrong client:
  every tool on one company takes `company_id`, an office's write without it is
  refused (`client_required`), and every result about a client names it in
  `activeClient`. An office sees its own tools and no longer the tools only a
  company's own people use; a company's own people no longer see the office
  tools. The server instructions explain how an office works across clients.
- `submit_feedback`: an agent reports where a Norman tool fell short (a wrong
  result, a missing filter or tool, an error, a misleading description) with a
  proposed fix, after the user agrees. The Norman team gets the report and
  fixes the tools from it.
- Payroll: `create_payroll_person` adds a managing director or an employee,
  a minijob included; its answer withholds the identifiers like every payroll
  tool. `update_employer_payroll_setup` takes `single_establishment`, `note` and
  the U1 flat surcharge, and works for a first setup. `record_minijob_details`
  explains a person without the minijob insurance profile instead of passing on
  the API's request for health fund data.
- DATEV booking batches of online shops and ERP tools (pathway, JTL-Wawi and
  similar) into the GmbH/UG ledger, OSS sales included:
  `preview_datev_batch_import`, `apply_datev_batch_import` (after the user
  confirms), `set_datev_batch_vat_rates`, `list_datev_batch_imports` and
  `delete_datev_batch_import`. `request_datev_file_upload` opens an in-chat panel for
  the batch files (CSV, TXT or ZIP) that books nothing and hands each file to the import.
- German partnerships (GbR, eGbR, PartG): the company details describe
  `isPartnership`, `partnershipForm` and `partnershipIncome`; new read-only
  tools `list_partnership_partners` and `get_partnership_profit_key`; the tax
  report tools know the Feststellungserklärung (`PARTNERSHIP_ASSESSMENT`) and
  never offer a partnership an income tax return.
- The server source moved to a private repository. This repository keeps the
  documentation, skills and client manifests, and is updated with each release.
- The local `norman-mcp-server` package on PyPI is no longer updated. Connect
  to the hosted server with OAuth instead; see [Connect your AI client](docs/connecting.md).
- Several businesses of one person (German Freiberufler and Gewerbetreibende):
  the new read-only tool `get_vat_entrepreneur` says whether they file one
  UStVA, annual VAT return and ZM from a main business, and which one.
  `company://current` names the main business of a grouped company, and the
  `tax-report` skill (1.3.0) never files a member's VAT itself.
  `submit_tax_report` explains the 409 for a return already filed from another
  company and takes `replace_filed_return`, which files an income tax return in
  place of the first only after the user confirms it; a VAT return has no
  override.

## 0.5.0 (2026-10-20)

- Polish bookkeeping: KPiR for JDG, full books for sp. z o.o., JPK registers,
  estimates and filing status.
- Complete Ledger export, DATEV preflight and an EXTF reader.
- Client and tax advisor messaging, and an advisor signature inbox.
- Partial invoice payments with `link_transaction` and a new
  `record_invoice_payment` tool.
- Switch UStVA and ZM filing reminders on or off from the assistant.
- Resend the email confirmation, and tell an unconfirmed email apart from a
  missing plan.

## 0.4.0 (2026-10-06)

- Payroll: 31 tools for the monthly payroll run, private by default.
- Norman workflows: start them from any MCP client, answer their questions and
  schedule them.
- Norman Inbox with bookkeeping tasks and approvals, live refresh and opt-in
  workflow events.
- Recurring invoices as a template and a rule; open and overdue invoices can
  be edited.
- Client emails and payment reminder rules.
- Finanzamt finder from the BZSt directory.
- `list_companies` for owners of several companies.
- Flat-rate deductions.
- Moved to MCP SDK 2 with isolated request identity.

## 0.3.0 (2026-09-27)

- Interactive accounting apps inside the chat: Document Review, Reconciliation
  Cockpit, Ledger Explorer and tax preview.
- Company accounting workspace, opening balances and cutover workflow.
- Products and services catalog, invoice templates, cancellations, credit
  notes and delivery notes.
- Contract-to-invoice and ongoing recurring invoices.
- E-Bilanz account assignments.
- Structured document upload.
- Gemini, Grok and Perplexity distribution.
