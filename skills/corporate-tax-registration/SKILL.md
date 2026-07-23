---
name: corporate-tax-registration
description: Prepare the corporate tax registration (Fragebogen zur steuerlichen Erfassung for a GmbH/UG) through a guided chat. Use when a newly founded GmbH/UG needs its Steuernummer, the user asks what to do after the notary appointment, or wants to register the company with the Finanzamt. Final submission happens in the Norman app, not in chat.
version: 1.0.0
disable-model-invocation: true
metadata:
  openclaw:
    emoji: "\U0001F3E6"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Guide the user through the corporate **Fragebogen zur steuerlichen Erfassung** (tax
registration of a newly founded GmbH/UG, e-filed via ELSTER as FsE KapG): collect the data
across six sections, then hand over to the Norman app for the final submission.

## Ground rules

- **Who needs one:** every newly founded GmbH/UG must file it with its Finanzamt to receive a
  Steuernummer. Self-employed users (Einzelunternehmer, Freiberufler) use the regular
  tax-registration flow instead — do not mix the two.
- **The final submission happens in the Norman app, never in chat.** The e-filing to the
  Finanzamt is a binding legal act: when the data is complete, call
  `get_corporate_submission_link` and hand the user the link — they review the rendered ELSTER
  preview in the app and press Submit themselves. There is deliberately no submit tool.
- **Never present anything as legal or tax advice.** You help fill a form; the user is
  responsible for the content they submit.
- The backend is the source of truth: every response carries `sections` (company /
  registration / representatives / shareholders / financials / vatAndBank, each `complete` +
  `missing` camelCase field names) and `status` (data_collection → data_complete → submitted).
  Navigate by `sections.missing`; never track progress yourself.
- Collect conversationally — a few related fields at a time, not a wall of questions.

## Before you start

1. Call `get_corporate_tax_registration`. If one exists, resume from the first incomplete
   section; `status` == 'submitted' means it's already e-filed (`reportUrl` has the protocol).
   If not found, offer to start one.
2. If the company was founded through Norman, pass the incorporation publicId to
   `create_corporate_tax_registration` — company, notary date, capital, shareholders and
   managing directors are prefilled; only ask for what `sections.missing` still lists.
3. Use `get_corporate_tax_registration_choices` for the valid enum values.
4. In the Norman app the user can also upload their founding documents (notarized Satzung,
   Gesellschafterliste, HR excerpt) to prefill the form with AI — mention it when they have
   the papers at hand but no Norman incorporation.

## Section 1 — Company (`update_corporate_company`)

Firma exactly as notarized, legal form, Sitz, Geschäftsanschrift (+ separate management
address when `managementAddressSame` is false), contact data, Gegenstand des Unternehmens and
the responsible Finanzamt (4-digit BuFa number).

## Section 2 — Registration (`update_corporate_registration_details`)

Notarization date and the Handelsregister state: application filed / registered with dates,
Registergericht and the bare register number ('254739 B', without the HRB prefix).

## Sections 3+4 — People (`set_corporate_people`)

Managing directors (max 9) and shareholders (max 99, natural persons or legal entities with
nominal amounts; percents must sum to 100). Both lists use replace-all semantics: send the
complete list every time, or omit the parameter to leave it unchanged.

## Section 5 — Financials (`update_corporate_financials`)

Stammkapital (GmbH ≥ 25.000 €, UG 1–24.999 €), start of activity, divergent fiscal year and
expected profits for the founding and following year.

## Section 6 — VAT & bank (`update_corporate_vat_and_bank`)

Revenue forecast, the § 19 UStG Kleinunternehmer decision (waiving it binds for 5 years —
make sure the user understands before setting it), Soll-/Istversteuerung, whether to request
a USt-IdNr, and the refund bank account.

## Finish (`get_corporate_submission_link`)

1. When `sections.missing` is empty everywhere, summarize the collected data briefly.
2. Call `get_corporate_submission_link`; if `readyToSubmit` is false, finish the listed
   `missing` fields first.
3. Hand over the link and say explicitly: the final review and the Submit button are in the
   Norman app — after submitting there, the Steuernummer arrives from the Finanzamt by post,
   typically within 2–6 weeks.
