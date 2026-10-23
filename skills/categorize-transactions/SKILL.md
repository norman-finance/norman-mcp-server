---
name: categorize-transactions
description: Review and categorize uncategorized bank transactions, match them with invoices, and verify bookkeeping entries. Use when the user wants to review transactions, categorize expenses, do bookkeeping, or reconcile their bank account.
version: 1.2.0
metadata:
  openclaw:
    emoji: "\U0001F3F7"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the user categorize and organize their bank transactions.

## First: determine account type and country

Call `get_company_details` and check `isSme`, `country` and `usesCompanyChart`:
- **Freelance** (`isSme: false`, `usesCompanyChart: false`): Use `categorize_transaction` — AI detects the freelance category automatically.
- **JDG** (`isSme: false`, `country: PL`, `usesCompanyChart: true`): a Polish sole trader books on its own PL_KPIR chart, never on the freelance categories. Its tax book is the KPiR, or on the ryczałt the revenue register; the account decides the KPiR column. Use `list_company_categories` and assign the account with `update_transaction` (`company_category_id`).
- **GmbH / UG** (`isSme: true`, `country: DE`): Use `list_company_categories` to find DATEV categories by code. If the right category isn't provisioned, use `search_skr_by_code` or `suggest_skr_category` to search the full SKR catalog, then `create_company_category` to add it.
- **Sp. z o.o.** (`isSme: true`, `country: PL`): full books on the PL_FULL chart of accounts (Zakładowy Plan Kont), not a KPiR. Use `list_company_categories` with `chart_template: "PL_FULL"` and assign the account with `update_transaction`. The SKR tools are German and not available for it; if no PL_FULL account fits, ask the user which account to use.

## Workflow

1. **Fetch uncategorized transactions**: Call `search_transactions` to find transactions that need attention. Look for unverified or uncategorized entries.

2. **Smart categorization**: For each transaction, suggest a category based on:
   - The transaction description / reference text
   - The counterparty name
   - The amount and pattern (recurring = likely subscription)
   - Similar past transactions

3. **Assign the category**:
   - **Freelance**: Use `categorize_transaction` with the transaction details — it returns the AI-suggested freelance category.
   - **SME, or a JDG on its PL_KPIR chart**: Use `update_transaction` with `company_category_id` to assign the account. For a GmbH/UG, if the needed category isn't in `list_company_categories`, search the full SKR03/SKR04 catalog with `search_skr_by_code` (by number) or `suggest_skr_category` (by description, uses AI). Then `create_company_category` to add it.

4. **Same counterparty**: When the user corrects the category of one booking, call `find_same_counterparty_transactions` with that booking before you save its new category. Offer to change the `suggested` bookings too, and say how many finalized ones stay as they are. Change the ones the user agrees to with `update_transaction`. If the new category asks for details (trip dates, VAT period, business share, asset lifetime), change only the one booking.

5. **Invoice matching**: When a transaction looks like an incoming payment:
   - Call `list_invoices` to find matching unpaid invoices (by amount or client)
   - Use `link_transaction` to connect the payment to the invoice

6. **Document attachment**: Remind the user to attach receipts for expenses:
   - Use `upload_bulk_attachments` for multiple receipts
   - Use `link_attachment_transaction` to connect receipts to transactions

7. **Verification**: After categorizing, use `change_transaction_verification` to mark transactions as verified.

Present transactions in batches of 10-15 for manageable review. Show: Date, Amount, Description, Suggested Category.
