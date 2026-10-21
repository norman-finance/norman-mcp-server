---
name: expense-report
description: Generate a detailed expense breakdown by category for a given period. Use when the user asks for an expense report, spending summary, Ausgabenübersicht, cost analysis, or wants to understand where their money is going.
version: 1.0.1
argument-hint: "[period, e.g. January 2026 or Q1 2026 or 2025]"
metadata:
  openclaw:
    emoji: "\U0001F4B8"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Generate a comprehensive expense report for the user:

## Step 1: Gather data
- Call `search_transactions` for the specified period (default: last month)
- Filter for outgoing transactions (expenses only, exclude income)
- Call `get_company_balance` for current balance context

## Step 2: Categorize and group
Group expenses by bookkeeping category. For each category show:
- Category name
- Total amount (in the company's currency)
- Number of transactions
- Percentage of total expenses

Present as a ranked list, largest category first.

## Step 3: Top vendors
List the top 10 vendors/payees by total spend:
- Vendor name
- Total amount
- Number of transactions
- Average transaction amount

## Step 4: Trends and insights
If the user asks for a longer period (quarter or year), provide:
- Month-over-month comparison of total expenses
- Categories that increased or decreased significantly
- Recurring vs. one-time expenses
- Largest single transactions in the period

## Step 5: Comparison (if possible)
If data is available for the previous equivalent period:
- Total expenses this period vs. last period
- Percentage change
- Categories with the biggest increase/decrease
- Flag any unusual or new expense categories

## Presentation format
Structure the report clearly:

```
Expense Report: [Period]
========================
Total Expenses: X,XXX.XX [currency]

By Category:
  1. [Category]     X,XXX.XX [currency]  (XX%)  [N transactions]
  2. [Category]       XXX.XX [currency]  (XX%)  [N transactions]
  ...

Top Vendors:
  1. [Vendor]       X,XXX.XX [currency]  [N transactions]
  2. [Vendor]         XXX.XX [currency]  [N transactions]
  ...

Key Insights:
  - [Notable finding]
  - [Notable finding]
```

Keep amounts in the company's currency (EUR in Germany, PLN in Poland) and label it. Use clear formatting for readability. Offer to drill down into any specific category if the user wants more detail.
