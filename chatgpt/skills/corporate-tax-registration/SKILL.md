---
name: corporate-tax-registration
description: Check corporate tax-registration status for a GmbH or UG and continue the questionnaire in authenticated Norman forms without collecting personal identifiers in chat.
version: 2.0.1
disable-model-invocation: true
---

Call `get_corporate_tax_registration` to retrieve only existence, status and a
`workspaceUrl`. Report a missing record honestly; do not create a questionnaire
or claim it was filed. Treat errors as unavailable status, not as missing records.

Representatives, shareholders, personal Steuer-ID, birth details, identity and
founding documents must be entered and reviewed in the authenticated Norman
workspace. Never solicit them in ChatGPT or ask the user to paste the completed
questionnaire back here. Business Steuernummer and VAT IDs are different from
personal identifiers; never ask for a personal 11-digit IdNr to fill a company field.

Use `get_norman_workspace` with `workflow="corporate_tax"` to provide the form
link when appropriate. The user reviews the questionnaire and any legally binding
submission inside Norman. Do not call a tax-report submission tool as a substitute
for this registration flow or promise that a tax number has been issued.
