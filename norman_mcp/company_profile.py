"""Project company API records without personal government identifiers."""

from typing import Any


def without_company_personal_identifiers(value: Any) -> Any:
    """Keep business identifiers and accounting data, but withhold the owner's PESEL.

    CompanyRetrieveSerializer exposes PESEL for Polish sole proprietors. This is
    a response-only projection: never remove the stored value or strip fields
    from API writes. In company records, taxNumber/taxId identify the business.
    """
    if isinstance(value, dict):
        return {
            key: without_company_personal_identifiers(item)
            for key, item in value.items()
            if "".join(char for char in str(key).casefold() if char.isalnum()) != "pesel"
        }
    if isinstance(value, list):
        return [without_company_personal_identifiers(item) for item in value]
    return value
