---
name: pl-office-month
description: Run a Polish accounting office's month across its clients (biuro rachunkowe) - whose JPK_V7 is ready, what is still to review, which documents are missing, whose KSeF is not connected - and prepare each JPK for its owner's approval. Use when a Polish office asks what is left this month, whose JPK is not ready, or to prepare the JPKs.
version: 1.1.0
metadata:
  openclaw:
    emoji: "\U0001F5D3"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the Polish accounting office through the month of all its clients:

## Step 1: The month across clients
- Call `list_polish_clients_jpk`. Per client: the open JPK period (`jpk`: JPK_V7M or JPK_V7K, dates, due date), the operations still to review (`unreviewedOperations`), the latest preparation (`jpk.run`: status, whether you prepared it, the owner's request for changes), whether you may prepare it (`canPrepareJpk`) and whether the client's plan includes it (`planIncludesJpk`)
- Call `list_client_deadlines` with `days` up to the month's end for the PIT and CIT advances, ZUS DRA and payroll lists due
- Order the clients: due soonest first, then those the owner sent back (`changesRequested`), then those not prepared yet
- `get_firm_team` says who in the office handles each client, if the office asks per person

## Step 2: What holds each client back
- Operations to review: name the count per client; the books are reviewed client by client, always with its `company_id`
- Missing documents: `get_missing_documents_summary` with the client's `company_id` and the month. Check `list_document_requests` first so a client is not asked twice, then ask several clients at once with `request_documents_from_clients` (or one with `request_documents_from_client`) after the office's yes
- KSeF: `list_client_ksef` lists the clients not connected. Where `canConnect` is true the office generates a token in the KSeF app in the client's context and connects it with `connect_client_ksef`. The token is a secret: take it only as pasted, never repeat it. `blocked: works` means the owner's own connection works and stays theirs
- `canPrepareJpk` false: the owner took the right away. `planIncludesJpk` false: the client's plan does not include preparing the JPK (JDG Pro and Sp. z o.o. Max do); only the owner chooses a plan. Say which, do not try another way; with the office's yes `ask_client_for_plan` (reason `books` or `filing`) asks the client to choose one

## Step 3: Prepare the JPKs for approval
- List the clients ready to prepare with their period and get the office's yes for the list
- Call `prepare_client_jpk` per client with its `company_id` and `jpk.reportId`. Preparing files nothing
- Follow each with `get_client_jpk_runs`: `ready_for_approval` waits for the owner, `needs_input` has `openBlockers` to name
- The owner approves in Norman or sends it back with a note; prepare again after the changes

## Step 4: Filing as the client's attorney
- Only with the owner's UPL-1 naming you: `filing` in `list_polish_clients_jpk`. A record you have not confirmed yet: `answer_client_power_of_attorney` with your PESEL. It is personal data: ask for it, use it once, never repeat it
- With an Autopilot run the owner approves the prepared JPK in Norman. Where `filing.mayFileWithoutApproval` is true you may approve it in their place: show the client, the period and the VAT to pay or carry forward (`previewSummary`), get an explicit yes, then `approve_client_jpk_for_owner` with `confirmed: true`. Approving sends nothing
- An attorney signs with their own qualified signature, never with the client's revenue. Read `get_polish_jpk_filing_status` with the client's `company_id` first: `attorney.blockReason` must be empty, otherwise relay `attorney.blockMessage`
- Step 1: `prepare_client_jpk_signing` gives `metadataFile`, a link to the XML valid for 10 minutes. The accountant signs that file as it is with their qualified signature, without opening and saving it in an editor (`get_client_jpk_filing_file` gives a new link)
- Step 2: `request_signed_jpk_upload` opens the uploader for the signed file; `get_file_upload_status` gives its `file_ref`
- Step 3: show the client, the period, the VAT and the attempt's `environment` ("test" never files), get an explicit yes, then `submit_client_jpk_signed` with `confirmed: true`. Follow with `refresh_polish_jpk_filing` (with `company_id`, `report_id`, `session_id`) until `accepted` (the UPO: `get_client_jpk_filing_file` with `kind: upo`) or `rejected` (quote MF's code and reason). Sending is not paying the VAT

## Step 5: Report
- One line per client: its name, the JPK state, what is left and who acts next (the office, the owner, Norman)
- Every result names its client in `activeClient`: use those names, never a guess
