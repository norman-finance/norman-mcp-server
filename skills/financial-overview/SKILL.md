---
name: financial-overview
description: Get a complete financial overview of the business including balance, recent transactions, outstanding invoices, and upcoming tax obligations. Use when the user asks about their financial status, dashboard, summary, or "how is my business doing?"
version: 1.0.0
metadata:
  openclaw:
    emoji: "\U0001F4CA"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Provide a comprehensive financial overview by gathering data from multiple sources:

1. **Company details**: Call `get_company_details` to get the business name and context
2. **Current balance**: Call `get_company_balance` to show available funds
3. **Recent transactions**: Call `search_transactions` with a recent date range (last 30 days) to show cash flow
4. **Outstanding invoices**: Call `list_invoices` and highlight unpaid or overdue ones
5. **Tax status**: Call `get_vat_next_report` to show upcoming tax deadlines and `get_company_tax_statistics` for the tax overview

Present the information in a clear, structured format:

- Start with the company name and current balance
- Show a brief income vs expenses summary from recent transactions
- List any overdue invoices that need attention
- Highlight upcoming tax deadlines
- End with actionable recommendations (e.g., "You have 3 overdue invoices totaling X EUR")

Use EUR currency formatting. Be concise but thorough.
