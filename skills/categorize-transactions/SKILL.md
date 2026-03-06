---
name: categorize-transactions
description: Review and categorize uncategorized bank transactions, match them with invoices, and verify bookkeeping entries. Use when the user wants to review transactions, categorize expenses, do bookkeeping, or reconcile their bank account.
version: 1.0.0
metadata:
  openclaw:
    emoji: "\U0001F3F7"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the user categorize and organize their bank transactions.

## First: determine account type

Call `get_company_details` and check `isSme`:
- **Freelance** (`isSme: false`): Use `categorize_transaction` — AI detects the freelance category automatically.
- **SME / GmbH / UG** (`isSme: true`): Use `list_company_categories` to find DATEV categories by code. If the right category isn't provisioned, use `search_skr_by_code` or `suggest_skr_category` to search the full SKR catalog, then `create_company_category` to add it.

## Workflow

1. **Fetch uncategorized transactions**: Call `search_transactions` to find transactions that need attention. Look for unverified or uncategorized entries.

2. **Smart categorization**: For each transaction, suggest a category based on:
   - The transaction description / reference text
   - The counterparty name
   - The amount and pattern (recurring = likely subscription)
   - Similar past transactions

3. **Assign the category**:
   - **Freelance**: Use `categorize_transaction` with the transaction details — it returns the AI-suggested freelance category.
   - **SME**: Use `update_transaction` with `company_category_id` to assign a DATEV category. If the needed category isn't in `list_company_categories`, search the full SKR03/SKR04 catalog with `search_skr_by_code` (by number) or `suggest_skr_category` (by description, uses AI). Then `create_company_category` to add it.

4. **Invoice matching**: When a transaction looks like an incoming payment:
   - Call `list_invoices` to find matching unpaid invoices (by amount or client)
   - Use `link_transaction` to connect the payment to the invoice

5. **Document attachment**: Remind the user to attach receipts for expenses:
   - Use `upload_bulk_attachments` for multiple receipts
   - Use `link_attachment_transaction` to connect receipts to transactions

6. **Verification**: After categorizing, use `change_transaction_verification` to mark transactions as verified.

Present transactions in batches of 10-15 for manageable review. Show: Date, Amount, Description, Suggested Category.
