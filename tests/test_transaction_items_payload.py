"""Split-transaction shaping shared with the embedded Norman MCP."""

from norman_mcp.tools.transactions import _build_items_payload, _items_total_mismatch


def test_expense_items_are_negated_and_ordered() -> None:
    payload = _build_items_payload(
        [
            {"description": "Food", "amount": 47.2, "vat_rate": 7},
            {
                "description": "Household",
                "amount": 19.5,
                "vat_rate": 19,
                "company_category_id": "coa-1",
            },
        ],
        negate=True,
    )

    assert payload[0]["amount"] == -47.2
    assert payload[0]["order"] == 0
    assert payload[1]["amount"] == -19.5
    assert payload[1]["companyCategory"] == "coa-1"


def test_mismatched_totals_are_rejected() -> None:
    mismatch = _items_total_mismatch([{"amount": 47.2}, {"amount": 10}], 66.7)

    assert mismatch is not None
    assert "57.20" in mismatch["error"]
    assert "66.70" in mismatch["error"]


def test_documented_fields_preserve_zero_null_ids_and_precision() -> None:
    row = _build_items_payload([{
        "public_id": "row-1", "amount": "119.59", "vat_rate": 19,
        "tax_treatment": "DOMESTIC_INPUT_VAT", "professional_use_part": 0,
        "vat_amount_mode": "DOCUMENTED_GERMAN_INPUT_VAT",
        "documented_vat_amount_eur": "19.00", "vat_document_id": "doc-1",
    }], negate=True)[0]
    assert row["publicId"] == "row-1"
    assert row["professionalUsePart"] == 0
    assert row["taxTreatment"] == "DOMESTIC_INPUT_VAT"
    assert row["documentedVatAmountEur"] == "19.00"
    cleared = _build_items_payload([{
        "amount": 0, "tax_treatment": None, "vat_amount_mode": "AUTO",
        "documented_vat_amount_eur": None, "vat_document_id": None,
    }], negate=False)[0]
    assert cleared["documentedVatAmountEur"] is None
    assert cleared["vatDocumentId"] is None
    assert cleared["taxTreatment"] is None
    assert _build_items_payload([{"documented_vat_amount_eur": "0.00"}], negate=False)[0]["documentedVatAmountEur"] == "0.00"


def test_discounts_keep_their_relative_sign_for_expenses_and_refunds() -> None:
    for inputs in ([119.59, -10], [-119.59, 10]):
        items = [{"amount": value} for value in inputs]
        assert _items_total_mismatch(items, 109.59) is None
        assert [row["amount"] for row in _build_items_payload(items, negate=True)] == [-119.59, 10]
        assert [row["amount"] for row in _build_items_payload(items, negate=False)] == [119.59, -10]
