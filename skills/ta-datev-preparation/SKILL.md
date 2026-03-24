---
name: ta-datev-preparation
description: Prepare a DATEV export for a client company. Verifies all transactions are categorized, receipts attached, DATEV settings configured, and triggers the export. Use when a tax advisor asks to prepare DATEV, export bookkeeping data, or send data to their tax software.
version: 1.0.0
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

## Step 4: Pre-export summary

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
List any blocking issues before export

## Step 5: Trigger export
- Only proceed if the advisor confirms
- Call `trigger_datev_export` to generate the DATEV EXTF CSV package
- The export includes:
  - DATEV EXTF CSV file (booking records)
  - Transaction statement
  - Attached documents
- Provide the download link from the response

## Step 6: Post-export
- Confirm the export was successful
- Remind the advisor to import the file into their DATEV software
- Suggest marking the period as exported to avoid duplicate exports

Tips:
- DATEV EXTF format is the standard for German tax advisors
- SKR03 is the most common chart of accounts; SKR04 is used by some industries
- Always verify advisor and client numbers match the DATEV installation
