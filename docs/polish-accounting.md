# Polish accounting through MCP

Norman MCP supports Polish **JDG** bookkeeping and **sp. z o.o.** full books
during the Polish soft launch. Connect through the same MCP endpoint as German
companies: `https://mcp.norman.finance/mcp`. No separate Polish MCP installation
is required. See [connection instructions](../README.md#-get-started).

## Select the company

Read `company://current` before a bookkeeping workflow. It identifies the selected
company, country, accounting currency, account type and chart. Original document
currency and operation date remain separate from accounting currency and payment
date. The API owns calculations, eligibility checks and permissions.

Use `list_companies` and `switch_company` to select an existing company, then read
its context again. A Polish-language conversation does not make a German company
Polish. JDG uses the Polish tax book; full-book tools require a `PL_FULL` chart.
Access also depends on the company's setup and API permissions.

## Reading and diagnosing books

| Tools | Scope / behavior |
| --- | --- |
| `get_polish_tax_book`, `get_polish_tax_book_operation` | Polish JDG: KPiR totals, entries and inclusion/exclusion reasons. Reads synchronize derived records; `readOnlyHint=false`. |
| `list_polish_ledger_journal`, `get_polish_ledger_entry` | PL_FULL postings and source/reversal information. Journal results are paginated. |
| `list_polish_ledger_accounts`, `get_polish_ledger_account` | PL_FULL chart and account sheets. Account-sheet entries are paginated. |
| `get_polish_trial_balance` | Complete PL_FULL trial balance for a period. This is not a bank balance. |
| `list_polish_financial_statements`, `get_polish_financial_statement` | Existing PL_FULL statements, workbook, statutory lines, XML issues and notes. |
| `preview_polish_accounting_export` | General, Optima or EPP compatibility preview, blockers and warnings. No export submission. |
| `get_polish_jpk_register` | JPK sales/purchases, totals and exclusions. |
| `get_polish_jpk_filing_status`, `get_polish_pit_filing_status` | Existing filing state and UPO availability. No signing or submission. |
| `get_polish_tax_estimates` | API PIT/ZUS or CIT estimates. May synchronize derived books; `readOnlyHint=false`. |

Each new tool captures the selected company once and uses that ID in the company
preflight, request URL and request header. Non-Polish companies are rejected;
PL_FULL tools also check the chart. Follow pagination before reporting complete
period results. An API error or absent amount is not a zero balance.

## Example workflows

### Explain a JDG's KPiR

Call `get_polish_tax_book` for the period:

```json
{"year": 2026, "month": 9}
```

Omit `month` for the whole year. The result contains the requested period rather
than one page. To diagnose one operation, call `get_polish_tax_book_operation`
with its actual `transaction_id`. Use the returned inclusion/exclusion reasons
before proposing edits; uploading a document or creating a bank payment alone
does not establish that an entry was included in the tax book.

These reads may synchronize derived entries and exchange differences. They do
not confirm operations or submit taxes. Keep the operation's `date` distinct
from `payment_date` and the document's OCR data when explaining the period.

### Review a spółka's full books

Start with `list_polish_ledger_accounts` and `get_polish_trial_balance`:

```json
{"date_from": "2026-07-01", "date_to": "2026-09-30"}
```

Use the returned chart codes with `get_polish_ledger_account`, or inspect
`list_polish_ledger_journal` with the same period and these optional filters:
`search`, `account`, `asset_id`, `page` and `page_size` (maximum 100).
Follow every page needed for the question. `get_polish_ledger_entry` accepts the
actual `entry_id` and exposes its source and reversal information.

For year-end review, call `list_polish_financial_statements`, then
`get_polish_financial_statement` with a returned `statement_id`. Inspect the
prepared workbook, statutory lines, notes and XML issues. These tools read
existing statements; they do not generate one, close the year or file with KRS.

### Inspect VAT and tax estimates

Find the existing report through `list_tax_reports`, then pass its real
`report_id` to `get_polish_jpk_register`. Review sales, purchases, totals and
excluded operations together. For a filing already started in Norman,
`get_polish_jpk_filing_status` returns methods, sessions, MF status and UPO
availability; `get_polish_pit_filing_status` reads the corresponding PIT state.
Neither tool signs or submits a return.

Call `get_polish_tax_estimates` with `year` and `month` for API-calculated
PIT/ZUS or CIT figures. Estimates are not filed returns. A missing value or a
failed calculation must be reported as unavailable, not zero.

### Check an accountant handoff

Call `preview_polish_accounting_export` with a period and one of `general`,
`optima` or `epp`:

```json
{
  "date_from": "2026-09-01",
  "date_to": "2026-09-30",
  "export_format": "optima",
  "include_files": true
}
```

The result contains compatibility findings, blockers, warnings and a snapshot.
This tool does not download a package or send it to an accounting system.
Review target database/register options with the accountant before handoff;
a successful preview does not prove an import into their software succeeded.

## Existing write tools

### Settings and sensitive identifiers

`propose_tax_setting_change` persists a pending proposal on each call. It is an
additive, non-idempotent write (`readOnlyHint=false`), not an applied settings
change. Give the owner the returned `openUrl` to review and apply it in Norman;
no public MCP tool applies the proposal or submits a declaration to an office.

PESEL and KSeF tokens must be entered directly in the authenticated Norman app.
The public proposal tool does not accept a PESEL field or setting. Business NIP
and EU VAT-number proposals remain available. `get_ksef_status` reports the
connection state, not the token. `search_polish_tax_offices` reads the available
offices so the owner can choose the correct one.

`lookup_polish_company` reads the selected sp. z o.o. in the KRS and on the
Ministry of Finance White list by its NIP or KRS number (none: the one Norman
holds) and persists one pending proposal per detail Norman lacks: the NIP,
`business_details` (REGON and seat address), `company_register` (KRS number,
register court, share capital and seat, which invoices must state under KSH
art. 206) and, for an active VAT payer, `vat_status`. It is the same additive,
non-idempotent write as `propose_tax_setting_change`; each proposal carries its
`openUrl`. A register that is down or out of its daily budget is named in
`company.sources`; the other one still answers.

### Invoices, assets and books

- Invoice items and operations preserve `vat_code`: `23`, `8`, `5`, `0`, `zw`,
  `np`, `oo`, or an explicit empty string. Do not infer an exempt, foreign supply
  or reverse-charge code from a numeric zero rate alone.
- `create_asset` and `update_asset` accept `polish_tax`, `opening_date`,
  `opening_book_value` and `bill_id`. The nested object follows API validation,
  including use date, method, annual rate, VAT recovery, KST/car classification,
  one-off amounts and confirmations. Confirmations are never set automatically.
- The opening balance of an sp. z o.o. on PL_FULL (bilans otwarcia from the previous
  books) goes through `get_accounting_setup`, `analyze_accounting_cutover_documents`,
  `preview_accounting_cutover` and `apply_accounting_cutover` with the trial balance
  (zestawienie obrotów i sald, CSV/XLSX) as `opening_file_ref`, or typed balances as
  `manual_balances`; no mode or dates. The preview maps each source account to
  PL_FULL and shows how; corrections go in `account_mapping`, assets taken over with
  their umorzenie in `takeover_assets`. Apply needs `confirmed=true` after the owner
  reviewed the preview. See the `pl-opening-balance` skill.
- `get_vat_proportion` and `update_vat_proportion` expose the API's Polish VAT
  proportion settings. Use figures confirmed by the user; explicit clearing is
  different from omitting an input.
- Category creation and visibility use the company's own chart, including
  PL_KPIR, rather than assuming only GmbH/UG can use company categories.
- Public `create_attachment` no longer supplies EUR when currency is unknown.
  Pass the document currency when known; otherwise allow OCR to determine it.

German public tool names remain discoverable for existing clients. German
procedures reject Polish companies at invocation (the accounting migration tools
above excepted), while the internal MCP filters
German procedures when constructing a Polish company's tool inventory. Polish
resources and prompts do not advertise DATEV/SKR as Polish bookkeeping.

Advisor tax-compliance reads bind the explicitly requested client company to the
request header, without changing the shared client's selected company. Parallel
advisor reads therefore do not switch each other's company context.

## Troubleshooting

| Response | What to check |
| --- | --- |
| `company_required` | Select an existing company before calling Polish tools. |
| `polish_company_required` | The selected company is not Polish; check `company://current`. |
| `polish_jdg_required` | The KPiR tool was called for a company using full books; use the Polish Ledger tools. |
| `polish_full_books_required` | The selected company does not use `PL_FULL`; check its accounting setup. |
| `german_company_required` | A German procedure was called for a non-German company; use the corresponding Polish tool where available. |
| API access or availability error | Check permissions, company setup and API deployment; do not reinterpret the error as an empty book. |

## Scope and verification

Polish MCP support includes bookkeeping reads, diagnostics and export previews,
plus Polish inputs on shared write tools. It does not expose Polish manual journal writes,
statement generation/year closing, signatures or tax submission tools. Those
require a separate workflow using the existing API gates. A prepared/downloaded
XML, closed year or draft statement is not proof of MF/KRS filing. Confirm tax
acceptance and UPO before reporting a successful filing.

Dedicated Polish tools return structured data. The German SKR Ledger Explorer,
Finanzamt preview, payroll and incorporation workflows are not Polish interfaces.
Availability in a hosted connection depends on both its MCP deployment and the
matching API endpoints, separately from repository or package metadata.

Tests exercise actual MCP argument/result validation with synthetic API responses,
company scoping, DE/PL behavior, VAT payloads, currencies and asset inputs. They do
not establish live OAuth, deployed API calculations, provider acceptance or UPO.

Implementation: [Polish tools](../norman_mcp/tools/polish_accounting.py),
[company guards](../norman_mcp/tools/country_scope.py),
[Polish asset inputs](../norman_mcp/tools/polish_assets.py), and
[protocol tests](../tests/test_polish_protocol.py).
