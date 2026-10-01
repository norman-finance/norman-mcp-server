---
name: overdue-reminders
description: Find overdue invoices and send payment reminders (Zahlungserinnerungen / Mahnungen) to clients. Use when the user asks about unpaid invoices, overdue payments, payment reminders, Mahnung, or chasing payments.
version: 1.1.0
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

## Step 2: Check what Norman already sent
- Call `list_invoice_emails` for each overdue invoice. It lists every reminder with its level and status, and `nextReminder`, the reminder Norman's own rule sends next
- Leave out an invoice with a planned reminder (`nextReminder`, or an email with status `scheduled`) or a reminder sent in the last few days, unless the user asks for it by name
- An invoice with `remindersActive` true is reminded automatically by the company's rule. Say so instead of sending by hand

## Step 3: Levels
Norman keeps the reminder levels; a reminder sent by hand takes the level after the last one:
- **Payment reminder** (level 1): friendly tone
- **First dunning notice** (level 2): firmer, may carry a fee
- **Final notice** (level 3): last notice before further steps

## Step 4: Review before sending
For each overdue invoice (or batch per client):
- Show the invoice details: amount, due date, days overdue
- Show the client's contact info from `get_client`
- Let the user decide whether to send a reminder or skip

## Step 5: Send reminders
- Use `send_invoice_overdue_reminder` for each approved reminder
- Wait for user confirmation before each send
- Omit `subject` and `body`: Norman uses the company's template for that level in the invoice's language. Write your own text only when the user asks for it
- Pass `fee` only when the user names a dunning fee. The client pays a fee by bank transfer; a reminder with a fee has no online payment button
- A send that fails returns an error with the reason. Report it; do not say the reminder went out

## Automatic reminders
- To let Norman remind on its own, call `update_invoice` with `autoReminders: true`, after the user agreed. This also works for an invoice that is already issued. `remindersPaused: true` stops them for one invoice
- `get_invoice_email_settings` shows the rule (days after the due date and fee per level); change it with `update_invoice_email_settings` only when the user asks. Automatic reminders need a paid plan
- `skip_invoice_reminder` stops one planned reminder

## Step 6: Summary
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
