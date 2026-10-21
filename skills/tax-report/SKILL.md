---
name: tax-report
description: "Review and manage tax reports. German companies: VAT (UStVA, ZM, Umsatzsteuer), income tax prepayments and Finanzamt submissions via ELSTER. Polish companies: the JPK_V7 and VAT-UE, PIT or CIT advances, ZUS DRA, the annual PIT and the CIT-8, which Norman prepares and the owner files in the Norman app or outside it. Use when the user asks about taxes, Steuern, podatki, VAT, USt, JPK, Finanzamt, urząd skarbowy, or tax filing."
version: 1.1.0
disable-model-invocation: true
argument-hint: "[period or tax type]"
metadata:
  openclaw:
    emoji: "\U0001F3E6"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the user with their tax obligations. Read the company's country first (`company://current` or `get_company_details`) and use its own terms: a German company has a UStVA and the Finanzamt, a Polish company the JPK_V7 and the urząd skarbowy, never the other one's.

1. **Overview**: Call `list_tax_reports` to see all tax reports and their statuses (draft, validated, submitted)

2. **Next deadline**: Call `get_vat_next_report` for the next VAT return: the UStVA of a German company, the JPK_V7 of a Polish VAT payer (a Polish company exempt from VAT files none). A Polish company's PIT or CIT advance and ZUS DRA, due on the 20th, are in `list_tax_reports`.

3. **Specific report**: If the user asks about a specific period, call `get_tax_report` with the report ID to see details including:
   - Reporting period
   - Revenue and VAT amounts
   - Status (draft, ready, submitted)
   - Submission status (the Finanzamt for a German report; the Ministry of Finance and its UPO for a Polish JPK_V7)

4. **German companies, preview and submit**:
   - Call `generate_finanzamt_preview` to show the user exactly what will be sent to the Finanzamt. Let them review all figures.
   - Only when the user explicitly confirms, call `submit_tax_report` to file with the Finanzamt via ELSTER. If it answers `Email not confirmed`, call `resend_email_confirmation` and ask the user to open the link in that email; a paid plan confirms the address without it.

5. **Polish companies, check and then file in the app**:
   - Read a JPK_V7's sales, purchases, totals and exclusions with `get_polish_jpk_register`, and its filing state (methods, MF status, UPO) with `get_polish_jpk_filing_status`; a PIT return's with `get_polish_pit_filing_status`. `get_polish_tax_estimates` gives PIT/ZUS or CIT estimates, which are not filed returns.
   - There is no Polish signing or submission tool here. Norman files the JPK_V7 (the monthly JPK_V7M, or each monthly file of a quarterly JPK_V7K) from the Norman app only after the owner approves and signs it, on the JDG Pro and Sp. z o.o. Max plans. Norman prepares the PIT returns, the CIT-8 draft and the VAT-UE and calculates ZUS; the user or their accountant files them.
   - Give facts and next steps, never an individual tax opinion.

6. **Tax settings**: Call `list_tax_settings` to review VAT registration, filing frequency, and other tax configuration.

Important warnings:
- German companies: ALWAYS show the Finanzamt preview before submitting
- Tax submissions are IRREVERSIBLE - make sure the user explicitly confirms
- Remind the user of filing deadlines:
  - DE: monthly: 10th of following month, quarterly: 10th of following quarter month
  - PL: JPK_V7M or JPK_V7K and VAT-UE: 25th of the following month; PIT and CIT advances and ZUS DRA: 20th of the following month; each moved to the next working day
- Reminders: for a German company Norman emails a reminder a week before and on the morning of each UStVA and ZM due date. For a Polish company Norman reminds of the JPK_V7, VAT-UE, PIT and CIT advances, ZUS DRA, annual PIT and CIT-8 a few days ahead and on the day, in the app, by push and by e-mail. To turn the reminders off or on again, set `notify_tax_deadlines` with `update_company_details`.
- If a German tax number (Steuernummer) needs validation, use `validate_tax_number` (Germany only)
