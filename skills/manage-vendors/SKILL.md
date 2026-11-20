---
name: manage-vendors
description: Manage vendors (suppliers, Lieferanten, Kreditoren) - list, create, update, find duplicates and merge them. Use when the user mentions vendors, suppliers, Lieferanten, Kreditor numbers or duplicate vendors.
version: 1.1.0
metadata:
  openclaw:
    emoji: "\U0001F3EA"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the user keep one vendor per supplier:

## Listing and editing
- Call `list_vendors` to show the vendors. Present a table: Name, Kreditor number, IBAN, Documents
- Call `create_vendor` or `update_vendor` with only the fields the user gave
- A vendor with bookings or bills cannot be deleted. Offer to merge it into another vendor instead

## Vendors from documents
- For a company that keeps a ledger (every GmbH and UG, and a sole trader who moved to the ledger), Norman gives every expense document a vendor. It looks for the seller among the vendors by VAT number, IBAN and name. If none fits, it creates a vendor with the name, VAT number, IBAN and country of the document
- `fromDocument` is true for a vendor that Norman made this way and the user has not edited since
- If such a vendor is wrong, set the right vendor on the booking with `update_transaction`. When its last booking has moved, Norman removes the vendor and its Kreditor number is free again
- If such a vendor is a second spelling of an existing vendor, merge it

## Finding duplicates
- Call `list_vendor_duplicates`
- `groups` are own vendors that share a VAT number, an IBAN or a name. Show each group with its names and Kreditor numbers
- `suggestions` are own vendors that look like a suggested brand
- Each vendor carries its VAT number, IBAN, country, bookings and documents. Show them, so the user can judge
- If the user says a row holds different companies, call `mark_vendors_not_duplicates`. The row does not come back

## Merging
- Ask which vendor to keep before you call `merge_vendors`. A merge cannot be undone. Propose the vendor with the most bookings
- The kept vendor keeps its own name, VAT number and bank details. It takes the bookings, bills and rules of the others, and their names as aliases
- The merged vendors leave the list. Their Kreditor numbers are free for new vendors again
- Reviewed bookings and bookings in a closed year never move. If `skipped` is above 0, tell the user: that many bookings were skipped, and their vendor stays in the list with them
- If the answer lists `keptNumbers`, tell the user: these bookings stay on the old Kreditor number, because the tax advisor already has them
- For a `suggestions` row call `merge_vendor_with_suggestion`: the vendor takes the brand's logo and keeps all its own data
