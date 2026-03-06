---
name: suggest-category
description: Find the right SKR account code for a bookkeeping category (SME only). Search the full SKR03/SKR04 chart of accounts by code or use AI to match by name or description. Use when an SME user needs help finding a category code, wants to add a new custom category, or asks "what account number is X?"
version: 1.0.0
metadata:
  openclaw:
    emoji: "\U0001F50D"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the user find the correct SKR chart of accounts category.

**IMPORTANT: SME accounts only.** This skill applies to GmbH/UG companies that use DATEV standard chart of accounts (SKR03/SKR04). For freelance accounts, use `categorize_transaction` instead — it has its own category set and AI detection.

## How to determine account type

Call `get_company_details` and check the `isSme` field:
- `isSme: true` → Use this skill (SKR tools below)
- `isSme: false` → Use `categorize_transaction` for freelance AI categorization

## Workflow

1. **Determine the search approach** based on what the user provides:
   - If they provide an **account number or prefix** (digits like `42`, `4200`, `6300`), use `search_skr_by_code` for instant CSV-based results.
   - If they describe a **category by name or purpose** (e.g. "office rent", "Reisekosten", "software subscriptions"), use `suggest_skr_category` which leverages OpenAI to semantically match against the full catalog.

2. **Show results clearly**: Present the matches with:
   - Account number (code)
   - German name (`nameDe`)
   - English name (`nameEn`)
   - Let the user pick the best fit.

3. **Check the company's existing categories**: Call `list_company_categories` to see if the desired category is already provisioned. If it is, inform the user — no need to create a new one.

4. **Create the category if needed**: If the user wants to add it, use `create_company_category` with:
   - The account code from the SKR catalog
   - The name (use the language the user prefers)
   - The cashflow type (INCOME or EXPENSE)
   - Optional German name and description

5. **Context**: The company's active chart of accounts (SKR03 or SKR04) determines which catalog is searched. You can check the current template via `get_company_details`.

## Tool summary

| Tool | For | What it does |
|---|---|---|
| `search_skr_by_code` | SME only | Fast CSV lookup by account number prefix |
| `suggest_skr_category` | SME only | AI (OpenAI) semantic search by name/description |
| `create_company_category` | SME only | Create a new custom DATEV category |
| `list_company_categories` | SME only | List categories already provisioned for the company |
| `categorize_transaction` | All accounts | AI detection for a specific transaction (freelance + SME) |

## Tips

- The full SKR catalog has ~1000+ entries — the tools handle search/filtering, don't try to list everything.
- Prefer `search_skr_by_code` over `suggest_skr_category` when possible (faster, no OpenAI cost).
- `categorize_transaction` is a *different* tool — it classifies a specific transaction. The SKR tools here help find/create account codes for the company's category setup.
- Common SKR04 ranges: 0xxx = assets, 1xxx = financial accounts, 2xxx = liabilities, 3xxx = income, 4xxx = material costs, 5xxx = depreciation, 6xxx = other expenses, 7xxx = extraordinary items.
