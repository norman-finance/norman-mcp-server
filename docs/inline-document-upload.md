# Inline document uploads

`request_file_upload` opens a document panel in MCP Apps hosts. The user chooses
files, selects **Revenue** or **Expense for each document**, and confirms upload.
Mixed batches use `INCOME`/`invoice` and `EXPENSE`/`receipt` separately for every
file through Norman's existing company-scoped attachment API. The selected
company is displayed before upload. No direction is silently inferred.

Successful uploads create attachments immediately. The panel calls the read-only
`get_file_upload_status` tool and sends the result back to the chat. The assistant
must not call `create_attachment` or `upload_bulk_attachments` for these files
again. "Uploaded" means the attachment was saved; OCR and document processing
may still be pending. Uploading does not finalize operations or bookkeeping.

## Hosts and fallback

The resource supports the standard MCP Apps bridge and the existing ChatGPT
`window.openai` bridge. Tool and resource metadata advertise both. File bytes go
directly from the panel to the MCP upload endpoint; they are not embedded in a
model message. Only filenames, direction and upload results enter chat context.

For a host without an inline UI, or when the panel cannot be used, the tool returns
a short-lived `fallback_url`. It opens the same uploader in a separate browser
page. The user returns to chat and the assistant reads `get_file_upload_status`;
there is no manual `file_ref` step. Existing direct `/files/upload` routes and
`file_url`/`file_ref` attachment inputs remain available. The new panel requires
the hosted OAuth connection; it is not available in local API-key/stdio mode.

Local browser QA uses a simulated MCP Apps host and synthetic attachments. It
does not establish compatibility with every hosted client. Verify an authenticated
ChatGPT/Claude upload after deployment before claiming hosted end-to-end coverage.

## Isolation, limits and retry behavior

- Upload capability: random, 30-minute lifetime, bound to the OAuth grant and
  selected company. The server checks the live grant and company before a write.
  Switching company requires a new panel; refreshing the same grant is supported.
- Limits: 20 documents, 10 MB per document, 100 MB total; PDF, PNG, JPG/JPEG, WEBP
  and XML. The backend remains authoritative for file validity.
- Each file has a stable panel ID. An atomic SQLite reservation precedes the API
  write. Replaying the ID returns its recorded result. Duplicate bytes in the same
  panel are also refused. This is panel-level protection, not global deduplication.
- A network error, timeout, server error or interrupted write is **unconfirmed**.
  The server never automatically repeats it. Check the documents in Norman before
  starting a new upload. Only a definitive upstream 401 permits one credential
  refresh and retry through the existing provider method.
- Only metadata is retained: company, hashed grant/capability, filename, size,
  digest, direction, status and attachment ID. File bytes are spooled only during
  the request. OAuth credentials are never sent to the panel or stored in this DB.

## Deployment configuration

`NORMAN_MCP_PUBLIC_URL` remains the existing public origin, with no MCP or OAuth
endpoint changes. Its origin is the panel's only permitted connection domain.

`MCP_UPLOAD_STATE_FILE` optionally specifies the SQLite path. It defaults to
`document_uploads.sqlite3` beside `MCP_OAUTH_STATE_FILE`, or in `~/.norman-mcp/`.
Keep it on the persistent OAuth-state volume. Workers on one host must share the
file and a coherent OAuth registry. Independently replicated hosts require
appropriate routing/storage coordination; this change does not add distributed
OAuth/session infrastructure. Losing the file invalidates outstanding panels.

Expired records are removed when the next panel is created. An interrupted write
remains unconfirmed after restart rather than being silently replayed. No
deployment or production data migration is performed by this change.
