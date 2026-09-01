# Norman MCP priorities and parity roadmap

Norman MCP should expose the same accounting model that customers use in the Norman product: day-to-day transactions and operational records feed a double-entry Ledger, and the Ledger powers reports, the annual close, and tax workflows.

This document separates what is available today from the next parity work. It is a product roadmap, not a compatibility promise or release schedule.

## Available today

- Transactions, including split items, categorisation, receipts, and verification
- Clients, vendors, invoices, reminders, and payment links
- SKR03/SKR04 chart-of-accounts templates and company-specific accounts
- Ledger journal, balances, account sheets, open items, cash book, P&L, and balance sheet
- Manual Ledger entries and reversals
- Assets and depreciation data
- Annual-close workbooks and closing entries
- DATEV export
- Tax-report review, validation, ELSTER preview, and separately annotated submission tools
- GmbH/UG formation and corporate tax registration workflows
- Tax-advisor company review, DATEV preparation, missing-receipt, and compliance skills

## P0: complete company-accounting parity

### 1. Opening and migration workspace

Expose the full opening/cutover flow rather than only its current status:

- upload and inspect DATEV opening balances and booking stacks;
- detect SKR03/SKR04 from imported data and ask before changing the company framework;
- import counterparties and asset registers;
- preview findings and reconciliation totals before applying an import;
- persist the cutover boundary and prevent duplicate transaction postings for covered periods.

### 2. Payment-account and bank mapping

Allow agents to list connected financial accounts and map each bank, card, cash, or PayPal source to its Ledger account. Reconnection must identify an existing institution/account and must not leave duplicate expired-connection prompts.

### 3. Safe filing and annual-close previews

- expose E-Bilanz and annual-close preview/download operations;
- keep preview and submission as distinct tools;
- require an explicit, fresh confirmation immediately before tax submission or another irreversible external action;
- return actionable validation findings instead of raw ELSTER or taxonomy identifiers where possible.

### 4. VAT and ZM source parity

Keep tax treatment consistent across Norman transactions and non-transaction Ledger entries, including domestic VAT, EU and non-EU reverse charge, foreign VAT, Kleinunternehmer cases, split items, refunds, and Zusammenfassende Meldung (ZM). Preserve source links so an agent can explain how each report line was derived.

### 5. Payroll review

Add read and review tools for managing-director payroll, payroll runs, Ledger postings, and Lohnsteuer previews. Submission remains confirmation-gated.

### 6. Exports and audit handoff

- expose the Ledger GoBD audit export alongside the existing DATEV export;
- support period, account, and source filters without changing the legacy transaction export;
- return downloadable artifacts and progress for long-running export jobs.

### 7. Release integrity

Make Git tags, GitHub releases, PyPI, and `server.json` use one published version and add a verified package-release workflow. A registry manifest must never point to a package version that does not exist.

## P1: deeper bookkeeping workflows

- Cost centres (`Kostenstellen`) on transactions, split items, manual entries, Ledger views, and DATEV export
- Drill-through from reports and Ledger postings to the originating Norman transaction, asset, payroll run, or import batch
- Search, filters, and pagination parity across chart of accounts, journal, SuSa, open items, and cash book
- Product/service catalogue, custom units, prices, VAT defaults, and optional inventory tracking
- Richer report comparison and reconciliation helpers for tax advisors

## MCP platform direction

### Company context

Company selection must be explicit, deterministic, and isolated per authenticated session. Multi-company and tax-advisor clients should be able to list stable company handles and pass a company identifier to scoped tools without relying on process-local global state.

### Long-running operations

DATEV imports, reconciliations, document extraction, ELSTER previews, and annual-close generation should report progress. Durable MCP Tasks are a candidate for operations that need polling, cancellation, or an `input_required` state; adoption should follow client support because Tasks are still an evolving protocol capability.

### Structured input

Use MCP elicitation for missing non-sensitive fields, confirmation, and reconciliation choices. Credentials, certificates, and other secrets must continue through Norman's authenticated UI or another protected channel, not elicitation forms.

### Interactive accounting views

MCP Apps are a candidate for Ledger tables, account drill-down, migration reconciliation, and tax-preview review when a host supports interactive UI. Every workflow must retain a complete text/tool fallback for clients without Apps support.

## Delivery rule

Each parity slice should ship end to end: API authority, MCP schema and annotations, safe confirmation boundary, tests, documentation, and at least one real-client or representative DATEV fixture. A merged pull request is not proof that the remote MCP server or package registry has been deployed.
