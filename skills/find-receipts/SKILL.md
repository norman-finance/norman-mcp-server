---
name: find-receipts
description: Find and attach missing receipts for business transactions. Search Gmail, email, or other sources for invoices and receipts, then upload them to Norman. Use when the user asks about missing receipts, Belege, attaching documents, or finding invoices from emails.
version: 1.0.0
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
- Call `search_transactions` to find recent transactions
- Call `list_attachments` to check which transactions already have receipts attached
- Present a list of transactions that are missing receipts, sorted by amount (largest first)

## Step 2: Search for receipts
Guide the user to find receipts from various sources:

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

## Step 4: Verify
- After attaching, use `change_transaction_verification` to mark transactions as verified
- Show a summary: how many receipts were found, attached, and how many are still missing

Tips:
- In Germany, receipts must be kept for 10 years (Aufbewahrungspflicht)
- Digital copies are legally accepted (GoBD-compliant) when stored properly
- Prioritize receipts for expenses over 250 EUR (required for Vorsteuerabzug)
