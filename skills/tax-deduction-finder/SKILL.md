---
name: tax-deduction-finder
description: Scan transactions for potentially missed tax deductions and suggest proper categorization. Use when the user asks about saving taxes, Steueroptimierung, deductible expenses, Betriebsausgaben, koszty uzyskania przychodu, or wants to check if they are missing any write-offs.
version: 1.1.0
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
Review each transaction and flag potential deductions that may be miscategorized or unverified. Look for common deductions based on the company's country:

**Home office (Arbeitszimmer):**
- Rent, electricity, internet, heating proportional to office space
- Office furniture, equipment, monitors, desks

**Technology & software:**
- SaaS subscriptions (Adobe, Google Workspace, Slack, hosting)
- Computer hardware and software (DE: fully deductible up to 800 EUR net; above that, written off in full in the year of purchase with the asset depreciation "In full in the year of purchase" (instant), BMF letter of 22 Feb 2022 / PL: fully deductible if under 10,000 PLN net, otherwise depreciated)
- Phone and mobile plans (business portion)

**Travel & transportation (Reisekosten):**
- Public transport, fuel, car maintenance (PL: for a car also used privately, 75% of its running costs count for PIT/CIT and 50% of the VAT is deductible; 100% only for a car used for business alone, with the VAT-26 filed and a mileage log: art. 23 ust. 1 pkt 46a PIT, art. 86a VAT)
- Hotels for business trips (PL: the cost counts for PIT/CIT, but the VAT on accommodation and restaurant services is not deductible: art. 88 ust. 1 pkt 4 VAT)
- Meals during business travel (DE: Verpflegungspauschale, see flat rates below / PL: dieta: 45 PLN per day for domestic travel)

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
- Client gifts (DE: up to 35 EUR per person per year)
- PL: representation costs are not deductible: entertaining clients or business partners, restaurant meals, food and drinks for them, and gifts meant to build the company's image (art. 23 ust. 1 pkt 23 PIT, art. 16 ust. 1 pkt 28 CIT); the VAT on restaurant services is not deductible either. There is no amount up to which they become deductible. Never suggest them as missed deductions; if the user sees an expense as advertising rather than representation, state the rule and leave the decision to them

## Step 3: Suggest corrections
For each potentially missed deduction:
- Show the transaction: date, amount, description, current category
- Suggest the correct SKR04 category (for a Polish company: an account of its own chart, PL_KPIR for a JDG or PL_FULL for an sp. z o.o.)
- Explain why it qualifies as a deduction
- Use `categorize_transaction` to recategorize if the user confirms

## Step 4: Estimate impact
Present a summary:
- Number of transactions reviewed
- Number of potential missed deductions found
- Estimated additional deductible amount (in the company's currency)
- Approximate tax savings (DE: ~30-42% marginal rate for Einkommensteuer + Soli / PL: 12% or 32% PIT on the tax scale or 19% on the linear tax; on the ryczałt costs do not lower the tax at all, only the VAT of a VAT payer; an sp. z o.o. pays CIT at 19%, or 9% as a small taxpayer meeting the conditions)

Tips:
- DE: Items up to 800 EUR net (GWG - Geringwertige Wirtschaftsgüter) can be fully deducted in the purchase year. Items over 800 EUR must be depreciated over their useful life (AfA).
- DE: Computer hardware, peripherals and software at any price may be written off in full in the year of purchase (instant): suggest it for a computer whose depreciation runs into later years.
- DE, GmbH/UG on SKR03/SKR04: a movable fixed asset that works on its own (an office chair, a desk) and costs up to 800 EUR net per item goes on the GWG write-off account (SKR03 4855, SKR04 6260). Consumables, services and goods for resale keep their own accounts. "Equipment & office rental" (SKR03 4960, SKR04 6835) is rent.
- PL: Items under 10,000 PLN net can be fully deducted in the purchase year. Items over 10,000 PLN must be depreciated (amortyzacja).
- Mixed-use items (e.g., phone) should only claim the business portion
- Keep receipts for all deductions - suggest attaching any missing ones
