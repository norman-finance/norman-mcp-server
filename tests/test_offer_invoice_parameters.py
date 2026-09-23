from mcp.server.fastmcp import FastMCP

from tests.test_invoice_parameter_parity import INVOICE, LINE, Api, arguments, call


def test_quote_creation_has_the_same_options_and_inherits_branding():
    from norman_mcp.tools.offers import register_offer_tools

    server = FastMCP()
    register_offer_tools(server)
    api = Api()
    kwargs = arguments(INVOICE)
    kwargs.pop("document_type")
    kwargs["offer_number"] = kwargs.pop("invoice_number")
    kwargs["valid_until"] = kwargs.pop("due_to")
    call(server, api, "create_offer", **kwargs)
    assert api.requests[-1][2]["json_data"] == {**INVOICE, "type": "quote"}
    api = Api()
    call(server, api, "create_offer", client_id="client-1", items=[LINE], offer_number="QUOTE-1")
    data = api.requests[-1][2]["json_data"]
    assert not {"font", "colorSchema", "documentDesign", "companyId", "companyEmail"} & data.keys()


def test_create_offer_leaves_the_currency_to_the_company_unless_told():
    from norman_mcp.tools.offers import register_offer_tools

    server = FastMCP()
    register_offer_tools(server)
    api = Api()
    call(server, api, "create_offer", client_id="client-1", items=[LINE], offer_number="QUOTE-1")
    assert "currency" not in api.requests[-1][2]["json_data"]
    call(server, api, "create_offer", client_id="client-1", items=[LINE], offer_number="QUOTE-2", currency="USD")
    assert api.requests[-1][2]["json_data"]["currency"] == "USD"
