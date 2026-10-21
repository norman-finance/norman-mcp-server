# Tool workflow reference

Detailed behavior and integration notes, moved from the main README. For the product overview and connection instructions, see [Norman MCP Server](../README.md).

## Document uploads

`create_attachment.file_url`, bulk `file_urls`, and structured document imports
accept HTTP(S) download links, including unexpired presigned S3 URLs with query
parameters. Pass the entire link unchanged; the file host must accept the request
without additional authorization headers. The URL downloader has no domain allowlist,
URL-length cap, or explicit file-size cap. Its connect/read timeout is 30 seconds
(not a total download deadline). The separate browser upload route defaults to
50 MiB, configurable with `MCP_UPLOAD_MAX_SIZE`; API file validation still applies.

URL download failures return an `error` message and `code`: `download_http_error`
(with `http_status`), `download_timeout`, `download_network_error`,
`download_storage_error`, or `download_error`. A 403 from the file host can mean an
expired or rejected signature; obtain a fresh link and check the host response.
Bulk uploads include `download_errors` for failed URLs, indexed within `file_urls`
followed by URL entries from the deprecated `file_paths` alias; successfully fetched
files are still uploaded. Structured imports report errors per document. Download
errors omit signed URLs, and temporary downloads are cleaned up after use or cancellation.

## Invoice appearance and updates

Use `list_invoice_templates` to discover the templates, appearance controls and the active company's plan access. Use `get_invoice_settings` to read its logo and saved defaults.

`create_invoice`, `create_recurring_invoice` and `create_offer` accept `document_design`, for example:

```json
{"template": "sovereign", "logoSize": 75, "textSize": "medium", "spacing": "compact", "tableBorders": "grid"}
```

Omit `document_design`, `font`, and `color_schema` to inherit saved branding. On create, a partial design uses that template's defaults. Paid templates require an active subscription.

Use `update_invoice` for an invoice or quote, `update_recurring_invoice` for a schedule, and `update_invoice_settings` for future document defaults. Their typed `changes` object accepts camelCase or snake_case field names. Unset fields stay unchanged; explicit `false`, `0`, empty strings and valid nulls keep their meaning. A partial document design keeps the document's other saved controls; changing its template starts from that template's defaults. Keep existing line IDs when editing lines. Rates use minor currency units; the API calculates totals. Only set `isToSend` when sending is intended.

Use `cancel_invoice`, `create_credit_note` and `create_delivery_note` for documents derived from an existing invoice or an approved quote; each links back to its source, and a cancelled invoice is read-only afterwards. `duplicate_invoice` copies an invoice or quote into a fresh draft without a link. API keys need `read_invoices` for template/settings reads and `write_invoices` for edits. Settings updates use the invoice-specific endpoint and cannot edit other company fields. Deploy the matching invoice API endpoints before deploying this MCP version.

## Client emails and payment reminders

`send_invoice` and `send_invoice_overdue_reminder` use the company's email template when `subject` and `body` are left out; `additional_emails` go out as CC, and the company's own copy follows its setting unless `is_send_to_company` is given. `list_invoice_emails` returns every email about a document with its delivery status and the reminder the rule sends next. A send that fails at once returns an error with the reason; otherwise `email.status` is `sent`, or `queued` while Norman retries. A dunning fee is shown in the reminder with the total and is paid by bank transfer: a reminder with a fee has no online payment button.

Automatic reminders are off until `autoReminders` is true on the invoice (`create_invoice`, `create_recurring_invoice`, or `update_invoice`, also after the invoice was issued); `remindersPaused` stops them for one invoice and `skip_invoice_reminder` stops one planned reminder. `remindersActive` on an invoice says whether Norman reminds by itself right now. The company's rule and wording live in `get_invoice_email_settings` / `update_invoice_email_settings` and `list_invoice_email_templates` / `save_invoice_email_template` / `reset_invoice_email_template`. `settings_on_overdue` is kept for older integrations and sends nothing. These tools need the invoice email endpoints of the API to be live before this MCP version is deployed.

## Starting a German company

Found a German **GmbH or UG (haftungsbeschränkt)** end-to-end — Norman collects the data, prepares the documents, and hands off to a notary:

- *"I want to start a GmbH in Berlin — walk me through it."*
- *"Found a UG for me and two co-founders, split the shares 60/40."*
- *"Is 'Wunderbar Robotics' still free in the Handelsregister?"*
- *"Reword my business purpose so it's ready for the register."*
- *"Generate the Musterprotokoll and find me a notary who does online notarization."*
- *"What's left before my company is officially registered?"*
- *"Which Finanzamt is responsible for my company's address?"*

> Choosing GmbH/UG also sets your Norman account to the corporate **SKR04** chart of accounts, so bookkeeping and taxes are ready from day one. The documents are drafts to prepare the notary appointment — not legal advice.

<br/>

## Mixed VAT and documented input tax

See [the German VAT item workflow](vat-item-workflows.md) for item-level treatments, fixed documented EUR input VAT, refunds and manual VAT-only corrections. For Poland, see [VAT codes and document currencies](polish-accounting.md#existing-write-tools). Requires the corresponding API migrations and calculation updates.

## DATEV files and complete Ledger exports

For German companies, `trigger_datev_export` defaults to the complete Ledger for GmbH/UG (`isSme`),
including opening, manual, payroll, depreciation and closing entries. Other
German companies retain the finalized-transactions export. Use `source="transactions"`
only for an explicitly requested transactions-only export. A Ledger failure never
falls back to that narrower export. The API checks the journal before returning
an expiring download link and includes its validation findings in the response.
With `include_documents=true`, the ZIP contains the journal, account reports and
available linked documents; unreadable attached documents block the package.

- `validate_ledger_datev_export`: preview structure, source coverage and documents
  for a period without saving company settings, creating a download or sending it.
- `read_datev_file`: inspect an uploaded EXTF/DTVF **Buchungsstapel** without
  importing it. Obtain a `file_ref` through `request_file_upload` or `POST /files/upload`, then
  filter by account, document date, text or minimum amount. Reuse that reference
  for subsequent pages (up to 100 rows/page) until its normal upload expiry.
  No DATEV connection or chart setup is needed; an authenticated Norman company
  is required. CSV/TXT/EXTF uploads are limited to 20 MB / 100,000 rows; extract
  the booking CSV from a ZIP before uploading.

The reader preserves tax keys and Generalumkehr markers. Its totals are source-row
amounts grouped by currency, **not** tax-expanded account balances or open items.
Structural checks do not certify tax correctness or acceptance by DATEV. Nothing
in these tools emails an accountant or pushes an export to DATEV.

The API release providing Ledger `responseFormat`/`validateOnly` and
`/companies/{id}/accounting/datev/read/` must be deployed before this MCP release.

## Transport and upload limits

The SDK 2 HTTP transport limits MCP JSON request bodies to 4 MiB. Send larger documents through `file_url` or the upload page's `file_ref`, rather than inline base64. The separate multipart upload route keeps its own 50 MiB default, configurable with `MCP_UPLOAD_MAX_SIZE`.
