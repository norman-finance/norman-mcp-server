---
name: gewerbe-registration
description: Prepare a German trade-office registration (Gewerbeanmeldung, form GewA 1) through a guided chat. Use when the user wants to register a trade/business with the Gewerbeamt, file a Gewerbeanmeldung, or asks what to do after founding a GmbH/UG or finishing the tax registration (Fragebogen).
version: 1.0.0
disable-model-invocation: true
metadata:
  openclaw:
    emoji: "\U0001F3EA"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Guide the user through preparing their **Gewerbeanmeldung** (German trade-office registration,
official form GewA 1, § 14 GewO): collect the data across three sections and generate a
pre-filled PDF they submit themselves to their local Gewerbeamt.

## Ground rules

- **Who needs one:** Gewerbetreibende (a trade) and GmbH/UG founders. **Freiberufler**
  (freelance professions — doctors, lawyers, artists, many IT/consulting freelancers) do
  **not** file a Gewerbeanmeldung. If the user is clearly a freelance profession, say so and
  don't push the flow.
- **Never present anything as legal advice.** The output is an auto-filled template for
  self-submission; it is not e-filed and not legally reviewed. Say this when the document
  comes up.
- The backend is the source of truth: every response carries `sections` (basic / business /
  owner, each `complete` + `missing` camelCase field names) and `status`. Navigate by
  `sections.missing`; never track progress yourself.
- Collect conversationally — a few related fields at a time, not a wall of questions.

## Before you start

1. Call `get_gewerbe_registration`. If one exists, resume from the first incomplete section.
   A non-empty `documents` list means it's already generated. If not found, offer to start one.
2. If the user is founding a GmbH/UG and has an incorporation, pass its publicId to
   `create_gewerbe_registration` so company, address, activity and managing directors are
   pre-filled. For self-employed users the tax-registration (Fragebogen) answers are carried
   over automatically. Mention that personal data (name, DOB, address) is collected for the form.
3. Use `get_gewerbe_registration_choices` for the valid enum values.

## Section 1 — Basics (`update_gewerbe_basic`)

Start of activity (`activityStartDate`, no more than ~14 days in the future) and whether it's a
head office or a branch (`establishmentType`).

## Section 2 — Business (`update_gewerbe_business`)

Legal form, registered/business name, and — for legal entities (GmbH/UG/AG/…) — the commercial
register number. Type of business (any of industry/trade/craft/other), the Betriebsstätte
address + email, and a precise **activity description** (Feld 15). Offer `suggest_gewerbe_activity`
to sharpen the wording — show the suggestion and only apply it if the user accepts. Then the
conditionals: whether a licence/permit is required (+ authority and date), public-sector
participation, and employees (+ full-/part-time counts).

## Section 3 — Owner / representative (`update_gewerbe_owner`)

Personal data of the owner (sole proprietor) or the managing director (GmbH/UG): names, birth
name, DOB (≥18), place/country of birth, nationality, gender. Whether the home address is the
business address (`ownerAddressSameAsBusiness`) — if not, the residence address. Main vs
secondary occupation (`activityType`).

## Generate (`generate_gewerbe_document`)

1. Summarize all collected data and get explicit confirmation.
2. Call `generate_gewerbe_document` (400 + `missing` if a section is incomplete). Share the
   download link; use `get_gewerbe_document_preview` to show the first page.
3. Say clearly: this is a pre-filled template for self-submission — not legal advice. The PDF
   has a blank signature line to sign on paper (or sign it in the Norman product).
4. Call `get_gewerbe_trade_office` and tell the user which Gewerbeamt is responsible; if it
   returns `{"office": null}`, tell them to search for "<their city> Gewerbeamt". Remind them
   they'll need their ID and any required permits to submit.
