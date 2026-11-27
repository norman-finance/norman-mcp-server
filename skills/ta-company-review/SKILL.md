---
name: ta-company-review
description: Full company review for tax advisors. Generates a structured health report covering financials, document completeness, tax compliance, and action items. Use when a tax advisor asks for an overview, health check, or status of a client company.
version: 1.1.0
metadata:
  openclaw:
    emoji: "\U0001F50D"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Perform a comprehensive company review for the tax advisor:

## Before you start: the client
- Find the client in `list_tax_advisor_clients`: the clients your office has you handle (the lead first), or all of them if you see every client. Pass its `publicId` as `company_id` on every call: `switch_company` only sets the default for reads, and every write without `company_id` is refused (`client_required`)
- Each result names its client in `activeClient`: name it in your answer, and stop if it is not the client the advisor means
- A 403 `advisor_block_closed` means the office or the client keeps that part of the books closed for you: say which part, and that the office's owner or a manager (or the client, for what it granted) opens it

## Step 1: Gather all company data
- Call `get_client_overview` with the client's `company_id` to get an aggregated snapshot
- This returns company details, balance, transaction stats, tax reports, and outstanding invoices in one call

## Step 2: Check document completeness
- Call `get_missing_documents_summary` to identify all transactions without receipts
- Note the total missing count and the highest-value missing items
- Note `documentsWithoutBooking`: months with uploaded documents that no booking holds are incomplete in the books

## Step 3: Assess tax compliance
- Call `get_tax_compliance_status` to check report filing status and registration completeness
- Identify overdue or unfiled reports and missing tax registration details

## Step 4: Present the health report

Structure the output as follows:

### Company Profile
- Company name, type (freelancer, GmbH/UG, JDG or sp. z o.o.), chart of accounts
- Tax state (German companies), tax ID (Steuernummer or NIP), VAT ID status

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
2. High: large transactions missing receipts (>250 [currency])
3. Medium: uncategorized transactions
4. Low: missing tax registration details

Be specific with amounts, dates, and report periods. Use the company's currency for formatting.
