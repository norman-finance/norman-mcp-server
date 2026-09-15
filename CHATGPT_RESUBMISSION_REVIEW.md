# Norman ChatGPT v2.0.1 resubmission — 2026-09-15

Status: **implementation prepared; not ready to submit**. No merge or deployment has
been performed. Published v1 is unchanged. Work is isolated on
`fix/chatgpt-resubmission-20260915`, based on main `509d9c5`.

## Rejection and approved scope

OpenAI's email lists inconsistent test results, incorrect/missing tool annotations,
and solicitation of sensitive personal information. It does not identify individual
tools. Findings below are from our audit, not an attribution of specific causes to
OpenAI. The owner approved the source and product-boundary corrections.

No OAuth redirect, DCR, client-registration, issuer, token or allowlist behavior is
changed. `/mcp` keeps the general connector's 169 tools. A separate authenticated
`/chatgpt/mcp` route exposes 131 tools and uses the exact same OAuth provider/settings.
This route is a reviewed product surface, not a replacement for backend authorization.

## Implemented corrections

- Explicit read-only/open-world/destructive hints for both contract tools, with
  generated output schemas from their dictionary return annotations.
- Invoice/recurring-invoice/quote creation advertises its optional external email send.
- All three URL-based attachment uploads advertise arbitrary external downloads.
- Test-preview generators advertise file creation, not pure reads or idempotency.
- Public Handelsregister name search advertises open-world access.
- Finanzamt preview honors returned image MIME type, with the backend JPEG fallback.
- Review widgets use backend `page_size` and snake-case date filters; Ledger shows
  an explicit empty state instead of an unexplained empty table.
- ChatGPT widget resources declare owned `https://mcp.norman.finance` as their unique
  app origin; connect/resource CSP lists remain empty. This is not an OAuth redirect.

## Personal-data and payment boundaries

The ChatGPT profile excludes the three full incorporation/trade/corporate-registration
modules. It exposes only existence, an allowlisted status, and authenticated Norman
form links under the three existing status-tool names. Registration 404 means
not started; authentication/service failures are not reported as nonexistent records.

Personal government identifiers and founder questionnaires are entered in Norman,
not solicited by ChatGPT tools or the three replacement registration skills. Known
identity keys are rejected on input and removed from structured results and their
JSON text duplicates. This is **not** a classifier for arbitrary prose/documents and
does not assert that every possible personal detail can be detected automatically.
Business Steuernummer is distinguished from personal Steuer-ID/IdNr.

`pay_bill` initiates a SEPA order before bank confirmation, so it is not exposed to
ChatGPT. The profile also omits `toggle_agent`, `approve_rule_execution`,
`apply_rule_to_existing` and `update_rule`, whose existing action chains can prepare
payments. A precheck followed by execution would not be an adequate race-safe guard.
Category-only `create_rule` remains available. The bills handoff returns a static
list-page link; it neither calls a bank nor prefills or creates a payment order.

Other connectors retain these capabilities and their original skills. The ChatGPT
upload package contains 20 skills, overriding only the three registration flows.
Email sends and binding tax filing remain explicit-confirmation actions, accurately
annotated as external and destructive. They were **not** exercised in live testing.

## Submission artifacts

- `chatgpt-app-submission.json`: Norman, “Accounting and tax workspace”, FINANCE,
  scope-accurate description, 131 tool-specific justifications, 5 positive and 3
  negative cases. Contains no reviewer credentials or customer identifiers.
- `python -m scripts.chatgpt_submission` emits the artifact and fails on inventory
  or external-effect drift. Tests compare the stored artifact to live descriptors.
- `python -m scripts.package_chatgpt_skills /path/to/skills.zip` builds the isolated
  upload package without changing the general `skills/` directory.
- OpenAI's rejected-version editor is open; corrected metadata was imported and the
  draft version set to 2.0.1. The 20-skill upload was accepted; safety scanning is
  still pending (the portal allows up to two hours). Final submission has not been
  attempted. All 5 positive and 3 negative cases are visible in the form. The
  existing Business — Norman identity was selected. The deployed endpoint scan
  must still be replaced after rollout; an imported JSON does not
  establish that the server used by the form matches the reviewed inventory.

## Verification and demo-account blocker

Local suite: **194 passed**. Python compileall and diff whitespace checks passed.
Coverage includes protocol input/output filtering, unavailable tool invocation,
status-only responses, no-call payment handoffs, both HTTP routes/lifespans and their
identical existing OAuth challenges, hints, MIME handling, and artifact/package drift.

Authenticated checks used only the existing dedicated review account. Local MCP tool
functions called the production Norman REST API; no account records were seeded or
modified. These are **not** actual ChatGPT web/mobile or end-to-end OAuth results.

| Case | Observed result | Coverage limit |
| --- | --- | --- |
| Document Review | 15 documents; normalized payload passed unchanged to renderer | No host widget interaction verified |
| Reconciliation | 50 transactions with corrected pagination; matching render payload | Subset only, not whole-history totals |
| Ledger Explorer | No postings; empty payload handled | Non-empty drilldown not verified |
| Tax preview | Report discovery succeeds; preview blocked by account configuration | Happy path not passing |
| Incorporation status | No active incorporation; only safe status/link fields returned | No founder data read or registration created |

The selected unsubmitted VAT report's non-binding preview returned HTTP 400 wrapping
an upstream 422: `submission_without_tax_nr` requires new-admission status when no
business tax number is supplied. The existing demo fixture has no business tax number
and does not meet that condition. Preview remains unavailable and `canSubmit` is false.
No real filing or payment occurred. Do not fabricate a tax number, silently toggle
new-admission status, or change expected results to disguise the failed happy path.
The owner must supply a correctly configured review fixture in Norman.

## Remaining release/submission gates

1. Review and authorize merging/deploying this patch. This repository automatically
   deploys production on a push to main; a green PR is not deployment evidence.
2. Verify live `/chatgpt/mcp` has 131 reviewed tools, shared OAuth works, and `/mcp`
   remains compatible. Scan the new URL in the OpenAI draft without replacing
   working OAuth client configuration or modifying redirect rules.
3. Correct the dedicated review fixture's business-tax setup and rerun the complete
   preview happy path, strictly without binding submission or payment.
4. Run all five positive and three negative cases on actual ChatGPT web and mobile;
   record outcomes and update the demo recording if its flows no longer match.
5. Confirm imported tool justifications, skills scan results and test cases. Reimport
   metadata after the live tool scan if the portal overwrites annotations.
6. Review the selected developer identity, privacy/data-use disclosures and compliance
   attestations with the owner, then perform the final authorized resubmission.

## Review findings and output-schema warning

The restricted-data/payment findings are addressed in the isolated source profile and
skill package but are not yet deployed. App naming/description and tool hints reflect
the implemented scope; no broad/wildcard widget CSP was introduced. Reviewer fixture
readiness, actual host behavior, the demo video and final legal attestations remain
unverified. No approval guarantee is implied.

These 8 descriptors still lack `outputSchema`: `get_invoice_preview`,
`generate_finanzamt_preview`, `get_attachment_preview`, `render_tax_preview`,
`render_tax_submission`, `render_document_review`, `render_reconciliation_cockpit`,
`render_ledger_explorer`. Add an outputSchema so models can use these tools' results
more reliably, based on their actual return contracts rather than invented shapes.
This is a warning, not the missing-hint blocker. See the
[MCP tool specification](https://modelcontextprotocol.io/specification/draft/server/tools#tool).

References: [OpenAI app guidelines](https://developers.openai.com/plugins/app-guidelines),
[submission guide](https://developers.openai.com/plugins/deploy/submission),
[metadata reference](https://developers.openai.com/plugins/reference).
