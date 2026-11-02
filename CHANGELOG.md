# Changelog

Changes to the hosted Norman MCP server at `https://mcp.norman.finance/mcp`.
The full list of tools is in [docs/tools.md](docs/tools.md).

## Unreleased

- The server source moved to a private repository. This repository keeps the
  documentation, skills and client manifests, and is updated with each release.
- The local `norman-mcp-server` package on PyPI is no longer updated. Connect
  to the hosted server with OAuth instead; see [Connect your AI client](docs/connecting.md).

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
