---
name: ta-client-period
description: Show which clients of a tax advisor need work in one month, quarter or year, the way the advisor's client list shows it. Use when a tax advisor asks which clients are open, ready or changed for a period, or what to do first this month.
version: 1.0.0
metadata:
  openclaw:
    emoji: "\U0001F4C5"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the tax advisor see all clients for one period:

## Step 1: Pick the period
- Use the period the advisor names. Without one, take last month
- Pass its first and last day to `list_clients_for_period` (a month, a quarter or a year)

## Step 2: Read each client
- `status` says where the client stands:
  - `changed`: the books changed after the advisor's DATEV file of this period
  - `missing_documents`: bookings of the period have no document
  - `in_progress`: bookings not finalized, or documents without a booking
  - `ready`: nothing open, no DATEV file yet
  - `handed_over`: the advisor has the DATEV file and nothing changed since
- `changed` and `missing_documents` need the advisor first; the list already sorts them on top
- `vatReturn` gives the UStVA of the period for a German company: `due` with the earliest open due date, `filed` with the newest filing date, or `none` (Kleinunternehmer, yearly filer or Polish client)

## Step 3: Present
- One line per client: name, status, the counts that are not zero, the DATEV file and, for a German company, the UStVA
- Then the next step for each client that needs the advisor:
  - `changed`: run `get_datev_changes_since_handoff` for the client and offer only the changes as a new file
  - `missing_documents`: offer `ta-missing-receipts` for the client
- Do not switch the active company or change anything without the advisor's request
