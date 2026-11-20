---
name: manage-clients
description: Manage business clients - list, search, create, or update client information. Use when the user mentions clients, contacts, customers, Kunden, or needs to manage their client database.
version: 1.2.0
metadata:
  openclaw:
    emoji: "\U0001F465"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the user manage their client database:

## Listing and searching
- Call `list_clients` to show all clients
- Present results in a clean table format: Name, Email, Phone, Outstanding balance

## Creating a new client
When creating a client with `create_client`, gather:
- **Required**: Client name (company or individual)
- **Recommended**: Email, phone, address (street, city, postal code, country)
- **Optional**: Tax ID (DE Steuernummer, PL NIP), EU VAT ID (DE USt-IdNr., PL NIP with the PL prefix), payment terms, notes
- For German businesses: ask about Kleinunternehmer status if relevant
- For Polish businesses: ask about the VAT exemption (zwolnienie podmiotowe z VAT) if relevant

## Updating a client
- Call `get_client` first to show current details
- Call `update_client` with only the fields that need changing
- Confirm changes with the user before updating

## Best practices
- Always verify client details before creating invoices
- For EU business clients, their EU VAT ID is needed for reverse charge invoices, the German ZM and the Polish VAT-UE
- Suggest cleaning up duplicate clients if detected

## Duplicates and merging
- Norman finds the client of an uploaded sales document by the VAT number first, then by the exact name, then by the name without legal form and punctuation or by an alias. A match by similar name or alias must agree in type (business or private), country and VAT number. If it does not agree, Norman creates a new client, so that no VAT figure changes
- If a client with exactly the same name has another VAT number or none, Norman creates a second client with the VAT number in its name, for example "Harbor Design GmbH (DE129273398)". If both are the same company, offer to correct the VAT number and to merge them
- Call `list_client_duplicates` to find clients that share a VAT number or a name. Show each client's VAT number, country, type, bookings and invoices, so the user can judge
- If the user says a group holds different companies, call `mark_clients_not_duplicates`. The group does not come back
- Ask which client to keep before you call `merge_clients`. A merge cannot be undone. Propose the client with the most bookings
- The kept client keeps its own name, VAT number, country and type. It takes the bookings, draft documents, recurring invoices and rules of the others, and their names as aliases
- Reviewed bookings, bookings in a closed year and issued documents never move. If `skipped` or `skippedDocuments` is above 0, tell the user how many stay, and that their client stays in the list with them
- A merge changes no VAT figure. If the API answers `different_tax_facts`, tell the user which client has another country, type or VAT number, and that these must be the same first
