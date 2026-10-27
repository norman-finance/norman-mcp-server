# Polish public MCP sync — 23 October 2026

This change ports the callable Polish gaps identified in the website parity audit
to the public MCP. It does not deploy the server or prove that production API
endpoints have the same revision.

## Source revisions

- Public MCP baseline: `norman-finance/norman-mcp-server`, main `3555308`.
- Internal MCP and API contracts: `norman-finance/norman-finance-api`, develop
  `deefbbb83d017993e88f41eec1ebfb60346c30f2`, using committed source only.
- The 14 dedicated Polish accounting tools and Polish asset implementation were
  already identical and are unchanged. The port preserves public file transport,
  per-request company guards, result handling and OAuth behavior.

## Added and extended tools

| Area | Public tools | Behavior |
| --- | --- | --- |
| Ryczałt | `propose_tax_setting_change` | Adds `setting="ryczalt_rate"`, `revenue_category` and optional `lump_sum_rate`. Omit the rate to show Norman's default and its source for owner review. Stores a pending proposal, never applies the setting. |
| Document discovery | `list_attachments` | Adds supplier/reference search, date bounds, pagination and metadata-only results with `include_download_urls=false`. Default calls still enrich temporary download links. |
| Accounting history | `search_transactions`, `list_tax_reports` | Adds pagination and report period/type filters. Transaction amount bounds preserve zero. Uses the API's `page_size`, with a 20-row default for transaction search and an explicit limit of 1–100. |
| Proforma | `create_invoice`, `list_invoices` | Adds `quote_kind="proforma"` with `document_type="quote"`, selects the proforma number series, and filters by subtype. Number lookup failure prevents creation. Uses the existing quote-to-invoice conversion separately. |
| CSV imports | **`list_csv_import_jobs`**, **`rollback_csv_import_transactions`** | Inspects the exact import batch. Rollback defaults to preview; apply needs a valid batch UUID, explicit confirmation and the signed preview token. The API revalidates the token, ownership and immutable rows. |
| Incoming invoices | **`create_bill`**, **`scan_bill_document`**, `list_bills` | Records bills with explicit original currency, extracts fields from an existing company attachment, and pages the list. No bank account is required to record a bill. No Polish SEPA payment capability is added. |
| Workflow progress | **`request_workflow_input`**, `complete_workflow_step` | Pauses for a required user answer; can reopen a step with `done=false` without advancing. Existing `skipped` behavior and advance/error handling remain intact. Reopening does not undo accounting entries. |
| Detected routines | **`list_routines`**, **`confirm_routine`**, **`dismiss_routine`** | Shows detected proposals and records the user's decision. Does not silently create recurring invoices. |

Bold names are the **eight new tools**. Eight existing tools gain optional
arguments. No existing tool name or required argument is removed or renamed.

`list_attachments.linked` preserves the existing API's counterintuitive semantics:
`true` selects unlinked documents and `false` linked documents. The schema now says
this explicitly; omitting it searches both. All other document filters combine
with AND. Metadata-only search avoids a download-link request per receipt.

Bill OCR returns suggestions for review, including currency; check them against
the source document before creating a bill. The MCP create tool has no implicit
EUR fallback. The API currently may return EUR from OCR when currency is missing;
that is not confirmation that the document is in euros.

## Corrected audit findings and retained boundaries

- Internal `abandon_workflow`, `schedule_monthly_workflow` and `get_agent_digest`
  already have public equivalents: `stop_workflow`, `schedule_workflow` and
  `get_agent_week`. No duplicate aliases are added.
- Generic unscoped API routes receive the selected company via `X-Company-Id`,
  not a `companyId` query parameter. CSV, report, invoice and attachment URLs are
  also scoped by company. Server-side ownership checks remain authoritative.
- Public tax-setting proposals remain writes with an owner review link. PESEL
  and KSeF tokens remain excluded. The public `pl-tax-settings` skill is corrected
  to describe pending proposals, ryczałt, and the current ZUS start-date inputs.
- German ledger, year-close, incorporation, tax optimizer and SEPA tools remain
  guarded by the existing selected-company checks.
- The existing seven legacy wire signatures affected by optional arguments and
  descriptions are individually updated. Unrelated tool/resource/prompt hashes
  remain pinned. The Polish settings tool is newer than that legacy inventory.

Internal rule-draft canvas and custom workflow-manifest authoring are still
feature-gated and depend on the in-app review UI. They are not Polish-specific
parity gaps that can be exposed by copying registration. Existing public rule
preview/approval and workflow tools remain available.

JDG/CEIDG or S24 registration, a Polish tax-regime comparison tool, creation and
closure of Polish financial statements, and signing/submitting Polish returns
still require new MCP contracts in both implementations. This sync does not
advertise them as callable tools. Provider-specific online-payment controls and
in-app chat attachment handling are also outside this port.

## Validation

- `python -m pytest -q`: **925 passed**. The 82 existing SDK deprecation warnings
  concern `AuthSettings.validate_token_resource`; this sync does not change OAuth.
- `node --test tests/tax_filing_ui.test.cjs`: **3 passed**.
- Focused flake8 error checks (`E9,F63,F7,F82`) and `git diff --check` passed.
- Production MCP `tools/call` dispatch with synthetic responses covers optional
  arguments, validation errors, PLN/EUR bill recording, proforma numbering,
  proposal-only settings, metadata-only search, API refusals, missing companies,
  CSV preview/confirmation and workflow behavior.
- Local HTTP fixtures exercise the real API client for all six new tools using
  unscoped routes and assert `X-Company-Id` carries the selected company.
- The full Python suite also covers German/Polish country restrictions,
  per-token company isolation, OAuth, SDK 2, and legacy HTTP/stdio clients across
  four protocol versions. Node tax-preview checks cover confirmation behavior.
- These are local protocol/HTTP tests, not production writes, a live OCR run,
  tax submission, or a hosted ChatGPT installation. Test HTTP listeners close
  in fixture teardown; no application database or persistent server was started.
