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

## 5. Prepare reviewed accounts (GmbH/UG)

Preview returns `accountReview` for GmbH/UG on SKR03/SKR04 (fiscal years 2024-2026). Its rows are source accounts that must exist and have an E-Bilanz position before import; they cause the "Review and prepare accounts" and "no E-Bilanz taxonomy mapping" blockers.

- Present each row with its state: `NEW` (will be created Ledger-only), `MAPPING_REQUIRED` (exists, needs a position), `CONFLICT` or `HIDDEN` (fix in the chart of accounts first; they cannot be prepared).
- Use `mode=AUTOMATIC` only where the row has `automatic=true`. Otherwise pick a `MANUAL` position from `accountReview.positions` matching the account type, or `DEFERRED` to decide later (the account then stays a blocker).
- Keep the name and type of existing accounts.
- After the user confirms, call `prepare_accounting_cutover_accounts` with `review_token`, the chosen rows and `confirmed=true`. The token expires after 30 minutes; if the API reports a changed or expired review, run Preview again.
- A single custom account can also be assigned directly: `update_chart_of_accounts_account` (or `create_chart_of_accounts_account`) with `ebilanz_assignment`; `get_ebilanz_positions` lists the allowed positions and `list_chart_of_accounts(fiscal_year=...)` shows each account's status.
- Run Preview again with the same inputs and confirm the blockers are gone.

## 6. Apply only after explicit confirmation

- Ask the user to confirm the exact successful Preview.
- Call `apply_accounting_cutover` with the same inputs and `confirmed=true` only after that confirmation.
- If any date, file, balance row or migration mode changes, run Preview again before Apply.
- Apply writes opening/cutover postings and establishes the boundary before which transaction-derived postings must not be duplicated.

## 7. Verify the result

- Call `get_accounting_setup` again and inspect the returned import status and counts.
- Use the Ledger tools to verify the affected accounts and dates.
- Report any remaining warnings without attempting tax submission or annual-close locking.
