"""Invoice wire models shared with the internal/external MCP copy.

Aliases match the public API. Unset fields stay unset so PATCH preserves saved
values and creation inherits company defaults. API contract tests pin the fields.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class ApiInput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    def payload(self) -> dict:
        return self.model_dump(by_alias=True, exclude_unset=True, mode="json")


class DocumentDesign(ApiInput):
    @model_validator(mode="before")
    @classmethod
    def reject_null_controls(cls, value):
        if isinstance(value, dict) and any(item is None for item in value.values()):
            raise ValueError("Design controls cannot be null; omit them to use template defaults.")
        return value

    template: Literal["heritage", "regent", "meridian", "horizon", "atelier", "epoque", "sovereign"]
    version: Literal[1] = 1
    logo_size: int = Field(default=50, ge=25, le=100)
    text_size: Literal["small", "medium", "large"] | None = None
    spacing: Literal["compact", "standard", "spacious"] | None = None
    table_borders: Literal["none", "dividers", "grid"] | None = None


class InvoiceItem(ApiInput):
    name: str = Field(max_length=255)
    quantity: float
    rate: int = Field(
        description="Unit price in minor currency units (cents for EUR); gross when is_vat_included is true."
    )
    vat_rate: int = Field(description="VAT percentage, e.g. 19. The API validates the applicable rate.")
    id: str | None = Field(default=None, description="Preserve an existing line UUID on edit; omit for a new line.")
    description: str | None = Field(default=None, max_length=500)
    unit: Literal["", "items", "hours", "days", "kilograms", "liters", "meters", "square_meters"] | None = None
    product_id: str | None = None
    company_category: str | None = None
    discount_percent: float | None = Field(default=None, ge=0, le=100)
    item_price_net: int | None = None
    item_price_gross: int | None = None
    item_vat_amount: int | None = None
    item_discount_amount: int | None = None
    gtu_code: (
        Literal[
            "",
            "GTU_01",
            "GTU_02",
            "GTU_03",
            "GTU_04",
            "GTU_05",
            "GTU_06",
            "GTU_07",
            "GTU_08",
            "GTU_09",
            "GTU_10",
            "GTU_11",
            "GTU_12",
            "GTU_13",
        ]
        | None
    ) = None
    is_split_payment: bool | None = None
    discount_note: str | None = Field(default=None, max_length=500, description="Deprecated alias; use description.")
    total: float | None = Field(
        default=None, exclude=True, description="Legacy input, ignored. The API calculates totals."
    )


class MailingData(ApiInput):
    email_subject: str | None = None
    email_body: str | None = None
    custom_client_email: str | None = None
    additional_emails: list[str] | None = None
    is_send_to_company: bool | None = None


class OverdueSettings(ApiInput):
    is_to_autosend_notification: bool | None = None
    notify_after_days: list[int] | None = None
    notify_in_particular_days: list[str] | None = None
    custom_email_body: str | None = Field(default=None, max_length=1000)
    custom_email_subject: str | None = Field(default=None, max_length=400)


class ClientData(ApiInput):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    zip_code: str | None = None
    country: str | None = None
    vat_number: str | None = None
    email: str | None = None
    phone: str | None = None


class CompanyData(ApiInput):
    name: str | None = None
    currency: str | None = None
    address: str | None = None
    zip_code: str | None = None
    city: str | None = None
    country: str | None = None
    tax_state: str | None = None
    vat_number: str | None = None
    tax_number: str | None = None
    iban: str | None = None
    bic: str | None = None
    bank_name: str | None = None


class DocumentFields(ApiInput):
    client: str | None = Field(
        default=None, description="Client public ID. Explicit null removes the recipient where allowed."
    )
    client_data: ClientData | None = None
    company_data: CompanyData | None = None
    invoice_type: Literal["SERVICES", "GOODS"] | None = None
    discount_percents: int | None = None
    currency: str | None = None
    currency_exchanged: str | None = None
    invoiced_items: list[InvoiceItem] | None = None
    payment_terms: str | None = None
    notes: str | None = None
    instructions: str | None = None
    message: str | None = None
    language: str | None = Field(default=None, description="Document language: en, de, pl, it or es.")
    is_vat_included: bool | None = None
    iban: str | None = None
    bic: str | None = None
    bank_name: str | None = None
    is_to_send: bool | None = None
    company_email: str | None = None
    full_cost_origin_exchanged: float | None = None
    create_qr: bool | None = None
    skip_bank_details: bool | None = None
    save_client_details: bool | None = None
    settings_on_overdue: OverdueSettings | None = None
    color_schema: str | None = Field(default=None, description="Hex colour; omission preserves company/saved branding.")
    font: str | None = Field(default=None, description="Omission preserves company/saved font.")
    document_design: DocumentDesign | None = None
    mailing_data: MailingData | None = None
    tax_exempt_reason: str | None = Field(
        default=None, max_length=500, description="Omit to derive the VAT note; an empty string prints no note."
    )
    online_payment_enabled: bool | None = Field(
        default=None, description="Stripe/PayPal payment link; false explicitly disables it."
    )
    source_contract: str | None = None


class InvoiceChanges(DocumentFields):
    """Only fields supplied by the caller are updated. Null is distinct from omission."""

    invoice_number: str | None = None
    payment_status: str | None = None
    status: str | None = None
    issued: str | None = None
    delivery_date: str | None = None
    due_to: str | None = None
    service_start_date: str | None = None
    service_end_date: str | None = None
    payment_date: str | None = None
    bank_account_pk: str | None = None
    type: Literal["invoice", "quote", "delivery_note", "cancel", "credit_note"] | None = None


class RecurringChanges(DocumentFields):
    recurring_number: str | None = None
    frequency_unit: int | None = None
    frequency_type: Literal["weekly", "monthly"] | None = None
    starts_from_date: str | None = None
    ends_on_date: str | None = None
    ends_on_invoice_count: int | None = None
    is_ongoing: bool | None = None
    payment_due_days: int | None = Field(default=None, ge=0, le=365)
    billing_in_advance: bool | None = None


class InvoiceSettings(ApiInput):
    """Company defaults for future invoices and quotes."""

    setup_completed: bool | None = None
    currency: str | None = None
    language: str | None = None
    create_qr: bool | None = None
    invoice_type: Literal["SERVICES", "GOODS"] | None = None
    color_schema: str | None = None
    font: str | None = None
    document_design: DocumentDesign | None = None
    show_customer_number: bool | None = None
    show_contact_person: bool | None = None
    online_payments_default: bool | None = None
    tax_office_name: str | None = None
    tax_office_city: str | None = None


def input_payload(value: ApiInput | dict, model: type[ApiInput]) -> dict:
    return model.model_validate(value).payload()


def item_payloads(items: list[InvoiceItem | dict]) -> list[dict]:
    return [input_payload(item, InvoiceItem) for item in items]


def apply_invoice_options(payload: dict, **options) -> None:
    """Omit unspecified create options but preserve explicit false, zero and empty strings."""
    models = {
        "document_design": DocumentDesign,
        "client_data": ClientData,
        "company_data": CompanyData,
        "mailing_data": MailingData,
        "settings_on_overdue": OverdueSettings,
    }
    for key, value in options.items():
        if value is not None:
            payload[to_camel(key)] = input_payload(value, models[key]) if key in models else value


class TransactionInvoiceItem(InvoiceItem):
    category: str | None = Field(default=None, description="Bookkeeping category for the linked transaction line.")
