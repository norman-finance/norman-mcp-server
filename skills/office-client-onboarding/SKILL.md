---
name: office-client-onboarding
description: Bring new clients into an accounting office - add one, import a list of Polish NIPs checked on the White list, start a new sp. z o.o. or JDG for a Polish client, set each client's taxes up, invite each owner to take their company over within 7 days, and ask a client to choose a plan. Use when an office has new clients, pastes a list of NIPs or a client list, founds a company for a client, or asks which owners have not joined.
version: 1.1.0
metadata:
  openclaw:
    emoji: "\U0001F4E5"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the office bring its clients in. Only the office's owner or a manager adds and imports clients, and only clients of the office's own country:

## Step 1: Know the clients
- One client: ask for the name, the legal form, the tax number (NIP in Poland, Steuernummer in Germany), the address, the owner's name (required for a sole trader) and, if the office has it, the owner's e-mail
- A list of Polish NIPs: call `look_up_polish_clients` (up to 100 per call). It writes nothing; `found` rows bring the name, address and `legalForm` (KRS: sp_z_oo, otherwise jdg). Name the rows that are `invalid`, `duplicate`, `already_client` or `not_found` (a sole trader exempt from VAT often is not on the White list: ask the office for its details). `unavailable`: try later
- Show the office the clients as they will be added

## Step 2: Set their taxes up
- Ask what onboarding would ask the owner: `vat_status` (vat or exempt) and `vat_frequency`; a Polish JDG's `tax_regime` (progressive = skala, flat = liniowy, ryczalt) and `zus_relief`; a Polish sp. z o.o.'s CIT rate (`cit_small` 9%, `cit_standard` 19%)
- A Polish client's books in Norman start in `bookkeeping_start`'s month, this month by default: earlier months stay with whoever kept them

## Step 3: Add them, with the office's yes
- One client: `add_client`. A list: `import_clients`, at most 10 rows per call; send a longer list in parts and report each part's `created`, `skipped` and `failed` rows with their errors
- The caller becomes each new client's lead; `office-team` covers giving clients to colleagues

## Step 4: The owners take over
- With `owner_email` the owner is invited at once; later with `invite_client_owner` (also to send again)
- The invitation is open for 7 days. If the owner does not take the company over by then, the office stops keeping the client the next night and the company is archived, not deleted. Say this when you invite
- `get_firm_team` lists the owners who have not joined (`ownersNotJoined`) with their invitation's end. Invite again before it ends, or `cancel_client_owner_invitation`: a client without an open invitation is not removed
- An owner who already keeps the same company on Norman connects it from the invitation instead; an accountant's address is refused

## Step 5: A company the office starts for its client (Poland)
- A Polish office starts a new sp. z o.o. or JDG with `start_client_company`: the legal form, the working name and the person who takes it over (a JDG's entrepreneur, an sp. z o.o.'s president or main founder), with their e-mail to invite them
- The office fills the registration draft in Norman, on the client's company founding page. The people's own acts stay theirs and happen outside Norman: the founders sign in S24, the board files the KRS application, the entrepreneur files the CEIDG-1, the board reports to the CRBR. Norman submits nothing there
- While the company is being founded (`founding.stage` in `list_tax_advisor_clients`) it has no deadlines, and a lapsed invitation does not remove it

## Step 6: The client's plan
- `plan` in `list_tax_advisor_clients` says what each client is on. The office never buys or quotes a plan: the client chooses and pays
- Where `plan.canRequest` is true and the office needs it (books, taxes and JPK, or filing), `ask_client_for_plan` with the reason and a short note, after the office's yes
