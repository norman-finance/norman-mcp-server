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
