# Polish accounting through MCP

Read `company://current` before a bookkeeping workflow. It identifies the selected
company, country, accounting currency, account type and chart. Original document
currency and operation date remain separate from accounting currency and payment
date. The API owns calculations, eligibility checks and permissions.

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

## Existing write tools

- Invoice items and operations preserve `vat_code`: `23`, `8`, `5`, `0`, `zw`,
  `np`, `oo`, or an explicit empty string. Do not infer an exempt, foreign supply
  or reverse-charge code from a numeric zero rate alone.
- `create_asset` and `update_asset` accept `polish_tax`, `opening_date`,
  `opening_book_value` and `bill_id`. The nested object follows API validation,
  including use date, method, annual rate, VAT recovery, KST/car classification,
  one-off amounts and confirmations. Confirmations are never set automatically.
- `get_vat_proportion` and `update_vat_proportion` expose the API's Polish VAT
  proportion settings. Use figures confirmed by the user; explicit clearing is
  different from omitting an input.
- Category creation and visibility use the company's own chart, including
  PL_KPIR, rather than assuming only GmbH/UG can use company categories.
- Public `create_attachment` no longer supplies EUR when currency is unknown.
  Pass the document currency when known; otherwise allow OCR to determine it.

German public tool names remain discoverable for existing clients. German
procedures reject Polish companies at invocation, while the internal MCP filters
German procedures when constructing a Polish company's tool inventory. Polish
resources and prompts do not advertise DATEV/SKR as Polish bookkeeping.

Advisor tax-compliance reads bind the explicitly requested client company to the
request header, without changing the shared client's selected company. Parallel
advisor reads therefore do not switch each other's company context.

## Delivery boundary

This change adds bookkeeping reads, diagnostics and export previews, plus missing
inputs on existing write tools. It does not add Polish manual journal writes,
statement generation/year closing, signatures or tax submission tools. Those
require a separate workflow using the existing API gates. A prepared/downloaded
XML, closed year or draft statement is not proof of MF/KRS filing. Confirm tax
acceptance and UPO before reporting a successful filing.

Tests exercise actual MCP argument/result validation with synthetic API responses,
company scoping, DE/PL behavior, VAT payloads, currencies and asset inputs. They do
not establish live OAuth, deployed API calculations, provider acceptance or UPO.
