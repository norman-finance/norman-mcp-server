---
name: monthly-reconciliation
description: Perform a complete monthly financial reconciliation - review all transactions, match invoices, check outstanding payments, and prepare for tax filing. Use when the user wants to close the month, do monthly bookkeeping, or perform a Monatsabschluss.
version: 1.0.0
disable-model-invocation: true
argument-hint: "[month, e.g. January 2026]"
metadata:
  openclaw:
    emoji: "\U0001F4C5"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Guide the user through a complete monthly reconciliation:

## Step 1: Transaction Review
- Call `search_transactions` for the specified month (or last month if not specified)
- Identify uncategorized transactions
- For each batch, suggest categories and let the user confirm
- Use `categorize_transaction` to assign the correct bookkeeping category

## Step 2: Finalize Transactions
- After all transactions are categorized, verify each one using `change_transaction_verification`
- Mark every transaction for the period as verified so the month can be closed
- If any transaction has missing information (no receipt, unclear category), flag it for the user before verifying
- Present a count: "X of Y transactions verified for [month]"

## Step 3: Invoice Reconciliation
- Call `list_invoices` to find invoices from the period
- Cross-reference with incoming payments in transactions
- Use `link_transaction` to match payments to invoices
- Flag any overdue unpaid invoices and suggest sending reminders via `send_invoice_overdue_reminder`

## Step 4: Document Check
- Call `list_attachments` for the period
- Identify transactions without attached receipts (especially expenses)
- Remind the user to upload missing receipts with `upload_bulk_attachments`
- Use `link_attachment_transaction` to connect any newly uploaded receipts

## Step 5: Tax Preparation
- Call `get_company_tax_statistics` for the period overview
- Call `get_vat_next_report` to check if a VAT report is due
- If due, call `generate_finanzamt_preview` to show the draft
- Only submit with explicit user confirmation via `submit_tax_report`

## Step 6: Summary
Present a closing summary:
- Total income and expenses for the month
- Number of invoices sent vs. paid
- Outstanding receivables
- VAT liability
- Any action items remaining

Be thorough but keep each step interactive - wait for user confirmation before proceeding.
