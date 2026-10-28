---
name: calculators-and-forms
description: Calculate public what-if estimates or find and prepare Polish forms. Use for VAT/net/gross, JDG PIT/ZUS, depreciation, employment cost, company tax/dividends, payment requests and handover protocols. Triggers include kalkulator, oblicz, formularz, wezwanie do zapłaty, protokół przekazania, calculator, form generator, калькулятор, требование об оплате, акт передачи, розрахунок, вимога про оплату, акт передання.
argument-hint: "[calculation or document request]"
---

# Calculators and Polish forms

Use the existing Norman tools to complete the request. Respond in the user's language. The language does not establish tax jurisdiction. Do not ask again for facts already supplied in the conversation. If a named tool is absent from the app turn, discover its exact name with `search_available_tools` before calling it.

## Choose the right tool family

| User intent | Flow |
| --- | --- |
| Hypothetical amount, VAT conversion, B2B/JDG PIT/ZUS, depreciation, employment cost, CIT/dividend | `list_public_calculators` → `get_public_calculator` → `calculate_public_estimate` |
| Actual tax due or an existing declaration for the selected company | `list_tax_reports` → `get_tax_report`, or `get_polish_tax_estimates` where applicable |
| Create an invoice in the account | Existing `create_invoice` flow, not a letter template |
| Find an official Polish form or blank document | `list_polish_forms` → `get_polish_form` |
| Prepare a payment request or handover protocol | `get_polish_form` → `generate_polish_document` |

## Public calculations

1. Resolve requested country, year and legal form. Use existing company context only when the request concerns that company; a hypothetical Polish scenario must not be replaced with the selected German company's jurisdiction. Never change company selection for public arithmetic.
2. Read `get_public_calculator` for the chosen ID. Follow its live `inputSchema` and description; ask one concise question for missing required or conditional inputs, including user-confirmed tax regime, VAT rate or relief eligibility. The current catalog supports 2026 only. Never substitute it for an unsupported year.
3. Send only schema-declared numbers, booleans and enums, with nested numeric details when required. Amounts are major currency units. Do not send names, email, NIP/PESEL, tax identifiers, account IDs, documents or the whole conversation. Do not classify a ryczałt rate or determine relief eligibility for the user.
4. Execute `calculate_public_estimate`. Present the returned result with country/year/currency, material assumptions and the returned source link. Do not perform a second calculation using invented formulas. The result is an estimate, not a tax report, filing, eligibility decision or payment.

Known IDs: PL `pl_vat`, `pl_jdg_annual`, `pl_zus_monthly`, `pl_depreciation`, `pl_spolka_dividend`, `pl_sole_shareholder_zus`, `pl_employer_cost`; DE `de_vat`, `de_income_tax`, `de_self_employed`, `de_company_tax`, `de_trade_tax`, `de_depreciation`. Fetch the catalog to confirm availability and current inputs. An sp. z o.o. is not a JDG; shareholder ZUS is not company employer DRA. Annualized JDG illustrations are not monthly filing schedules.

## Forms and documents

1. Search in the user's supported language (`pl`, `en`, `ru`, `uk`). If a narrow query gives no results, broaden it or inspect a known form ID; do not conclude the feature is absent from one empty search.
2. `payment-request`: wezwanie do zapłaty, demand letter, требование об оплате, вимога про оплату. `handover-protocol`: protokół przekazania, handover, акт передачи, акт передання. Get the current version and required fields. Ask only for missing facts; never invent parties, dates, amounts or interest.
3. Prepare only on the user's request using `generate_polish_document` with that version and exact field keys. PDF is the default unless DOCX is requested. The file is Polish regardless of the chat language. Show the real preview/download returned by the tool. Say that the user reviews and signs; the bearer link expires after 10 minutes and anyone holding it can download it.
4. `upl-1`, `zaw-fa`, `vat-r`, `zus-dra` are official-source references only. Provide the current authority link and instructions; do not claim to fill, sign, send or file these forms. For the company's prepared ZUS DRA, use its report flow instead of the blank-form entry.

Preparation never sends a reminder, signs a document, files a declaration or pays money. A request to send an account invoice reminder belongs to the separate reminder tool and its own authorization, not this generator. Calculator and form requests do not authorize other account mutations.

If any service returns an error or 404, report the specific unavailable operation. Never fabricate a successful calculation, document or download URL. Refresh the schema after a version conflict; regenerate an expired document only if the user still wants it. A source-code registration alone is not evidence that a service is deployed.
