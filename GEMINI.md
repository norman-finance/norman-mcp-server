# Norman Finance

Use the Norman Finance MCP tools for bookkeeping, accounting, invoicing,
documents, reports and tax workflows for European businesses. Authenticate with
the user's Norman account when prompted; credentials must never be requested in
chat.

Read `company://current` first. Use Polish KPiR tools for JDG and the Polish
PL_FULL tools for full books, prepared financial statements and trial balances.
Use JPK tools for VAT registers and existing filing status. German SKR/DATEV,
ELSTER, payroll and incorporation tools require a German company. Polish tools
do not sign or submit returns; an XML download is not confirmed acceptance or UPO.
See [Polish accounting workflows](docs/polish-accounting.md).

For Polish settings, `propose_tax_setting_change` creates a stored pending
proposal, not an applied change. The owner reviews and applies it in Norman.
Never ask for a PESEL or KSeF token in chat; those belong in the authenticated app.

Read current Norman data before proposing a change. Explain the concrete effect
and obtain the user's explicit approval before sending invoices or reminders,
making payments, filing taxes, deleting or reversing records, applying an
accounting migration, or starting an external company-registration step.

Use the bundled skills when a request matches one of their workflows. Treat tax,
accounting, and incorporation output as preparation for the user's review, not
as legal or tax advice.
