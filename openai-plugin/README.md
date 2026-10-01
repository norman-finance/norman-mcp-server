# Norman OpenAI plugin package

This directory owns the portable upload for the existing Norman plugin,
`plugin_asdk_app_6981ec32565481919b1c5a1627b1e330`. It retains the original
package name and existing OAuth MCP endpoint at `https://mcp.norman.finance/mcp`.
The hosted server owns UI resources; this ZIP contains metadata, skills and
the brand icon, with no credentials or generated app bindings.

## Build

Run from the repository root with Python 3.10 or later:

```sh
python openai-plugin/build.py /tmp/app-6981ec32565481919b1c5a1627b1e330-2.1.0.zip
```

The build includes all canonical `skills/` and their text references, followed
by the six additions in `openai-plugin/skills/`. It sorts files and fixes ZIP
timestamps and permissions for deterministic output. Version 2.1.0 contains
27 skills. The icon is the existing Norman mobile icon.

The five interactive workflows are Inbox, Document Review, Reconciliation
Cockpit, Ledger Explorer and tax test-preview. Rendering document, reconciliation
and Ledger views requires the complete, unchanged result of their data tools.
`render_tax_preview` accepts a report ID and creates its own temporary preview;
do not also fetch `get_tax_filing_data` for the same preview.

## Standards changes in the server

Replacement, cancellation and irreversible workflow actions declare
`destructiveHint: true`. Enabling future client emails or external workflow
actions declares `openWorldHint: true`. The legacy category-template alias has
a distinct title. SKR AI suggestions remain bounded to the fixed SKR catalog,
even though computation uses OpenAI; the description now makes that boundary
explicit. A review clarification may still be necessary for that finding.

Corporate-registration tools omit known personal government-identifier fields
from returned objects and reject those fields as people inputs. If a replaced
people list already contains an identifier, editing is redirected to the
authenticated Norman form so hidden values cannot be discarded by replace-all
semantics. This projection leaves stored API records untouched. It is key-based
field minimization, not a general sensitive-data classifier.

## Portal state and remaining verification

On 2026-10-01, release 1.0.0 was published and release 2.0.1 was already in
review. Uploading a replacement was disabled until that review ends or is
cancelled. Obtain explicit authorization before cancelling review. Local source
changes and this package have not been deployed, uploaded, submitted or
published by preparing them.

The repeated MCP scan reported a review-service failure and partial prior
findings, not a finding against the server. Document, reconciliation, Ledger
and tax render tools appeared Live; the three Inbox tools appeared Not live.
An updated ZIP alone does not deploy or make held hosted tools available.

The ZIP provides five positive and three negative review cases from actual tool
contracts. They require a dedicated sample company and are **not authenticated
host test results**. Use its September 2026 receipts and transactions, a blocked
workflow, a pending approval, an SKR03 account 1200 with postings, and an existing
unsubmitted September VAT report. Review cases never approve, send, pay or file.

The package deliberately omits `demo_recording_url`, reviewer credentials,
commerce declarations, country targeting and translations. Omission preserves
saved portal values on an existing release import; it does not verify those
values. Read them back after upload and verify reviewer access. Enter credentials
only in secure portal fields, never in this ZIP or Git.

Before resubmitting, record and verify a reviewer-accessible demo of the new UI
using the positive prompts in `plugin.json`. Show OAuth connection, the selected
sample company, Inbox and approval inspection, an unmatched document, month-end
blockers, Ledger account drill-down and the tax **test** preview. Show the visible
result of each tool and the preview label; do not run a binding action. A script
does not replace an actual recording or host verification.

After authorized deployment, rescan the hosted MCP, resolve or appeal remaining
findings, and test all eight cases in the intended ChatGPT/Codex host. Then upload
the complete ZIP to the same plugin as a draft, verify imported fields, and finish
required portal review information. Review submission and publication are
separate actions; legal attestations belong to the publisher.

References: [package and submission](https://developers.openai.com/plugins/deploy/submission),
[plugin guidelines](https://developers.openai.com/plugins/plugin-guidelines),
[UI guidelines](https://developers.openai.com/plugins/concepts/ui-guidelines).
