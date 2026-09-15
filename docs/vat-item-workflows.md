# Mixed expenses and documented German input VAT

These additions apply to German GmbH/UG expense transactions. Existing items with `taxTreatment: null` retain inherited transaction semantics. An explicit `DOMESTIC_NO_VAT` means no VAT; it is not inferred from a missing rate.

## One bank movement: service plus bank fee

Read the existing transaction first. PATCH its complete `items` list, preserving each existing `publicId`, and use the company's chart-of-accounts IDs:

```json
{
  "items": [
    {"publicId": "existing-service-item-id", "description": "US service", "amount": "-100.00", "vatRate": 19, "companyCategory": "software-account-id", "taxTreatment": "THIRD_COUNTRY_SERVICE_REVERSE_CHARGE", "order": 0},
    {"publicId": "existing-fee-item-id", "description": "Domestic bank fee", "amount": "-2.00", "vatRate": 0, "companyCategory": "bank-fee-account-id", "taxTreatment": "DOMESTIC_NO_VAT", "order": 1}
  ]
}
```

For a newly added row omit `publicId`. After saving, review the ledger and both VAT reports: payment EUR 102, reverse-charge base EUR 100, tax EUR 19, fee EUR 2 excluded from the RC base. No additional bank transaction is necessary. Domestic RC, EU services and EU goods acquisitions have separate treatment values; choose the value matching the document.

## Invoice in USD with input VAT explicitly stated in EUR

Attach the invoice first. On its item select `DOMESTIC_INPUT_VAT`, the invoice's rate (7 or 19), `vatAmountMode: DOCUMENTED_GERMAN_INPUT_VAT`, `documentedVatAmountEur: "19.00"`, and `vatDocumentId` of the supporting document belonging to the company. The item `amount` remains its gross share of the actual movement in the transaction currency. Keep the bank fee and any separately established FX difference in their own correctly classified rows; rows must still add up to the real payment.

The documented value is the invoice's full EUR input VAT before the deductible business share. `professionalUsePart` is 0 through 1; the ledger and reports apply it once. Zero documented VAT and zero business share are valid and distinct from missing values. The server rejects fixed VAT for reverse charge, output VAT, foreign VAT, missing/foreign-company documents, and amounts exceeding the converted gross item amount.

FX conversion preserves this EUR source value, including when workers run again. Source document/value changes affect audit and ledger fingerprints. Historical inherited hashes retain their previous format. Supporting VAT documents are included in document exports. DATEV exports exact EUR expense/VAT legs, with BU 40 on the expense leg to suppress automatic VAT and no automatic tax key on the explicit VAT leg. This follows DATEV's [automatic-account suppression convention](https://apps.datev.de/help-center/documents/0907051); acceptance in an actual DATEV installation remains a release check.

To return to automatic calculation explicitly send `vatAmountMode: AUTO`, `documentedVatAmountEur: null`, and `vatDocumentId: null`. When clearing the entire tax override also send `taxTreatment: null`. To delete a protected item, first clear its override and save, then remove it. A client that cannot preserve item identity receives a validation error instead of silently deleting tax details. Verified/locked financial data cannot be edited in place.

In the web split editor, select each item's tax treatment, then "Input VAT stated on document" and its EUR amount. The document must already be attached. On mobile, these entries route to the web editor. When a native currency differs from EUR, the UI keeps the payment total and documented EUR VAT separate; it does not subtract EUR tax from a USD total.

## Manual correction of the tax itself

Create a manual ledger entry using `taxRole: VAT`, `taxTreatment: DOMESTIC_INPUT_VAT`, `taxCountryScope: DOMESTIC`, `taxCorrectionReason: BOOKKEEPING_ERROR`, a descriptive memo and `inputTaxDeductionPercent: 100`. The amount is the actual tax correction, for example EUR 0.59, without multiplying by 19%. Credit to the input VAT account reduces the deduction; debit increases it. Use exactly one appropriate input VAT account (SKR04 1400/1401/1406 or SKR03 1570/1571/1576). Other correction reasons are not supported by this mode.

Use the entry's existing reverse endpoint/tool to cancel it; do not create an unrelated compensating bank payment. The original and its reversal must net to zero in the ledger, UStVA and annual USt. Historic BASE entries retain their role; only the reversal sign calculation changes.

## MCP field mapping

`create_transaction` / `update_transaction` item objects use snake_case: `public_id`, `tax_treatment`, `vat_amount_mode`, `documented_vat_amount_eur` (decimal string), `vat_document_id`, `professional_use_part`, and `metadata`. Read existing items before updating and pass the full list. Costs may use positive document orientation with negative discounts; the tool normalizes the whole list for expenses/refunds while keeping discount signs. `create_manual_ledger_entry` uses `tax_role` and `tax_correction_reason` with the same semantics as above.

## Rollout and compatibility

Deploy additive migrations 0195/0196, compatible API and every currency/OCR/repair worker first, then the web/mobile/MCP clients. The manual-correction patch can ship independently. The documented-VAT API patch is stacked on item treatment. Once documented values exist, do not roll back to old workers that do not understand them. Disabling controls does not protect stored source values; use a compatible rollback or forward fix.

Recalculate only the relevant company's draft reports after reviewing a scoped preview. Do not rewrite original/manual records, filed snapshots or locked periods. Existing ambiguous historical 0% split rows need review; the migration does not guess their treatment. Local regression and ERiC validation are distinct from deployment, customer-data verification and an actual DATEV import.

### DATEV scope for nonstandard deductions

Explicit German input-VAT items export their actual EUR ledger legs for both automatic and documented amounts, including partial deductions and open vendor accounts. Fully deductible RC items keep their normal keys; services without input deduction use the corresponding non-deductible key. Partial RC deduction and EU acquisitions without deduction are rejected by DATEV export with a clear error until their export representation is validated. They remain available in the ledger/GDPdU and VAT calculations. The export must never silently claim full input VAT for such an item.

Manual ledger tools require the existing authenticated company/OAuth permissions. They are not added to the restricted `nrm_` public API-key surface by this change; its OpenAPI export covers the transaction item fields.
