# Polish forms via chat

Three tools reuse Norman's API-owned catalog and generation engine:

1. `list_polish_forms(query, locale)` finds official forms and available generators.
2. `get_polish_form(form_id)` returns current version, required fields, limits and official sources.
3. `generate_polish_document(form_id, version, fields, output_format)` prepares a payment request or handover protocol in Polish PDF/DOCX and returns a preview plus a temporary download link.

Use supplied facts only. Ask for missing fields; do not request PESEL, government identifiers, tax-portal credentials or signatures. Official ZAW-FA, UPL-1, VAT-R and ZUS DRA entries link to official forms and cannot be generated. The user reviews, signs and delivers the resulting business document themselves. No sending, filing, payment, company prefill or persistent company-document creation occurs.

The API controls validation, template version and rendering. Links expire after 10 minutes and are accessible to anyone holding them. State that fact with the preview/download. A 409 requires rereading the form schema; an expired link requires regeneration. API failures are MCP tool errors, never successful document results.

The existing MCP login and company isolation are unchanged. These generic Polish forms do not read a selected company and can be discovered without changing company selection.

Deployment depends on the forms API endpoints and a shared Redis artifact cache being available first. Local contract tests do not prove hosted API/chat availability.

```sh
python -m pytest tests/test_forms.py tests/test_polish_public_sync.py -q
```
