---
name: ta-company-review
description: Full company review for tax advisors. Generates a structured health report covering financials, document completeness, tax compliance, and action items. Use when a tax advisor asks for an overview, health check, or status of a client company.
version: 1.0.0
metadata:
  openclaw:
    emoji: "\U0001F50D"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Perform a comprehensive company review for the tax advisor:

## Step 1: Gather all company data
- Call `get_client_overview` with the active company ID to get an aggregated snapshot
- This returns company details, balance, transaction stats, tax reports, and outstanding invoices in one call

## Step 2: Check document completeness
- Call `get_missing_documents_summary` to identify all transactions without receipts
- Note the total missing count and the highest-value missing items

## Step 3: Assess tax compliance
- Call `get_tax_compliance_status` to check report filing status and registration completeness
- Identify overdue or unfiled reports and missing tax registration details

## Step 4: Present the health report

Structure the output as follows:

### Company Profile
- Company name, type (freelancer/GmbH/UG), chart of accounts
- Tax state, tax ID, VAT ID status

### Financial Summary
- Current balance
- Total income and expenses
- Outstanding invoice count and total amount

### Document Completeness
- Total transactions vs. transactions with receipts
- Missing receipt count with percentage
- Top 5 highest-value transactions missing receipts

### Tax Compliance
- Filed vs. unfiled tax reports
- List of unfiled reports with periods and due dates
- Tax registration status (tax ID, VAT ID)

### Action Items
Prioritized list of recommended actions:
1. Critical: overdue tax reports
2. High: large transactions missing receipts (>250 EUR)
3. Medium: uncategorized transactions
4. Low: missing tax registration details

Be specific with amounts, dates, and report periods. Use EUR formatting.
