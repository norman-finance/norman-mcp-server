# Norman MCP priorities and parity roadmap

Norman MCP should expose the same accounting model that customers use in the Norman product: day-to-day transactions and operational records feed a double-entry Ledger, and the Ledger powers reports, the annual close, and tax workflows.

This document separates what is available today from the next parity work. It is a product roadmap, not a compatibility promise or release schedule.

## Delivery status

- **Shipped** means the capability is available from the deployed Norman MCP server.
- **In review** means implementation exists in a pull request but is not yet part of the deployed server.
- **Planned** means the product/API contract still needs implementation or MCP exposure.

The first P0 slice is **in review** in [PR #103](https://github.com/norman-finance/norman-mcp-server/pull/103): DATEV/opening-document analysis, reconciliation preview, and an explicitly confirmed opening/cutover import, plus a guided accounting-cutover skill.

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
- Document creation from an HTTPS URL, a Norman temporary file reference, or a small base64 payload, with optional pre-extracted invoice metadata

## P0: complete company-accounting parity

### 1. Opening and migration workspace

**Status: in review in [PR #103](https://github.com/norman-finance/norman-mcp-server/pull/103).** The implementation exposes the existing backend opening/cutover authority rather than creating a second accounting model:

- upload and inspect DATEV opening balances and booking stacks;
- detect SKR03/SKR04 from imported data and ask before changing the company framework;
- import counterparties and asset registers;
- preview findings and reconciliation totals before applying an import;
- persist the cutover boundary and prevent duplicate transaction postings for covered periods.

### 2. External document archive ingestion

Let a document archive hand Norman a receipt or invoice together with data it has already extracted, while Norman remains responsible for bookkeeping, bank reconciliation, and the DATEV/tax workflow.

Add one canonical `ingest_document` contract with:

- a ChatGPT-native top-level `file` object (`download_url`, `file_id`, optional `mime_type` and `file_name`) declared through `_meta["openai/fileParams"]`;
- portable fallbacks through a Norman `file_ref` or a short-lived, signed HTTPS `file_url` for MCP clients without native file parameters;
- `external_document_id` and `idempotency_key`, plus checksum-based duplicate detection;
- structured supplier/customer, invoice number, document date, amount, currency, VAT, document type, and line-item metadata;
- explicit processing modes: trust supplied metadata, verify it against the document, or use OCR as a fallback;
- an optional match-or-create transaction instruction without silently creating duplicate bookkeeping;
- provenance and confidence per extracted field, validation findings, ingest status, match status, and a stable Norman document identifier in the result.

The server now accepts the portable file object and declares its ChatGPT file parameter through `openai/fileParams`. It downloads transient URLs promptly, applies URL and size guards, and retains Norman's upload-link/file-reference flow as the compatibility fallback. Native ChatGPT attachment delivery is not considered fully shipped until the connector-level handoff has passed E2E verification; idempotency, provenance, matching, retention, and audit-state work also remain in this P0 item.

Claude custom connectors and the Anthropic Messages API MCP connector can call remote MCP tools with normal JSON arguments, so the portable `file_ref`, signed `file_url`, and small-base64 paths are the initial Claude-compatible contract. Anthropic does not currently document a Claude.ai attachment equivalent to `openai/fileParams` that is automatically forwarded into a remote MCP tool call. Treat a file attached to a Claude conversation as Claude context, not as a Norman upload, until an explicit bridge is implemented.

Claude parity therefore requires:

- a Norman presigned-upload/session flow that returns a stable `file_ref` before `ingest_document` is called;
- an adapter for custom Anthropic API clients that reads a Claude Files API asset and uploads the bytes to Norman before invoking the MCP tool;
- clear tool errors when only an unresolvable client-side file identifier is supplied;
- compatibility tests in Claude.ai custom connectors, Claude Desktop, the Anthropic Messages API MCP connector, ChatGPT, and MCP Inspector.

MCP resources may expose Norman documents back to a client, including binary resources, but they are a server-to-client read mechanism and are not a portable replacement for uploading a user's Claude attachment to Norman.

### 3. Payment-account and bank mapping

Allow agents to list connected financial accounts and map each bank, card, cash, or PayPal source to its Ledger account. Reconnection must identify an existing institution/account and must not leave duplicate expired-connection prompts.

### 4. Safe filing and annual-close previews

- expose E-Bilanz and annual-close preview/download operations;
- keep preview and submission as distinct tools;
- require an explicit, fresh confirmation immediately before tax submission or another irreversible external action;
- return actionable validation findings instead of raw ELSTER or taxonomy identifiers where possible.

### 5. VAT and ZM source parity

Keep tax treatment consistent across Norman transactions and non-transaction Ledger entries, including domestic VAT, EU and non-EU reverse charge, foreign VAT, Kleinunternehmer cases, split items, refunds, and Zusammenfassende Meldung (ZM). Preserve source links so an agent can explain how each report line was derived.

### 6. Payroll review

Add read and review tools for managing-director payroll, payroll runs, Ledger postings, and Lohnsteuer previews. Submission remains confirmation-gated.

### 7. Exports and audit handoff

- expose the Ledger GoBD audit export alongside the existing DATEV export;
- support period, account, and source filters without changing the legacy transaction export;
- return downloadable artifacts and progress for long-running export jobs.

### 8. Release integrity

Make Git tags, GitHub releases, PyPI, and `server.json` use one published version and add a verified package-release workflow. A registry manifest must never point to a package version that does not exist.

## P1: deeper bookkeeping workflows

- Cost centres (`Kostenstellen`) on transactions, split items, manual entries, Ledger views, and DATEV export
- Drill-through from reports and Ledger postings to the originating Norman transaction, asset, payroll run, or import batch
- Search, filters, and pagination parity across chart of accounts, journal, SuSa, open items, and cash book
- Product/service catalogue, custom units, prices, VAT defaults, and optional inventory tracking
- Batch document ingestion with durable progress, retries, dead-letter handling, completion webhooks/status events, and vendor/customer auto-upsert
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
