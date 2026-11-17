# Changelog

Changes to the hosted Norman MCP server at `https://mcp.norman.finance/mcp`.
The full list of tools is in [docs/tools.md](docs/tools.md).

## Unreleased

- DATEV booking batches of online shops and ERP tools (pathway, JTL-Wawi and
  similar) into the GmbH/UG ledger, OSS sales included:
  `preview_datev_batch_import`, `apply_datev_batch_import` (after the user
  confirms), `set_datev_batch_vat_rates`, `list_datev_batch_imports` and
  `delete_datev_batch_import`.
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
