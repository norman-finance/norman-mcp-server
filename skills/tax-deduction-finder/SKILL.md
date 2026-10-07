---
name: tax-deduction-finder
description: Scan transactions for potentially missed tax deductions and suggest proper categorization. Use when the user asks about saving taxes, Steueroptimierung, deductible expenses, Betriebsausgaben, or wants to check if they are missing any write-offs.
version: 1.0.1
argument-hint: "[period, e.g. 2025 or Q4 2025]"
metadata:
  openclaw:
    emoji: "\U0001F50D"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the user find missed tax deductions by analyzing their transactions:

## Step 1: Gather data
- Call `search_transactions` for the specified period (default: current year)
- Call `get_company_details` to understand the business type
- Call `list_tax_settings` to check VAT status and tax regime

## Step 2: Scan for common deductions
Review each transaction and flag potential deductions that may be miscategorized or unverified. Look for these common German freelancer/small business deductions:

**Home office (Arbeitszimmer):**
- Rent, electricity, internet, heating proportional to office space
- Office furniture, equipment, monitors, desks

**Technology & software:**
- SaaS subscriptions (Adobe, Google Workspace, Slack, hosting)
- Computer hardware (fully deductible up to 800 EUR net, otherwise depreciated)
- Phone and mobile plans (business portion)

**Travel & transportation (Reisekosten):**
- Public transport, fuel, car maintenance
- Hotels for business trips
- Meals during business travel (Verpflegungspauschale, see flat rates below)

**Flat rates without receipts (DE sole proprietors):**
- Home office flat rate: 6 EUR per day worked mainly from home, at most 1,260 EUR a year; not on top of Arbeitszimmer room costs
- Travel meal allowance: 14 EUR per arrival, departure or over-8-hour day and 28 EUR per full day in Germany; country and city rates abroad (`get_flat_rates`)
- If the year has no "Home office flat rate" or "Travel meal allowance" entries, ask the user for the days; never guess them. With the user's go, add one entry per period (one per country for trips) with `create_transaction`, that category and the days in `category_metadata`. Norman calculates the amount.

**Professional development:**
- Courses, certifications, books, conferences
- Professional memberships and associations

**Insurance & financial:**
- Professional liability insurance (Berufshaftpflicht)
- Business bank account fees
- Tax advisor fees (Steuerberater)

**Marketing & client acquisition:**
- Advertising, domain names, hosting
- Business cards, printed materials
- Client gifts (up to 35 EUR per person per year)

## Step 3: Suggest corrections
For each potentially missed deduction:
- Show the transaction: date, amount, description, current category
- Suggest the correct SKR04 category
- Explain why it qualifies as a deduction
- Use `categorize_transaction` to recategorize if the user confirms

## Step 4: Estimate impact
Present a summary:
- Number of transactions reviewed
- Number of potential missed deductions found
- Estimated additional deductible amount (EUR)
- Approximate tax savings (rough estimate using ~30-42% marginal rate for Einkommensteuer + Soli)

Tips:
- Items up to 800 EUR net (GWG - Geringwertige Wirtschaftsgüter) can be fully deducted in the purchase year
- Items over 800 EUR must be depreciated over their useful life (AfA)
- Mixed-use items (e.g., phone) should only claim the business portion
- Keep receipts for all deductions - suggest attaching any missing ones
