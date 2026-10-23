---
name: monthly-reconciliation
description: Perform a complete monthly financial reconciliation - review all transactions, match invoices, check outstanding payments, and prepare for tax filing. Use when the user wants to close the month, do monthly bookkeeping, or perform a Monatsabschluss (zamknięcie miesiąca).
version: 1.1.1
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
- Open bookings (payment type `NOT_PAID`) are not finalized: they wait for their payment (Step 4)
- Mark every transaction for the period as verified so the month can be closed
- If any transaction has missing information (no receipt, unclear category), flag it for the user before verifying
- Present a count: "X of Y transactions verified for [month]"

## Step 3: Invoice Reconciliation
- Call `list_invoices` to find invoices from the period
- Cross-reference with incoming payments in transactions
- Use `link_transaction` to match payments to invoices. A German invoice is booked when it is issued; a payment of its whole open amount takes that booking over. For a part payment pass `amount`: the rest stays open, and the invoice's `payments` shows what is paid and open. One transfer for several invoices is linked to each invoice with its own `amount`; an `amount` above what is open is capped, and the transfer keeps the rest. A payment that is not in the bank feed (cash, card, PayPal) is recorded with `record_invoice_payment`, which saves the payment and pays the invoice in one step.
- Flag any overdue unpaid invoices and suggest sending reminders via `send_invoice_overdue_reminder`

## Step 4: Open Bookings
- German companies book every document and invoice when it arrives. One that no payment has paid yet is an open booking: `search_transactions` with `payment_type=NOT_PAID` lists them, `source=document` the ones Norman booked from documents. `openAmount` and `payments` say how much is paid.
- For each open booking, call `find_booking_payments`. Pay it with `pay_booking` and the payment's id: a payment of the whole open amount takes the booking over (one row, the document's date, the bank's payment date); pass `amount` for a part payment, and the rest stays open. A Norman invoice's booking is paid with `link_transaction` (Step 3).
- Paid with cash, a card, PayPal or a bank Norman does not see: `record_booking_payment` with the day, the method and the amount.
- A wrong match is undone with `unlink_payment` on the payment; the booking opens again.
- Bookings that stay open are unpaid bills or receivables: list them in the summary.

## Step 5: Document Check
- Call `list_attachments` for the period
- Identify transactions without attached receipts (especially expenses)
- Remind the user to upload missing receipts with `upload_bulk_attachments`
- Use `link_attachment_transaction` to connect any newly uploaded receipts

## Step 6: Tax Preparation
- Call `get_company_tax_statistics` for the period overview
- Call `get_vat_next_report` to check if a VAT report is due
- German companies: if the UStVA is due, call `generate_finanzamt_preview` to show the draft. Only submit with explicit user confirmation via `submit_tax_report`
- German companies: a late document keeps its legal date, also in a month whose UStVA is filed; for each filed UStVA of the period, `get_filed_report_changes` shows what changed per Kennzahl and whether a correction is due (§ 153 AO)
- Polish companies: if the JPK_V7 is due, find its report with `list_tax_reports` and read it with `get_polish_jpk_register` and `get_polish_jpk_filing_status`. There is no Polish submit tool: Norman files the JPK_V7 only after the owner approves and signs it in the Norman app

## Step 7: Summary
Present a closing summary:
- Total income and expenses for the month
- Number of invoices sent vs. paid
- Outstanding receivables, and open bookings that wait for their payment
- VAT liability
- Any action items remaining

Be thorough but keep each step interactive - wait for user confirmation before proceeding.
