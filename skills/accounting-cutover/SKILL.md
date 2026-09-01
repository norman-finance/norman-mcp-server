---
name: accounting-cutover
description: Analyze and migrate opening balances or prior DATEV books into Norman's SME Ledger. Use when a GmbH or UG is starting its books, changing accounting systems, importing DATEV opening balances, or performing an accounting cutover.
metadata:
  openclaw:
    emoji: "\U0001F4DA"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Guide a company through an accounting migration without changing its Ledger until the user has reviewed the preview and explicitly confirmed the import.

## 1. Inspect the current setup

- Call `get_accounting_setup` for the relevant fiscal year.
- Note the current SKR framework, existing cutover state and any previously imported entries.
- Do not switch SKR03 or SKR04 automatically. A framework switch has broader accounting consequences and requires its own explicit confirmation.

## 2. Collect and analyze source files

- Upload the available DATEV files or supporting documents and retain their short-lived `file_ref` values.
- Call `analyze_accounting_cutover_documents` with all related files together.
- Present the detected file roles, fiscal periods, likely SKR framework and any ambiguity to the user.
- Ask for a replacement file when a reference has expired.

File limits enforced by the Accounting API:

- 1 to 20 files per analysis
- 20 MB per file and 100 MB in total
- PDFs may be analyzed as supporting evidence, but opening-balance and booking-stack inputs for Preview and Apply must be machine-readable DATEV or CSV files

## 3. Choose the migration scenario

- `formation`: a newly formed GmbH or UG with legal opening entries
- `year_start`: prior-year closing balances become this year's opening balances
- `mid_year`: opening balances plus all bookings through the cutover date

Choose `opening_method=datev` when an opening-balance file exists. Choose `opening_method=manual` only when the user wants to enter non-zero account balances directly. Manual rows require `account_code`, `side` (`debit` or `credit`), `amount`, and may include `memo`.

## 4. Preview before writing

- Call `preview_accounting_cutover` with the complete set of dates, files and manual rows.
- Explain reconciliation totals, detected periods, blockers and warnings in plain language.
- Treat Preview as read-only. It does not write Ledger entries.
- Resolve every blocking finding before proceeding.

## 5. Apply only after explicit confirmation

- Ask the user to confirm the exact successful Preview.
- Call `apply_accounting_cutover` with the same inputs and `confirmed=true` only after that confirmation.
- If any date, file, balance row or migration mode changes, run Preview again before Apply.
- Apply writes opening/cutover postings and establishes the boundary before which transaction-derived postings must not be duplicated.

## 6. Verify the result

- Call `get_accounting_setup` again and inspect the returned import status and counts.
- Use the Ledger tools to verify the affected accounts and dates.
- Report any remaining warnings without attempting tax submission or annual-close locking.
