---
name: verfahrensdokumentation
description: Help a German company with its GoBD Verfahrensdokumentation (process documentation). Use when the user asks for the Verfahrensdokumentation, a process documentation template, or what a tax audit expects about their process. Germany only.
version: 1.0.0
metadata:
  openclaw:
    emoji: "\U0001F4DD"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the user complete their GoBD Verfahrensdokumentation.

## What it is
- Norman creates a PDF with the four GoBD parts: general description, user documentation, technical system documentation and operating documentation.
- Norman creates it fresh at each download from the user's answers and the company's current data. It is not a Word file, and it is free on every plan.
- It stays the customer's own document. Nobody at Norman reviews it, and Norman holds no GoBD attestation. Never call Norman or its bookings GoBD-certified or unchangeable.

## Step 1: Read the saved answers
- Call `get_verfahrensdokumentation` and show which answers are still empty.

## Step 2: Ask only for what is missing
- Who captures documents in Norman, and who checks and finalizes the bookings.
- How often documents are captured and checked: daily, weekly or monthly.
- What happens to paper documents: none, originals kept (and where), or originals destroyed after capture.
- Which systems the company uses outside Norman, such as a till, a shop or a payroll program.
- Use only what the user states. Never guess a process for them.

## Step 3: Save
- Call `update_verfahrensdokumentation` with the answers the user gave. Norman logs each change, and the PDF lists them.

## Step 4: Download
- The user downloads the PDF in the app: Export on the transactions page, turn on Download in GoBD format, then Verfahrensdokumentation. A GmbH or UG also finds it under Ledger, Export GoBD.
- There is no link to the PDF. Tell the user to keep each downloaded version as long as the records it explains.
