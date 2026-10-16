"""Polish asset inputs; the API owns all eligibility rules and calculations."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field

from norman_mcp.tools.invoice_schemas import ApiInput


class PolishAssetTax(ApiInput):
    kind: Literal["computer", "phone", "furniture", "machinery", "software", "car"]
    entry_date: date = Field(description="Date the asset entered use, distinct from purchase/payment date")
    annual_rate: Decimal = Field(ge=1, le=100, max_digits=5, decimal_places=2)
    method: Literal["linear", "low_value", "new_assets", "de_minimis"]
    vat_rate: Literal[0, 5, 8, 23]
    vat_recovery: Literal[0, 50, 100]
    car_kind: Literal["", "electric", "low_emission", "high_emission"] = ""
    kst_group: Literal["", "3", "4", "5", "6", "7", "8"] = ""
    one_off_amount: Decimal = Field(default=Decimal(0), ge=0, max_digits=12, decimal_places=2)
    external_allowance_used: Decimal = Field(default=Decimal(0), ge=0, max_digits=12, decimal_places=2)
    scope_confirmed: bool = Field(default=False, description="True only after the user confirms the supported scope")
    classification_confirmed: bool = Field(
        default=False,
        description="True only after the user confirms KST/car classification",
    )
    eligibility_confirmed: bool = Field(
        default=False,
        description="True only after the user confirms one-off eligibility",
    )
    factory_new: bool = False
