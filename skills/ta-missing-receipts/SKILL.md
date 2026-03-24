---
name: ta-missing-receipts
description: Find and collect missing receipts for a client company. Identify high-priority items, suggest a ping strategy, and bulk-notify the client. Use when a tax advisor asks about missing documents, Belege, or requests receipts from a client.
version: 1.0.0
metadata:
  openclaw:
    emoji: "\U0001F4CE"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the tax advisor identify and collect missing receipts from a client:

## Step 1: Get the missing documents summary
- Call `get_missing_documents_summary` with the active company ID
- This returns all transactions without receipts grouped by month with amounts

## Step 2: Analyze and prioritize
Present the results in a structured format:

**By priority:**
1. **Critical** (>250 EUR) — required for Vorsteuerabzug
2. **High** (100–250 EUR) — significant business expenses
3. **Medium** (<100 EUR) — should be collected for compliance
4. **Informational** — small amounts that may be bundled

**By month:** Show which months have the most gaps

**By category:** Group by category to help the client understand what types of documents are needed

## Step 3: Suggest a ping strategy
- Recommend which transactions to ping the client about first (highest amount, oldest first)
- Suggest grouping pings by vendor or category to make it easier for the client
- Warn if the total missing count is very high (suggest batching requests)

## Step 4: Send reminders
- Ask the tax advisor to confirm before sending
- Call `ping_client_for_documents` with the selected transaction IDs
- Report how many reminders were sent successfully

## Step 5: Summary
- Show total missing documents before and after action
- Recommend a follow-up date to check again
- Remind about the 10-year retention requirement (Aufbewahrungspflicht)

Tips for the advisor:
- In Germany, receipts are mandatory for Vorsteuerabzug on expenses >250 EUR
- Digital copies are GoBD-compliant when stored properly in Norman
- Consider requesting receipts monthly to avoid large backlogs
