---
name: ta-month-close
description: Close, reopen or check a German client's VAT period for a tax advisor, and read the state of its year. Use when a tax advisor says a month, quarter or year is done, asks what changed after a close, or asks whether a year is closed.
version: 1.0.0
metadata:
  openclaw:
    emoji: "\U0001F512"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the tax advisor close a client's period:

## Step 1: Find the period
- Call `list_clients_for_period` with the period the advisor names. Without one, take last month
- `close.period` is the client's VAT period that closes from here: the month of a monthly filer, the quarter of a quarterly filer, otherwise the year. If it is null, the picked period spans several VAT periods: ask which one
- `close.canChange` is false while the period runs or when the advisor may not write bookings. Say so

## Step 2: Name what is open
- Name the open items of that VAT period: `documentsWithoutBooking`, `missingDocuments` and `openBookings`
- Open items never block the close. Say this plainly and let the advisor decide

## Step 3: Close, with the advisor's yes
- This is a write. Ask first, then call `close_client_period` with the client and the VAT period
- Closing keeps a record of the bookings and documents the period holds now. It locks nothing: the client can still change the period and sees nothing of the close
- A late document keeps its legal date, also in a closed period

## Step 4: Changes after the close
- `close.changes` counts the changes since the close. `get_client_period_close_changes` names them: new, changed and removed bookings, and new documents
- To accept them, close the period again with the advisor's yes: it takes a new record
- Call `reopen_client_period` only when the advisor asks for it

## Step 5: The year
- Pick the calendar year: `year.closed` and `year.missing` give its state
- A self-employed year is closed when its last period is closed and the EUeR and, where due, the annual VAT return are filed. There is no extra step to close it
- A GmbH's or UG's year is closed when its annual close is locked: use `annual-close`. Its months read as closed then, and they do not reopen here
- In a GmbH's or UG's closed year, whatever arrives late books on the first open day and its VAT keeps the legal month
