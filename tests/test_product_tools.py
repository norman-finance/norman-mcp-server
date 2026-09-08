import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from norman_mcp.tools.invoices import register_invoice_tools
from norman_mcp.tools.products import register_product_tools


class FakeMcp:
    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., Any]] = {}

    def tool(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        del args, kwargs

        def register(function: Callable[..., Any]) -> Callable[..., Any]:
            self.tools[function.__name__] = function
            return function

        return register


class FakeApi:
    def __init__(self, company_id: str | None = "company-1", response: Any = None) -> None:
        self.company_id = company_id
        self.response = {"ok": True} if response is None else response
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    async def arequest(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        self.requests.append((method, url, kwargs))
        return self.response


def context_for(api: FakeApi) -> SimpleNamespace:
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))


def registered(api: FakeApi | None = None) -> tuple[FakeMcp, FakeApi]:
    mcp = FakeMcp()
    api = api or FakeApi()
    register_product_tools(mcp)
    return mcp, api


def call(mcp: FakeMcp, tool: str, api: FakeApi, **kwargs: Any) -> Any:
    return asyncio.run(mcp.tools[tool](context_for(api), **kwargs))


PRODUCTS_URL = "https://api.norman.finance/api/v1/companies/company-1/products/"


def test_registers_the_five_product_tools() -> None:
    mcp, _ = registered()
    assert {
        "list_products",
        "get_product",
        "create_product",
        "update_product",
        "archive_product",
    } <= set(mcp.tools)


def test_list_sends_only_set_filters_and_defaults_to_active() -> None:
    mcp, api = registered()

    call(mcp, "list_products", api)
    assert api.requests[-1] == (
        "GET",
        PRODUCTS_URL,
        {"params": {"page": 1, "pageSize": 50, "status": "active"}},
    )

    call(
        mcp,
        "list_products",
        api,
        search="consult",
        product_type="SERVICES",
        unit="hours",
        status="all",
        page=2,
    )
    _, _, kwargs = api.requests[-1]
    assert kwargs["params"] == {
        "page": 2,
        "pageSize": 50,
        "status": "all",
        "search": "consult",
        "type": "SERVICES",
        "unit": "hours",
    }


def test_list_rejects_unknown_values_without_a_request() -> None:
    mcp, api = registered()

    assert "error" in call(mcp, "list_products", api, status="deleted")
    assert "error" in call(mcp, "list_products", api, unit="grams")
    assert "error" in call(mcp, "list_products", api, product_type="STUFF")
    assert api.requests == []


def test_get_product_hits_the_detail_url() -> None:
    mcp, api = registered()

    call(mcp, "get_product", api, product_id="p-1")

    assert api.requests[-1] == ("GET", PRODUCTS_URL + "p-1/", {})


def test_create_sends_the_camel_case_payload() -> None:
    mcp, api = registered()

    call(
        mcp,
        "create_product",
        api,
        name="Consulting hour",
        price=15000,
        vat_rate=19,
        unit="hours",
        description="Senior rate",
        sku="CONS-H",
        company_category_id="cat-1",
    )

    method, url, kwargs = api.requests[-1]
    assert (method, url) == ("POST", PRODUCTS_URL)
    assert kwargs["json_data"] == {
        "name": "Consulting hour",
        "price": 15000,
        "type": "SERVICES",
        "isPriceGross": False,
        "vatRate": 19,
        "unit": "hours",
        "description": "Senior rate",
        "sku": "CONS-H",
        "companyCategory": "cat-1",
    }


def test_create_leaves_the_vat_rate_to_the_country_default_when_omitted() -> None:
    mcp, api = registered()

    call(
        mcp,
        "create_product",
        api,
        name="Notebook stand",
        price=4990,
        product_type="GOODS",
        is_price_gross=True,
    )

    assert api.requests[-1][2]["json_data"] == {
        "name": "Notebook stand",
        "price": 4990,
        "type": "GOODS",
        "isPriceGross": True,
    }


def test_create_rejects_an_unknown_unit() -> None:
    mcp, api = registered()

    result = call(mcp, "create_product", api, name="Flour", price=320, unit="grams")

    assert "error" in result
    assert api.requests == []


def test_update_sends_only_the_given_fields_and_can_clear_the_category() -> None:
    mcp, api = registered()

    call(
        mcp,
        "update_product",
        api,
        product_id="p-1",
        price=16000,
        company_category_id="",
        status="active",
    )

    method, url, kwargs = api.requests[-1]
    assert (method, url) == ("PATCH", PRODUCTS_URL + "p-1/")
    assert kwargs["json_data"] == {"price": 16000, "companyCategory": None, "status": "active"}


def test_update_without_fields_makes_no_request() -> None:
    mcp, api = registered()

    result = call(mcp, "update_product", api, product_id="p-1")

    assert result == {"message": "No fields provided for update."}
    assert "error" in call(mcp, "update_product", api, product_id="p-1", status="deleted")
    assert api.requests == []


def test_archive_deletes_and_confirms() -> None:
    mcp, api = registered()

    result = call(mcp, "archive_product", api, product_id="p-1")

    assert api.requests[-1] == ("DELETE", PRODUCTS_URL + "p-1/", {})
    assert result == {"message": "Product archived.", "productId": "p-1"}


def test_archive_passes_an_api_error_through() -> None:
    mcp, api = registered(FakeApi(response={"error": "Not found", "status_code": 404}))

    result = call(mcp, "archive_product", api, product_id="missing")

    assert result["status_code"] == 404


def test_every_tool_needs_a_company() -> None:
    mcp, api = registered(FakeApi(company_id=None))

    assert "error" in call(mcp, "list_products", api)
    assert "error" in call(mcp, "get_product", api, product_id="p-1")
    assert "error" in call(mcp, "create_product", api, name="x", price=1)
    assert "error" in call(mcp, "update_product", api, product_id="p-1", name="y")
    assert "error" in call(mcp, "archive_product", api, product_id="p-1")
    assert api.requests == []


def test_invoice_tools_document_the_product_line_fields() -> None:
    mcp = FakeMcp()
    register_invoice_tools(mcp)

    for name in ("create_invoice", "create_recurring_invoice"):
        doc = mcp.tools[name].__doc__ or ""
        assert "productId" in doc
        assert "description" in doc
        assert "unit" in doc
