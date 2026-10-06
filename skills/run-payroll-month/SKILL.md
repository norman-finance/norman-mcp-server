---
name: run-payroll-month
description: Run the monthly payroll (Lohnabrechnung) of a German GmbH or UG with Norman — check people and changes, calculate, approve, pay, Beitragsnachweis and Lohnsteuer-Anmeldung. Use when the user asks about payroll, Lohnabrechnung, Gehaltsabrechnung, salaries, payslips, Minijob, Midijob, Sozialversicherung, Beitragsnachweis or Lohnsteuer-Anmeldung.
version: 1.0.0
disable-model-invocation: true
argument-hint: "[month, e.g. 2026-12]"
metadata:
  openclaw:
    emoji: "\U0001F4B6"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Run one month of payroll with the user. Payroll is part of the Max plan and open to the company's owner and its tax advisor; a 403 means it is not available for this account.

1. **Where things stand**: Call `get_payroll_overview`, then `list_payroll_people`. Ask whether anything changed this month: a raise (`record_salary_change`), new tax data from ELStAM (`record_tax_profile_change`), a leaver (`set_employment_end`), vacation or sickness (`record_absence`). A new person, a Steuer-ID or insurance number is entered in the Norman app, never in chat.

2. **Calculate**: Call `calculate_payroll_month`. If it returns `issues`, explain them in plain words and say what to complete in the app (employer data, social insurance data, work schedule). Show each person's gross, taxes, social insurance and payout, and the employer cost.

3. **Approve**: Only after the user has reviewed the numbers and explicitly says so, call `approve_payroll_month` with the `revision` and `fingerprint` from the review they saw. The month is then booked and frozen; changes need `prepare_payroll_correction` and `approve_payroll_correction`.

4. **Social insurance**: `get_social_insurance_contributions` shows the amounts per Krankenkasse and the Minijob-Zentrale. Contributions are due on the third-last banking day of the month, and the Beitragsnachweis must reach each fund two working days earlier: save the estimate with `save_contribution_plan` in time (the first plan in Norman needs the user's confirmation). The user sends the Beitragsnachweis through the SV-Meldeportal; Norman does not transmit it.

5. **Pay**: `get_payroll_payments` lists net salaries, contributions and wage tax still due. Paying happens in the app (`payUrl`): one collective transfer the user confirms at the bank.

6. **Lohnsteuer-Anmeldung**: When every month of the filing period is approved, call `prepare_wage_tax_return`, show it with `get_wage_tax_return`, test it with `preview_wage_tax_return`, and only on the user's explicit request file it with `submit_wage_tax_return`. Due on the 10th of the following month. If it was filed elsewhere, use `mark_wage_tax_return_filed`.

7. **Documents**: `get_payslip` and `get_lohnkonto` return one-hour download links. `get_aag_claim` prepares the U1/U2 reimbursement after sickness or an employment ban.

Important:
- Approving, correcting and filing are binding: always show the numbers first and wait for an explicit yes.
- Never ask for or repeat a Steuer-ID, Rentenversicherungsnummer, IBAN or a diagnosis.
- Minijobs (up to €603 a month in 2026) go to the Minijob-Zentrale with the 2 % flat tax and carry no Lohnsteuer; midijobs (up to €2,000) use the reduced contributions of the transition zone automatically.
