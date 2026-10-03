# Review remediation, 3 October 2026

This is a source audit and a preparation record, not a claim of approval or a
replacement for an authenticated test of the submitted release.

## Which version was rejected

The rejection email identifies Norman **2.0.1** and lists commerce, tool
annotations, names/descriptions and sensitive-data collection as concerns.
The submission portal was inspected without changing it on 3 October:

- Publication: **1.0.0**.
- Metadata & skills: **2.0.1 — Changes required**.
- Local upload source: **2.1.0**, including earlier remediation from `e6234e4`.
- The portal has eight MCP issue entries: `link_transaction`, `list_agents`,
  `suggest_skr_category`, `match_incorporation_notaries`, `toggle_agent`,
  `list_workflows`, `start_workflow` and `schedule_workflow`.
- The opened `link_transaction` and `list_workflows` cards only said the update
  needed further review. This is not a tool-specific explanation of the four
  email findings. The latter tool, `toggle_agent`, `start_workflow` and
  `schedule_workflow` were marked **Not live**; `suggest_skr_category` was
  marked **Earlier version live**. Inbox tools were marked **Live**.

The rejected ZIP and its exact scanned MCP snapshot have not been recovered.
Current source cannot establish which individual change the reviewer saw.
OpenAI stores scanned tool metadata with a submission; a source commit or ZIP
alone does not refresh that snapshot. See the
[MCP review requirements](https://developers.openai.com/plugins/deploy/app-review).

## Confirmed source corrections

| Concern | Source evidence | Correction |
| --- | --- | --- |
| Commerce | Workflow limit errors suggested upgrading a Norman plan; the tax-submit 403 message asked the user to subscribe. | Explain the unavailable entitlement or reset time without a purchase/upgrade call to action. Keep the existing error codes and tool behavior. |
| Destructive actions | `link_transaction` can replace transaction items and the existing attachment, finalize the transaction and mark the invoice paid. `update_asset` can delete unlocked depreciation postings when depreciation/status changes. | Both tools advertise `destructiveHint: true` and describe those side effects. |
| Rule execution | `apply_rule_to_existing` can overwrite existing transaction fields and creates a new execution on every call; the backend deliberately has no idempotency key for this operation. | Advertise `destructiveHint: true` and `idempotentHint: false`; describe the limited recent-transaction sweep and queued/inline results. |
| Description quality | Attachment parameters used “BEST OPTION” and “LAST RESORT”; category guidance expressed a speed/cost preference. | State supported inputs and matching behavior factually. Keep callable tool names and parameter contracts. These phrases are candidates, not a proven explanation of the email finding. |
| Restricted-data output | The backend company serializer includes `pesel`; company detail responses were forwarded unchanged. | Remove PESEL fields from company read/update responses. Extend the existing corporate-registration projection to recognize PESEL. Preserve business tax numbers, account identifiers and bank details needed for accounting. |

The default locally registered inventory contains **207 tools**. Every tool has
explicit boolean `readOnlyHint`, `destructiveHint` and `openWorldHint` values.
This establishes the current local contract, not that the rejected snapshot had
the same annotations. Other optional metadata fields may legitimately be null.

### Annotation rationale for the corrected actions

- `link_transaction`: read-only **false**, destructive **true**, open-world
  **false**. It overwrites company bookkeeping state; it does not contact the
  invoice recipient or execute a bank transfer.
- `update_asset`: read-only **false**, destructive **true**, open-world **false**.
  It updates an asset and can remove unlocked depreciation postings. The API
  protects locked postings; that protection does not make the other writes
  non-destructive.
- `apply_rule_to_existing`: read-only **false**, destructive **true**,
  open-world **false**, idempotent **false**. It creates a new execution for a
  bounded company transaction sweep on each request. Supported transaction
  actions can modify bookkeeping state. The audited sweep uses the transaction
  action registry, not the invoice email action registry.
- `suggest_skr_category` remains read-only **true**, destructive **false**,
  open-world **false**: results come from the fixed SKR catalog. Calling an AI
  service for bounded matching is not, by itself, open-ended web access.

## Remaining review decisions and evidence

The [plugin guidelines](https://developers.openai.com/plugins/plugin-guidelines)
allow access to an existing paid account but disallow subscription purchases,
upgrades and digital-service commerce. Removing upsell copy addresses a
specific issue; it does not settle how the reviewer classified Norman's wider
invoice/payment capabilities.

The public MCP still supports invoice creation/sending, payment links and
finAPI payment initiation. These features have not been removed or hidden from
reviewers. Before resubmission, describe their real behavior in the commerce
declaration and obtain clarification about the rejected workflow. Do not state
that Norman has no commerce merely because it does not sell Norman plans in
chat. If a narrower product scope is chosen, implement and document that scope
for all users of that distribution, not only the review account.

Known-key response projection is not a sensitive-data classifier. Free text,
uploaded documents, historical payloads and other endpoints still need a
fixture-based data-minimization review. The existing corporate people tool
rejects recognized personal identifier keys and sends identifier entry to the
authenticated Norman form; replacement updates are blocked when they would
discard stored identifiers. Do not claim that every possible representation of
restricted data is filtered.

Before submitting the prepared 2.1.0 package:

1. Confirm the desired commerce scope and the saved review declaration, rather
   than guessing which of the four email concerns caused a particular hold.
2. After an authorized server deployment, rescan and inspect the stored tool
   definitions, annotations and availability. Confirm that the three changed
   annotations match this source.
3. Use the dedicated sample company to run the existing five positive and
   three negative cases. Record actual tool calls/results, verify OAuth and
   test forbidden identifier input and entitlement failures with synthetic
   data. Local mocks are not reviewer-account evidence.
4. Verify the demo recording, privacy disclosures and secure reviewer access.
   The current package still omits a verified demo URL and a commerce
   declaration; omission does not prove the saved portal values are complete.
5. Upload and resubmit only after those checks and user authorization. Keep the
   published release, rejected release and new draft distinct in status reports.

No review cancellation, rescan, upload, appeal, resubmission or publication was
performed as part of this audit.
