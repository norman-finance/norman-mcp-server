---
name: gewerbe-registration
description: Check a Norman trade-registration record's status and continue its questionnaire in the authenticated Norman workspace.
version: 2.0.1
disable-model-invocation: true
---

Use `get_gewerbe_registration` to obtain existence, status and `workspaceUrl`.
Explain the returned status; if no record exists, say so and offer the form link.
If the tool reports an error, say status is unavailable instead of inventing it.

The owner's questionnaire, birth details, residential information and identity
documents belong in authenticated Norman forms, not in ChatGPT. Do not request,
collect or display these details here or generate identity-bearing registration
documents through another tool. Do not claim a Gewerbeanmeldung was submitted.

Use `get_norman_workspace` with `workflow="gewerbe"` for a navigation link.
This only opens the workspace; it does not create, sign or file a registration.
Do not provide binding legal advice about the user's registration obligations.
