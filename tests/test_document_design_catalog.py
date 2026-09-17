"""Pin the design controls this server advertises to the catalog the API owns.

The API owns the template catalog in ``apps/invoices/document_design.py``. This
server carries its own copy as a typed enum so a bad template never leaves the
machine. Nothing else connects the two: without this test a template added on
the API is rejected here while ``list_invoice_templates`` advertises it, and CI
stays green. Update the constants below in the same change that updates the API.
"""

from norman_mcp.tools.invoice_schemas import DocumentDesign

# apps/invoices/document_design.py -> TEMPLATE_CATALOG, in gallery order.
TEMPLATES = ["heritage", "regent", "meridian", "horizon", "atelier", "epoque", "sovereign"]
TEXT_SIZES = ["small", "medium", "large"]
SPACINGS = ["compact", "standard", "spacious"]
TABLE_BORDERS = ["none", "dividers", "grid"]
LOGO_SIZE = (25, 100)


def test_design_schema_matches_the_api_catalog():
    schema = DocumentDesign.model_json_schema()["properties"]
    assert schema["template"]["enum"] == TEMPLATES
    for field, choices in (
        ("textSize", TEXT_SIZES),
        ("spacing", SPACINGS),
        ("tableBorders", TABLE_BORDERS),
    ):
        assert schema[field]["anyOf"][0]["enum"] == choices
    assert (schema["logoSize"]["minimum"], schema["logoSize"]["maximum"]) == LOGO_SIZE
