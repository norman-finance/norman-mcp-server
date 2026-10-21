---
name: pl-tax-settings
description: A Polish JDG or sp. z o.o. reads or changes its tax settings in Norman (forma opodatkowania, stawka CIT, ZUS, status VAT, JPK_V7M/K, metoda kasowa, proporcja VAT, NIP, numer VAT UE, PESEL, data rozpoczęcia, urząd skarbowy, przypomnienia, KSeF). Every change is a proposal the owner applies in Norman. Facts only.
version: 1.0.0
disable-model-invocation: true
argument-hint: "[setting]"
metadata:
  openclaw:
    emoji: "⚙"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the owner of a Polish company with its tax settings in Norman.

1. **Read first**: `get_company_details` (tax form, ZUS, cash method, NIP, EU VAT number, start date, reminders) and `list_tax_settings` (this year's VAT status and JPK_V7 frequency). For KSeF call `get_ksef_status`; for the VAT proportion `get_vat_proportion`.

2. **Explain with facts**: what Norman does with the setting (which returns, advances and contributions it works out from it, which JPK file it prepares, the deadlines) and how the owner checks it: the tax form in CEIDG, the VAT status in the VAT register (Biała lista), ZUS in PUE ZUS (ePłatnik).

3. **Never recommend**: do not choose or advise a tax form, a CIT rate or a ZUS scheme for the owner, and do not say which one is cheaper for them. State the rules and the owner's own figures; the owner decides.

4. **Change only as a proposal**: when the owner asks for a change, call `propose_tax_setting_change` with one setting per call. It writes nothing, and Norman does not take these settings from an AI client directly. Give the owner the returned `openUrl`: it opens Norman's tax settings with the proposal on top, where the owner applies or cancels it. Never say a setting is changed before the owner applied it, and never try to apply it yourself. If the API refuses the change, say why in its words.
   - Tax form (JDG): `tax_form` with the tax year it applies from. CIT rate (sp. z o.o.): `cit_rate`, 19% or 9%. Norman does not settle Estonian CIT.
   - ZUS (JDG): `zus` with the scheme, the first day of a relief and the sickness insurance. Mały ZUS Plus needs last year's figures in the ZUS settings first. Company ZUS (sp. z o.o.): `company_zus`.
   - VAT: `vat_status` (this year's status and JPK_V7 frequency), `vat_cash_method`, `vat_proportion`.
   - Company data: `nip` (the EU VAT number follows it), `eu_vat_number`, `pesel` (Norman masks it), `activity_start`, `tax_office` (find the code with `search_polish_tax_offices`; let the owner choose the office), `reminders`.
   - KSeF: `ksef_auto_sync` switches the automatic import; `ksef_sync` imports from KSeF now.

5. **Offices**: Norman records the setting and notifies no office. The owner reports a tax form in CEIDG or at the tax office, VAT changes on VAT-R, ZUS changes in ePłatnik or CEIDG.

6. **KSeF token**: never ask for a KSeF token and never take one, even when the owner pastes it. The owner pastes it in Norman's settings: `get_ksef_status` returns the link to that field.
