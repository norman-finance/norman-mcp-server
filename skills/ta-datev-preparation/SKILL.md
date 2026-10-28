---
name: ta-datev-preparation
description: Prepare a DATEV export for a German client company (Germany only). Verifies all transactions are categorized, receipts attached, DATEV settings configured, and triggers the export. Use when a tax advisor asks to prepare DATEV, export bookkeeping data, or send data to their tax software.
version: 1.1.0
metadata:
  openclaw:
    emoji: "\U0001F4E6"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the tax advisor prepare and execute a DATEV export:

## Step 1: Verify DATEV settings
- Call `get_company_details` to check current DATEV configuration
- Verify the following are set:
  - **Chart of accounts** (SKR03 or SKR04)
  - **DATEV advisor number** (Beraternummer)
  - **DATEV client number** (Mandantennummer)
- If any are missing, inform the advisor and offer to update via `update_company_details`

## Step 2: Check categorization completeness
- Call `search_transactions` with `status=UNVERIFIED` to find uncategorized transactions
- Report the count and total amount of uncategorized transactions
- If there are uncategorized transactions:
  - List the top items by amount
  - Offer to help categorize them using company categories (`list_company_categories`)
  - Warn that uncategorized transactions will be exported without a DATEV booking account

## Step 3: Check receipt completeness
- Call `get_missing_documents_summary` to identify transactions without receipts
- Focus on expense transactions >250 EUR (required for Vorsteuerabzug)
- Report the count and recommend collecting missing receipts before export
- Check `documentsWithoutBooking` for the export months: documents no booking holds are missing from the export, so the client books or deletes them first

## Step 4: Check changes since the advisor's last file
- Call `get_datev_changes_since_handoff` to compare each period the advisor already has a file of (a download by an advisor of the client, a DATEV push or an email to the advisor) with the books now
- For each period with new, changed or removed bookings, name them: the changed values as old → new (for example account 6640 → 6600), and why a booking left the file (deleted, no longer finalized, moved to another period)
- A changed period needs a new file; include it in the summary as an issue to resolve

## Step 5: Pre-export summary

### DATEV Configuration
- Chart of accounts: SKR03/SKR04
- Advisor number: ✅/❌
- Client number: ✅/❌

### Data Completeness
- Total transactions in period: X
- Categorized: X (Y%)
- With receipts: X (Y%)
- Ready for export: X (Y%)

### Issues to Resolve
List any blocking issues before export, and the periods that changed since the advisor's last file

## Step 6: Trigger export
- Only proceed if the advisor confirms
- Call `trigger_datev_export` to generate the DATEV EXTF CSV package
- The export includes:
  - DATEV EXTF CSV file (booking records)
  - Transaction statement
  - Attached documents
- Provide the download link from the response

## Step 7: Post-export
- Confirm the export was successful
- Remind the advisor to import the file into their DATEV software
- Norman keeps a record of each download, push and email; later changes to the period show in `get_datev_changes_since_handoff`

Tips:
- DATEV EXTF format is the standard for German tax advisors
- SKR03 is the most common chart of accounts; SKR04 is used by some industries
- Always verify advisor and client numbers match the DATEV installation
