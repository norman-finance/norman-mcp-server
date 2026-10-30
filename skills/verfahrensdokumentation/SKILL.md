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

Help the user get their GoBD Verfahrensdokumentation.

## What it is
- Norman creates a PDF with the four GoBD parts: general description, user documentation, technical system documentation and operating documentation.
- Norman creates it fresh at each download from the company's current data, and asks the user nothing. It shows per year how many documents were captured, in how many months and by which channel, and who finalized how many bookings. It is not a Word file, and it is free on every plan.
- It stays the customer's own document. Nobody at Norman reviews it, and Norman holds no GoBD attestation. Never call Norman or its bookings GoBD-certified or unchangeable.

## Download
- The user downloads the PDF in the app: Export on the transactions page, turn on Download in GoBD format, then Verfahrensdokumentation. A GmbH or UG also finds it under Ledger, Export GoBD.
- There is no link to the PDF. Tell the user to keep each downloaded version as long as the records it explains.

## What the user adds
- The PDF covers only the work in Norman. The user describes the rest in their own document and keeps it with the PDF: what happens to paper originals, which systems they use outside Norman, and who does which task.
- Help them word it if they ask. Use only what the user states. Never guess a process for them.
