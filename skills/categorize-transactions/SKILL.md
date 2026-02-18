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

Help the user categorize and organize their bank transactions:

1. **Fetch uncategorized transactions**: Call `search_transactions` to find transactions that need attention. Look for unverified or uncategorized entries.

2. **Smart categorization**: For each transaction, suggest a category based on:
   - The transaction description / reference text
   - The counterparty name
   - The amount and pattern (recurring = likely subscription)
   - Similar past transactions

3. **Update transactions**: Use `categorize_transaction` to assign the correct bookkeeping category (SKR04 chart of accounts for German businesses).

4. **Invoice matching**: When a transaction looks like an incoming payment:
   - Call `list_invoices` to find matching unpaid invoices (by amount or client)
   - Use `link_transaction` to connect the payment to the invoice

5. **Document attachment**: Remind the user to attach receipts for expenses:
   - Use `upload_bulk_attachments` for multiple receipts
   - Use `link_attachment_transaction` to connect receipts to transactions

6. **Verification**: After categorizing, use `change_transaction_verification` to mark transactions as verified.

Present transactions in batches of 10-15 for manageable review. Show: Date, Amount, Description, Suggested Category.
