# Norman Inbox and MCP Events (development)

[Back to the overview](../README.md#interactive-ui-inside-your-ai-assistant)

`open_norman_inbox` declares global/sidebar and thread entrypoints for hosts that
support [plugin extensions](https://developers.openai.com/plugins/build/extensions).
MCP Apps hosts can render the same self-contained UI; other clients can call
`get_norman_inbox_data` and `get_norman_approval_data` for structured results.
Workflow questions use actual blocking state. Pending approval totals include all
pages; tax reviews are a bounded list. Source failures are shown as unavailable.
The Inbox also shows latest synced bank balances grouped by their original
currency, overdue unpaid invoices, unattached invoice/receipt documents and
unfinalized transactions with status `UNVERIFIED`. These task counts cover all
history. Transaction totals cover the previous and current calendar months, with
the date range displayed. Counts come from pagination totals, not
the single record requested with each counter. Overdue invoices use Norman's
stored overdue status; bank snapshots may lag the bank and are not profit.
Task buttons delegate work to the conversation with the selected company and
scope. The assistant can complete supported, evidence-backed document matching,
categorization and finalization through existing tools, then report verified
results and genuine blockers. Financial overview is analysis-only; invoice
follow-ups prepare drafts. External messages, payments, tax filing and automation
approvals require a separate decision. The iframe sends a chat request rather
than calling write tools itself; clients without messaging show a copyable request.
Button-generated messages use readable references to the Inbox selection. Internal
company and record IDs stay in structured app context, which is acknowledged before
sending. When that context is unavailable, the request asks the user to confirm the
company and relevant record; copyable requests also omit IDs.
Below the financial overview, **You can also ask Norman** shows three contextual
tasks with the remaining suggestions under **Explore more tasks**. Their order
stays stable for the selected company while the panel refreshes. Spending analysis,
tax readiness and accountant handover checks are read-only; invoice creation is
restricted to an unsent draft, and tax previews never authorize filing.
The additive `capabilities` object contains `ledger` and `taxPreview` discovery
hints. One company detail read enables Ledger suggestions only for SMEs with an
SKR03/SKR04 chart. A preview suggestion requires an existing prepared Autopilot
run with a report ID; a missing suggestion does not mean no tax reports exist.
Unknown eligibility hides specialized suggestions while general tasks remain
usable. Raw company details are omitted, and the host and API still enforce
tool availability and permissions.
The header shows the selected company's name, legal form and country. Its picker
loads non-archived companies on demand through `list_companies`, then switches
with `switch_company` and re-reads the Inbox. Switching clears old decisions,
confirmation and chat context before loading the replacement. An ambiguous timeout
keeps actions unavailable until the requested company is verified; the switch is
never automatically retried. The additive `company` profile reuses the existing
company lookup and excludes tax IDs, bank details and members.
On mobile, the Inbox has a bounded inner scroll area, uses host safe-area insets,
and condenses empty states and explanatory text. Standard host context controls
theme and dimensions, with legacy OpenAI globals and OS theme fallbacks. Sidebar
icons include explicit light and dark variants. Unbounded inline hosts retain
natural height; previously cached Inbox resource URIs remain available.
The review card uses existing approve/dismiss/undo tools and refreshes actual
results. Approval requires a checkbox and re-reads current values and planned
actions immediately before executing. A changed review requires confirmation
again. The backend remains responsible for atomic execution and permissions.
Non-transaction approvals whose current target is unavailable can be discussed or
dismissed; they cannot be approved from this card.

The visible Inbox refreshes through `get_norman_inbox_data` 30 seconds after a
completed read and backs off to 60, 120 and at most 300 seconds while nothing on
screen changes; any interaction or change resets it to 30. Focus or becoming
visible refreshes only once half the current interval has passed. It pauses while
hidden/offscreen, during actions, on teardown, and after an expired session until
the user acts. It keeps the selected page and typed workflow answer (a draft is
bound to its question; if the question changes, sending needs confirmation); an
unchanged approval keeps explicit consent, while changed current values or
planned actions clear it. This uses the portable Apps `tools/call` bridge: iframe support for
SDK 2 resource subscriptions is not assumed.

Hosted SDK 2 clients can separately opt into resource invalidations by setting
`NORMAN_MCP_INBOX_LIVE=1` on a **single-process** MCP deployment using the
streamable-http transport (SSE starts one lifespan per connection, so the flag is
ignored there with a warning). Credential-only stdio does not enable this feature. Existing tools and legacy refresh continue
working when the setting is absent.

1. Call `watch_norman_inbox` with an approval `page` (default 1). It returns an
   opaque `resourceUri`, `expiresAt` (Unix seconds), and observation interval.
2. Open SDK 2 `subscriptions/listen` for that exact URI. After acknowledgment,
   call `resources/read` for the current snapshot; refetch on each
   `notifications/resources/updated`. Events contain only the opaque URI.
3. Reopen the watch after expiry, reconnect, token refresh, restart, or an
   attempted `switch_company`. Watches last at most five minutes and never
   outlive their MCP bearer token. There is no replay; always refetch on reconnect.

Read and listen both check the exact OAuth grant, client and selected company.
Observers resolve only that grant's current Norman token and pin its company.
An expired Norman token (one hour) is refreshed through that grant; a 401 that
survives the refresh, or a 403, closes the watch. Local grant revocation, company changes and expiry
end its stream within one second. The observer reads only while a stream is
connected, with 30 seconds between observation cycles. Each watch observes one
approval page, workflow state, bounded tax reviews, discovery capabilities and the Inbox overview; it is not a complete
company event log and may miss intermediate changes. Financial snapshots are
never cached in the change bus. There are at most 128 leases/streams, four leases
and four open streams per OAuth grant, four concurrent snapshot reads (normally
ten API requests per snapshot) and two per grant. The grant-pinned reader
permits only GET requests.
Tokens refreshed from one authorization
share its grant, so refreshing does not raise these limits.

Leases and the SDK subscription bus are in memory. Use one process/replica;
multiple replicas require shared lease state, OAuth state and a distributed
subscription bus before this feature can be enabled reliably. This read-only
feed is separate from the durable webhook events below.

The opt-in `workflow.attention_required` event implements the
[draft MCP Events contract](https://developers.openai.com/plugins/build/mcp-events)
on SDK 2 / protocol `2026-07-28`. It watches one explicitly selected company and
workflow through the Norman API and sends signed webhooks when the active run
becomes blocked. It does not advance workflows, send invoice reminders or file
taxes. Current delivery waits 30 seconds between source observation cycles; it does not yet
consume a backend event stream and can miss transitions between observations.

To enable events on a hosted **single-worker** Streamable HTTP deployment, set:

- `NORMAN_MCP_EVENTS_DB`: an absolute SQLite path on a persistent private volume.
- `NORMAN_MCP_EVENTS_KEY`: a Fernet encryption key from your secret manager. Keep
  the same key across restarts; changing it makes stored subscriptions unreadable.

Start with `norman-mcp --transport streamable-http --public-url https://your-host`.
Both settings are required. Without them, events are not advertised. SQLite state
contains encrypted authentication references, callback URLs, signing keys and
pending payloads. Persist the existing `MCP_OAUTH_STATE_FILE` on a private volume
as well: delivery after restart needs valid OAuth tokens and Norman token mappings.
The worker reads each run with the subscriber's own grant and company; an
expired Norman access token (one hour) is refreshed through that grant, and a
grant that cannot be refreshed suspends delivery until the client refreshes the
subscription. Nothing falls back to other credentials. Multiple worker
processes/replicas require coordinated OAuth storage and a distributed delivery
lease before enabling events.

Subscriptions use `events/list`, `events/subscribe` and `events/unsubscribe`, with
arguments `{ "company_id": "UUID", "run_id": "UUID" }` and webhook delivery
`{ "mode": "webhook", "url": "https://public-callback", "secret": "whsec_…" }`.
The receiver must echo the signed verification challenge. Subscription lifetime
is capped at one hour and authentication expiry; renew before `refreshBefore`.
Secret rotation accepts the previous signing key for five minutes. Each retry
keeps the same `eventId`; receivers should deduplicate by it. Permanent callback
failures stop retries until the subscription is renewed, and HTTP 410 removes
the subscription. Callback addresses are validated and DNS-pinned to public HTTPS
endpoints; redirects are not followed. Each callback, verification included, has
15 seconds in total and runs in a small dedicated pool.

Host support, plugin submission and production activation need separate
verification. Local protocol and browser fixtures do not establish ChatGPT
catalog availability or a successful production OAuth/webhook connection.
