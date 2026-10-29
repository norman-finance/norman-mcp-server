# Calculators and forms in the agent

The default MCP initialization instructions describe when to calculate a hypothetical estimate, read actual company reports or prepare a Polish business document. The `calculators_and_forms` MCP prompt provides the full workflow. The plugin source contains the same workflow as `skills/calculators-and-forms/SKILL.md`; publishing a plugin update is a separate step.

## Calculator contract

- `list_public_calculators(country)` lists the available PL/DE calculators.
- `get_public_calculator(calculator)` returns the live input schema and scope.
- `calculate_public_estimate(calculator, inputs)` validates the inputs and calls the existing public engine at `https://norman.finance/api/calculators`.

The adapter uses its own unauthenticated HTTP client, with no company token/header or environment proxy/netrc credentials. It does not copy formulas. Unknown fields, personal identifiers, unsupported years/countries, non-finite numbers and invalid decimal amounts are rejected before the calculation POST. Monetary inputs/outputs use major units. Returned source, assumptions, country, year, currency and estimate status are retained. Service errors remain tool errors.

The catalog currently has seven Polish calculators (VAT, JDG annual PIT/ZUS, monthly ZUS, depreciation, company/dividend, sole-shareholder ZUS, employer cost) and six German calculators (VAT, income tax, self-employed, company tax, trade tax, depreciation). Always read the live schema; the current engines support 2026 only. A hypothetical calculation does not access the selected company's books or create a report, filing or payment.

## Natural-language examples

| Request | Expected flow |
| --- | --- |
| Oblicz VAT z 361 zł brutto w Polsce w 2026, stawka 23% | `pl_vat` schema, then estimate with supplied values |
| Calculate Polish JDG tax on hypothetical annual revenue | `pl_jdg_annual` schema, ask for missing regime/eligibility/amounts |
| Przygotuj wezwanie do zapłaty w PDF | Current `payment-request` schema, then document generation |
| Generate a Polish handover protocol in DOCX | Current `handover-protocol` schema, then DOCX generation |
| Przygotuj wniosek o urlop wypoczynkowy | Current `annual-leave-request` schema; collect dates and parties; no approval of leave |
| Prepare a payment receipt | Confirm money was received, collect allocation and remaining amounts; use `payment-receipt` |
| Pokaż moją deklarację ZUS DRA za wrzesień | Existing company tax-report flow, not a public estimate or blank form |
| Utwórz fakturę dla klienta | Existing invoice workflow, not a payment-request letter |

[Forms contract and hosted prerequisites](polish-forms.md). Official form references do not fill or submit tax returns. A generated PDF/DOCX is for user review and signature; its download link expires after ten minutes.

## Verification and rollout

`tests/test_calculators.py` drives the production MCP SDK handler, checks that no company API calls occur, exercises strict input validation and errors, and checks prompt registration. The companion API change tests Polish and English discovery and follow-up context in the internal chat. These are deterministic contract tests, not a live-model conversation evaluation.

The website calculator API can be checked with synthetic numeric inputs without account data. Hosted chat use additionally requires deployment of the MCP/API changes and, for documents, the forms backend. Source registration and passing local tests do not prove those deployments.
