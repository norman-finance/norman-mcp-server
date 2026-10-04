---
name: run-workflow
description: Run a Norman workflow (month-end close, monthly reconciliation, VAT-return readiness, invoice to payment, client document requests) on Norman's servers, answer the questions it asks, and schedule it to run by itself. Use when the user asks Norman to close a month, reconcile the bank, get ready for the VAT return, or "do it every month".
version: 1.0.0
argument-hint: "[workflow, e.g. 'close August' or 'VAT return']"
metadata:
  openclaw:
    emoji: "\U0001F501"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Norman runs its workflows on its own servers. You start one, relay the user's answers, and report the result. You do not do the steps yourself.

## Step 1: Pick the workflow
- Call `list_workflows`. Match `$ARGUMENTS` or the user's words to a workflow key:
  - "close the month" → `month-end-close`
  - "reconcile" → `monthly-reconciliation`
  - "VAT return", "UStVA" → `vat-readiness`
- If a run of that workflow is already active, continue with it (Step 3) instead of starting another.
- Tell the user which steps it will take (the `steps` of the workflow) and for which period (`defaultScope`, or the month they named).

## Step 2: Start it
- Call `start_workflow` with the key. Pass `period_start`/`period_end` only if the user named a different period.
- Say that Norman is now working on it and will stop only if it needs them.

## Step 3: Follow the run
- Call `get_workflow_run` when the user asks how it is going. Do not poll in a loop.
- Act on `blockedReason`:
  - `user_input`: show the question from `blockedDetail`. Send the user's own answer with `answer_workflow_question`. Never answer on their behalf.
  - `manual_step`: explain the step's instruction. Once the user did it, or wants to skip it, call `complete_workflow_step`.
  - `source_required`: ask them to connect the bank or source in Norman, then `continue_workflow`.
  - `step_failed`: say what stopped it (from `blockedDetail`). Offer `continue_workflow` to try again.
  - `ai_limit` or `chat_limit_reached`: this month's AI messages are used up. The workflow can continue when the messages renew next month.

## Step 4: Report and offer the schedule
- When `state` is `done` or `done_with_warnings`, summarize each step's `summary` in plain words.
- If the workflow has no `schedule`, offer to run it by itself: month-end close on day 3, reconciliation on day 5, VAT readiness 5 days before the deadline. Only after the user agrees, call `schedule_workflow`.
- A refusal with code `automation_paid_feature` means automatic runs need a paid plan. Say so; running by hand stays free.

Important:
- Start, answer, schedule and stop only when the user asked.
- Invoice to payment and client document requests send to clients only when the user asked for sending. Confirm before you relay a "yes, send it".
- For "what did Norman do this week?", call `get_agent_week` and quote its numbers.
