---
name: overdue-reminders
description: Find overdue invoices and send payment reminders (Zahlungserinnerungen / Mahnungen) to clients. Use when the user asks about unpaid invoices, overdue payments, payment reminders, Mahnung, or chasing payments.
version: 1.0.0
disable-model-invocation: true
argument-hint: "[client name or 'all']"
metadata:
  openclaw:
    emoji: "\u23F0"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the user manage overdue invoices and send payment reminders:

## Step 1: Find overdue invoices
- Call `list_invoices` to get all invoices
- Filter for invoices that are past their due date and still unpaid
- If `$ARGUMENTS` specifies a client name, filter to that client only
- Present a summary table: Client, Invoice #, Amount, Due Date, Days Overdue

## Step 2: Prioritize
Group overdue invoices by severity:
- **Gentle reminder** (1-14 days overdue): First reminder, friendly tone
- **Second reminder** (15-30 days overdue): Firmer tone, reference original due date
- **Final notice** (30+ days overdue): Urgent, mention potential consequences

## Step 3: Review before sending
For each overdue invoice (or batch per client):
- Show the invoice details: amount, due date, days overdue
- Show the client's contact info from `get_client`
- Let the user decide whether to send a reminder or skip

## Step 4: Send reminders
- Use `send_invoice_overdue_reminder` for each approved reminder
- Wait for user confirmation before each send

## Step 5: Summary
Present a final report:
- Total overdue amount across all clients
- Number of reminders sent
- Any invoices the user chose to skip (and why)
- Suggest scheduling a follow-up check in 7 days

Important:
- ALWAYS let the user review and approve each reminder before sending
- Never send reminders automatically without explicit confirmation
- In Germany, a Mahnung (formal dunning letter) has legal implications - make sure the user is aware
- Suggest checking if a payment was recently received but not yet linked (use `search_transactions`)
