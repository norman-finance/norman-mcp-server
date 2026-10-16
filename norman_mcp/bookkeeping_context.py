"""Company-specific bookkeeping context, without personal government identifiers."""


def company_bookkeeping_context(company: dict) -> str:
    country = company.get("country") or "Unknown"
    currency = company.get("currency") or "Unknown"
    chart = company.get("chartOfAccounts")
    code = chart.get("code", "") if isinstance(chart, dict) else chart or ""
    text = (
        f"# {company.get('name', 'Unknown company')}\n\n"
        f"**Company ID**: {company.get('publicId', 'Unknown')}\n"
        f"**Country**: {country}\n**Accounting currency**: {currency}\n"
        f"**Account type**: {company.get('accountType', 'Unknown')}\n"
        f"**Chart of accounts**: {code or 'None'}\n"
        f"**VAT ID**: {company.get('vatNumber') or 'Not set'}\n"
        f"**Business tax ID**: {company.get('taxNumber') or 'Not set'}\n"
        f"**Activity start**: {company.get('activityStart') or 'Not set'}\n"
        f"**Address**: {company.get('address') or ''} {company.get('zipCode') or ''} {company.get('city') or ''}\n"
        f"**Profession**: {company.get('profession') or 'Not set'}\n"
    )
    if country == "PL":
        text += (
            "\nPolish company. Accounting currency is read above; preserve the original document currency separately. "
            "Use Polish VAT codes and API calculations. Operation date/valueDate is distinct from payment_date; "
            "documents provide supporting evidence/OCR. Use get_polish_jpk_register and "
            "get_polish_jpk_filing_status. An XML download is not a filing; require confirmed acceptance and UPO.\n"
        )
        if str(code).upper() == "PL_FULL":
            text += "PL_FULL: use Polish ledger, trial balance and financial statements tools for this company.\n"
        else:
            text += (
                "For JDG use get_polish_tax_book and get_polish_tax_book_operation to explain inclusion/exclusion.\n"
            )
    elif country == "DE" and company.get("isSme"):
        text += (
            "\nGerman SME: use its SKR03/SKR04 company chart, German Ledger, E-Bilanz and DATEV tools.\n"
            f"**DATEV advisor number**: {company.get('datevAdvisorNumber') or 'Not set'}\n"
            f"**DATEV client number**: {company.get('datevClientNumber') or 'Not set'}\n"
        )
    if company.get("usesCompanyChart") or company.get("isSme"):
        text += "Use list_company_categories and company category IDs from this company's chart.\n"
    return text
