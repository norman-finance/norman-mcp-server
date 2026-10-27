---
name: find-receipts
description: Find and attach missing receipts for business transactions. Search Gmail, email, or other sources for invoices and receipts, then upload them to Norman. Use when the user asks about missing receipts, Belege, attaching documents, or finding invoices from emails.
version: 1.0.3
argument-hint: "[transaction description or vendor name]"
metadata:
  openclaw:
    emoji: "\U0001F4CE"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the user find and attach receipts to their transactions:

## Step 1: Identify transactions missing receipts
- Call `search_transactions` with `no_receipt=true` to find recent bookings that still need a document
- German and Polish companies: a payment without a document may pay an open booking that already holds its document. Call `find_booking_payments` with the payment's id first; a fitting open booking is the first candidate.
- A booking marked as needing no document is not missing one. Transfers between own accounts, private withdrawals and deposits, capital contributions and VAT payments to the tax office start that way in German companies. When the user says bookings need no document (payment-provider or bank fees), set `document_not_required=true` with `update_transaction`; for every future match, offer an automation rule with the `mark_document_not_required` action.
- Present a list of transactions that are missing receipts, sorted by amount (largest first)

## Step 2: Search for receipts
Guide the user to find receipts from various sources:

**Norman first:**
- `list_attachments` with `has_booking=false` and `search` for the supplier lists the uploaded receipts and invoices no booking holds yet.

**Gmail / Email:**
- Suggest searching Gmail with queries like:
  - `from:{vendor} subject:receipt` or `from:{vendor} subject:invoice`
  - `subject:Rechnung from:{vendor}`
  - `subject:Bestellbestätigung` (order confirmation)
  - `has:attachment after:{date} {vendor name}`
- For common vendors, suggest specific search terms:
  - AWS: `from:aws subject:"invoice available"`
  - Google: `from:payments-noreply@google.com`
  - Apple: `from:apple subject:receipt`
  - Amazon: `from:auto-confirm@amazon subject:Bestellung`

**Other sources:**
- Check vendor portals (suggest logging into the vendor's website to download invoices)
- Check cloud storage (Google Drive, Dropbox) for scanned receipts
- Check photo library for photos of paper receipts

## Step 3: Upload and attach
Once the user has the receipt files:
- Use `upload_bulk_attachments` to upload multiple receipts at once
- Use `create_attachment` for individual receipts with metadata (vendor, date, amount)
- Use `link_attachment_transaction` to connect each receipt to its matching transaction
- Pay a fitting open booking from `find_booking_payments` with `pay_booking` (booking id, payment id): the payment takes the booking over with its document
- German companies: a receipt that matches no payment books itself as an open booking (payment type `NOT_PAID`, source document) on its own date; its bank payment takes the booking over when it arrives. Linking a receipt to a booking made by hand replaces the booking Norman made from it.

## Step 4: Verify
- After attaching, use `change_transaction_verification` to mark transactions as verified
- Show a summary: how many receipts were found, attached, and how many are still missing

Tips:
- In Norman the owner works through the same lists one at a time: **Buchhaltung → Prüfen** (Accounting → Review) shows the unfinalized bookings, those without a document first, each with its matching bookings, payments and documents; **Belege → Belege prüfen** (Documents → Review documents) shows the documents no booking holds. Home shows both counts.
- DE: Receipts must be kept for 10 years (Aufbewahrungspflicht). Digital copies are legally accepted (GoBD-compliant) when stored properly. Prioritize receipts for expenses over 250 EUR (required for Vorsteuerabzug).
- PL: Receipts must be kept for 5 years. Documents must comply with JPK requirements. Prioritize receipts for expenses over 450 PLN (required for VAT deduction).
