---
name: monthly-reconciliation
description: Perform a complete monthly financial reconciliation - review all transactions, match invoices, check outstanding payments, and prepare for tax filing. Use when the user wants to close the month, do monthly bookkeeping, or perform a Monatsabschluss (zamknięcie miesiąca).
version: 1.1.5
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
- If the bank does not connect or its feed left days without bookings, ask for the bank's statement of the month. A PDF works (text or scanned): `import_bank_statement_pdf`, then `get_bank_statement_import` until it shows the statement, then `confirm_bank_statement_import` once the user approved the rows. Rows already in Norman are skipped. When the rows do not add up to the closing balance, tell the user and ask whether to import the recognized rows anyway (`import_despite_mismatch`)
- Identify uncategorized transactions
- For each batch, suggest categories and let the user confirm
- Use `categorize_transaction` to assign the correct bookkeeping category

## Step 2: Invoice Reconciliation
- Call `list_invoices` to find invoices from the period
- Cross-reference with incoming payments in transactions
- Use `link_transaction` to match payments to invoices. A German invoice is booked when it is issued; a payment of its whole open amount takes that booking over, and so does a payment that pays no other invoice and is within 3 % of the euro value of an invoice in another currency with no credit note and no earlier payment, at the bank's amount (a GmbH/UG books the difference as an exchange gain or loss). For a part payment pass `amount`: the rest stays open, and the invoice's `payments` shows what is paid and open. One transfer for several invoices is linked to each invoice with its own `amount`; an `amount` above what is open is capped, and the transfer keeps the rest. A payment that is not in the bank feed (cash, card, PayPal) is recorded with `record_invoice_payment`, which saves the payment and pays the invoice in one step.
- Where VAT follows the money (an EÜR company, or a GmbH/UG in a year it taxes on received remuneration), a correction that is settled with invoice lines of another VAT rate adds a booking without money on the correction's date: amount 0, `source=invoice`, lines that add up to zero. It moves the VAT from one rate to the other in that month. Norman makes and updates it. It is no payment: do not link, change, delete or finalize it.
- Flag any overdue unpaid invoices and suggest sending reminders via `send_invoice_overdue_reminder`

## Step 3: Open Bookings
- German companies book every document and invoice when it arrives. One that no payment has paid yet is an open booking: `search_transactions` with `payment=not_paid` lists them, `payment=partly_paid` the ones partly paid, `source=document` the ones Norman booked from documents. `openAmount` and `payments` say how much is paid. An invoice and its cancellation or credit note settle each other without a payment (`settledBy`): never pay or link what they settle. What a correction keeps open after that is a refund the client is owed: link the outgoing refund to the correction (`link_transaction`) or record it (`record_invoice_payment`).
- For each open booking, call `find_booking_payments`. Pay it with `pay_booking` and the payment's id: a payment of the whole open amount takes the booking over (one row, the document's date, the bank's payment date), and so does a payment that pays no other booking and is within 3 % of a booking in another currency that nothing has paid yet; pass `amount` for a part payment, and the rest stays open. A Norman invoice's booking is paid with `link_transaction` (Step 2).
- Paid with cash, a card, PayPal or a bank Norman does not see: `record_booking_payment` with the day, the method and the amount.
- A wrong match is undone with `unlink_payment` on the payment; the booking opens again.
- Bookings that stay open are unpaid bills or receivables: list them in the summary.

## Step 4: Document Check
- Search the period with `search_transactions` and `no_receipt=true`, without a status filter: reviewing a booking does not give it a document. Take the ones still to review first, as Norman's booking review does
- For a payment without a document, call `find_booking_payments` with its id. Pay a fitting open booking with `pay_booking`, then read back the row `pay_booking` returns (its `publicId`: the payment in German companies, the booking in Polish ones, whose payment then retires) and use that id from then on: a booking made by hand may have no document, so keep searching while it has none. A Norman invoice's booking (its `invoice` field in `get_transaction`) is paid with `link_transaction` (that invoice id, the payment id), never with `pay_booking`.
- Search `list_attachments` with `has_booking=false` and the supplier, and link a match with `link_attachment_transaction`
- `list_attachments` with `has_booking=false` and the period's `date_from`/`date_to` lists the documents that still wait for a booking
- Remind the user to upload missing receipts with `upload_bulk_attachments`
- In the app, **Buchhaltung → Prüfen** (Accounting → Review) works through these bookings one at a time, and **Belege → Belege prüfen** (Documents → Review documents) through the documents without a booking

## Step 5: Review the bookings
- Marking a booking reviewed (Geprüft) is the user's check. Mark the period's bookings reviewed with `change_transaction_verification` only when the user asked for it, after the matching steps: `pay_booking` refuses reviewed payments
- A booking that is not paid yet can be reviewed too; a later payment pays it and leaves it reviewed
- If any booking has missing information (no receipt, unclear category), flag it for the user before you mark it reviewed
- Never set a reviewed booking back to review on your own: only the user does that, one booking at a time
- Present a count: "X of Y bookings reviewed for [month]"

## Step 6: Tax Preparation
- Call `get_company_tax_statistics` for the period overview
- Call `get_vat_next_report` to check if a VAT report is due
- German companies: if the UStVA is due, call `generate_finanzamt_preview` to show the draft. Only submit with explicit user confirmation via `submit_tax_report`
- German companies: a late document keeps its legal date, also in a month whose UStVA is filed; for each filed UStVA of the period, `get_filed_report_changes` shows what changed per Kennzahl and whether a correction is due (§ 153 AO)
- Polish companies: if the JPK_V7 is due, find its report with `list_tax_reports` and read it with `get_polish_jpk_register` and `get_polish_jpk_filing_status`. There is no Polish submit tool: Norman files the JPK_V7 only after the owner approves and signs it in the Norman app

## Step 7: Hand the period to the tax advisor
- Only if the company works with a tax advisor (`ask_tax_advisor` refuses otherwise)
- Call `get_period_open_items` with the period's dates: it counts what the advisor still sees as open, the way the advisor's own list does
- Show the open items and offer to finish them first; the user may also send the period with them open
- Draft the message: the period is ready, and what is still open. Send it with `ask_tax_advisor` only after the user confirms the text

## Step 8: Summary
Present a closing summary:
- Total income and expenses for the month
- Number of invoices sent vs. paid
- Outstanding receivables, and open bookings that wait for their payment
- VAT liability
- Any action items remaining

Be thorough but keep each step interactive - wait for user confirmation before proceeding.
