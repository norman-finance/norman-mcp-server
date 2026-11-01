---
name: ta-client-period
description: Show which clients of a tax advisor need work in one month, quarter or year, the way the advisor's client list shows it. Use when a tax advisor asks which clients are open, ready or changed for a period, or what to do first this month.
version: 1.2.0
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
  - `changed`: the books changed after the advisor's DATEV file of this period, or after the advisor closed it
  - `missing_documents`: bookings of the period have no document
  - `in_progress`: bookings not finalized, or documents without a booking (an unpaid booking waits for its payment and does not count)
  - `ready`: nothing open, no DATEV file yet
  - `handed_over`: the advisor has the DATEV file, nothing changed since and nothing is open
  - `period_closed`: the advisor closed the period and nothing changed since
  - `closed`: bookkeeping is not opened for the advisor, so the list cannot say what is open
- `changed` and `missing_documents` need the advisor first; the list already sorts them on top
- `vatReturn` gives the VAT return of the period, the UStVA or the Polish JPK_V7: `due` with the earliest open due date, `filed` with the newest filing date, or `none`. A Kleinunternehmer or a VAT-exempt company has one only for a period with tax, such as reverse charge. A yearly filer normally has none
- `close` says whether the advisor closed the period and how many changes came after it. `year`, only for a calendar year, says whether the year is closed and what it still lacks
- `closedBlocks` names what the client or the firm has not opened for the advisor; those facts are null. Say so instead of reading them as zero

## Step 3: Present
- One line per client: name, status, the counts that are not zero, the DATEV file and the VAT return
- Then the next step for each client that needs the advisor:
  - `changed` with `close.changes`: run `get_client_period_close_changes` for the client, name the changes and offer `ta-month-close` to close the period again
  - `changed` with `file.changes`: run `get_datev_changes_since_handoff` for the client and offer only the changes as a new file
  - a null count means the comparison failed: say so and do not read it as zero
  - `missing_documents`: offer `ta-missing-receipts` for the client
  - a period the advisor is done with: offer `ta-month-close` for the client
- Do not switch the active company or change anything without the advisor's request
