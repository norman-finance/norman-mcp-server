---
name: tax-report
description: Review and manage German tax reports including VAT (Umsatzsteuer), income tax prepayments, and Finanzamt submissions. Use when the user asks about taxes, Steuern, VAT, USt, Finanzamt, or tax filing.
version: 1.0.0
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

Help the user with their German tax obligations:

1. **Overview**: Call `list_tax_reports` to see all tax reports and their statuses (draft, validated, submitted)

2. **Next deadline**: Call `get_vat_next_report` to show the next upcoming VAT filing deadline

3. **Specific report**: If the user asks about a specific period, call `get_tax_report` with the report ID to see details including:
   - Reporting period
   - Revenue and VAT amounts
   - Status (draft, ready, submitted)
   - Finanzamt submission status

4. **Preview before submission**: Call `generate_finanzamt_preview` to show the user exactly what will be sent to the Finanzamt. Let them review all figures.

5. **Submit**: Only when the user explicitly confirms, call `submit_tax_report` to file with the Finanzamt via ELSTER.

6. **Tax settings**: Call `list_tax_settings` to review VAT registration, filing frequency, and other tax configuration.

Important warnings:
- ALWAYS show a preview before submitting to the Finanzamt
- Tax submissions are IRREVERSIBLE - make sure the user explicitly confirms
- Remind the user of filing deadlines (monthly: 10th of following month, quarterly: 10th of following quarter month)
- If tax numbers need validation, use `validate_tax_number`
