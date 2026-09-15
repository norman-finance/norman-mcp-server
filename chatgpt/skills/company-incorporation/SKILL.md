---
name: company-incorporation
description: Check an existing Norman GmbH or UG formation's status and continue the founder questionnaire in the authenticated Norman workspace.
version: 2.0.1
disable-model-invocation: true
---

Use `get_incorporation` to retrieve only whether a formation exists and its status.
Present the returned status and `workspaceUrl`. If `exists` is false, say there is
no active formation and offer the workspace link; do not invent progress or create one.
An error is not evidence that no formation exists: explain that status is unavailable.

The founder questionnaire, personal identifiers, residential and birth details,
identity documents, founding documents and notary handoff are handled inside
authenticated Norman forms, not in ChatGPT. Do not ask the user to paste those
details or upload identity documents here. Do not promise a notary appointment,
registration, bank-account opening or capital transfer has occurred.

Use `get_norman_workspace` with `workflow="incorporation"` if only a navigation
link is needed. This does not start or modify a formation. Explain the status in
plain language without giving binding legal advice.
