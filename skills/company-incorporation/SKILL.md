---
name: company-incorporation
description: Found a German GmbH or UG (haftungsbeschränkt) through a guided chat. Use when the user wants to open, found or incorporate a company in Germany, start a GmbH/UG, prepare founding documents (Musterprotokoll, Gesellschafterliste) or find a notary for incorporation.
version: 1.1.0
disable-model-invocation: true
metadata:
  openclaw:
    emoji: "\U0001F3E2"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Guide the user through founding a German GmbH or UG (haftungsbeschränkt): collect the data,
generate pre-filled founding document drafts, and hand off to a notary.

## Ground rules

- **Never present anything as legal advice.** The generated documents are auto-filled
  templates (drafts) to prepare the notary appointment; the notary produces the binding
  versions. Say this whenever documents come up.
- The backend is the source of truth: every tool response carries `sections`
  (per-section `complete` + `missing`), `musterprotokoll` (`eligible` + `reasons`) and
  `status`. Navigate by `sections.missing`; never track progress yourself.
- Collect conversationally — one topic at a time, not a wall of questions.
- Amounts are full euros (§ 5 Abs. 2 GmbHG: nominal amounts in whole euros).

## Before you start

1. Call `get_incorporation`. If one exists, resume from the first incomplete section and
   summarize what's already collected. If not found, briefly explain the journey
   (data → documents → notary) and call `create_incorporation`. Save `publicId`.
2. Mention that personal data of the founders (name, DOB, address) will be collected to
   prepare the documents and the notary hand-off.

## Section 1 — Company (update_incorporation_company)

- Legal form: UG (haftungsbeschränkt) or GmbH. If the user is unsure: UG founds from 1 €
  capital but must retain earnings to build reserves; GmbH needs 25,000 € (half paid in
  before registration) and carries more weight with partners/banks.
  **Side effect worth mentioning:** choosing the legal form switches the user's Norman
  account to that corporate type with the SKR04 chart of accounts (out of the freelancer
  default), so bookkeeping and taxes are set up correctly from the start.
- Company name. The legal suffix is appended automatically. After saving, offer
  `check_incorporation_name` — it searches the Handelsregister for similar registered
  names. `status="unavailable"` means the portal couldn't be reached (say so; don't imply
  the name is free); matches mean a similar name may be rejected. Final say is the registry
  court + IHK.
- Business purpose (Unternehmensgegenstand): a short concrete sentence. If the user's
  wording is rough, offer `suggest_incorporation_purpose` — it returns a registry-ready
  rewrite; show it and let them accept or keep their own, then save via
  update_incorporation_company. Never auto-apply it.
- Registered office city (Sitz) is required; the street address can be skipped for now
  (`registered_address_skipped=true`) but is needed before notarization — mention Norman
  can help with a business address later.

## Section 2 — Shareholders (add/update/remove_incorporation_shareholder)

- Up to 3 shareholders for the statutory Musterprotokoll; natural persons (name, DOB 18+,
  nationality, residential address) or legal entities (Firma, Sitz, register court + number).
- Each shareholder takes a nominal amount (`share_nominal_amount`) — the amounts must sum
  to the share capital.
- Exactly one shareholder must be managing director (`is_managing_director=true` — setting
  it unsets others). Ask "who will be the managing director?" once all founders are in.

## Section 3 — Capital (update_incorporation_capital)

- UG: 1–24,999 €, fully paid in cash before registration.
- GmbH: ≥ 25,000 €; at least half (≥ 12,500 €) paid in before registration.

## Section 4 — Agreement (set_incorporation_agreement)

- If `musterprotokoll.eligible` is true, recommend `musterprotokoll` (statutory template —
  fastest and cheapest). Explain `individual` as the alternative.
- If not eligible, translate the `reasons` codes into plain language (e.g.
  `NOMINAL_SUM_MISMATCH` → "the shares don't add up to the capital") and either fix the
  data or set `individual` — the notary will draft an individual Satzung.

## Documents (generate_incorporation_documents)

1. Summarize ALL collected data and get explicit confirmation first.
2. Generate; share the download links. Use `get_incorporation_document_preview` to show
   the first page in chat.
3. Always add: these are drafts to prepare the notary appointment — not legal advice.
4. If the user changes data afterwards (`documentsStale=true`), offer to regenerate.

## Section 5 — Notary (update_incorporation_notary_preferences → match → request)

1. Collect: preferred city, online (DiRUG video notarization) vs in person, timeframe.
2. `match_incorporation_notaries` — present the matches; the user may pick one or none.
3. Confirm, then `request_incorporation_notary`. Explain: the Norman team coordinates the
   appointment and gets back to them — nothing is sent to a notary automatically.

## Formation roadmap (complete_incorporation_step)

Once the notary hand-off is requested, the record carries a `roadmap`: 7 founder-completable
steps (3-9 of the journey). Drive from `roadmap` (each has `done`/`active`); mark steps with
`complete_incorporation_step` (undoable). These are the founder's own checklist — they do not
send emails and never move the official `status` backwards.

**Whenever you present these next steps, send the user back into the product.** Point them to
their Norman dashboard — **https://app.norman.finance/** — and invite them to continue there.
The Home formation roadmap in the app shows exactly these remaining steps, adds bank-account
partner cards (Qonto/Vivid/Tide) for the deposit, and lets them tick each step done and ask
follow-up questions per step. Always close the incorporation chat with this invitation to open
the dashboard and track the rest of the founding.

1. `notary` — schedule the notary and sign the Articles.
2. `bank_account` — open a business account (needed for the deposit). Norman shows partner
   options (Qonto/Vivid/Tide) in the product.
3. `deposit` — deposit the share capital and send the bank statement to the notary.
4. `hrb` — get the HRB number from the Handelsregister (pass `register_number`/`register_court`).
   — after this the company is officially registered —
5. `finanzamt` — register with the Finanzamt (tax registration; the Fragebogen flow).
6. `gewerbeamt` — register with the Gewerbeamt.
7. `transparency` — register in the Transparency register.

The user can keep using Norman throughout; bookkeeping/invoicing/taxes already run on the
SKR04 account provisioned when the legal form was chosen.
