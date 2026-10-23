<div align="center">
   <a href="https://norman.finance/?utm_source=mcp_server">
      <img width="140" src="https://github.com/user-attachments/assets/d2cb1df3-69f1-460e-b675-beb677577b06" alt="Norman" />
   </a>
   <h1>Norman MCP Server</h1>
   <p>Invoicing, full accounting, year-end preparation and taxes for freelancers<br/>and small businesses in the EU, including Germany and Poland.</p>
   <p>
      <img src="https://img.shields.io/badge/Protocol-MCP-black?style=flat-square" alt="MCP" />
      <img src="https://img.shields.io/badge/Transport-Streamable_HTTP-black?style=flat-square" alt="Streamable HTTP" />
      <img src="https://img.shields.io/badge/Auth-OAuth_2.1-black?style=flat-square" alt="OAuth 2.1" />
      <img src="https://img.shields.io/badge/License-MIT-black?style=flat-square" alt="MIT" />
   </p>
   <code>https://mcp.norman.finance/mcp</code>
</div>

<p align="center">
   <a href="#what-you-can-do">Capabilities</a> ·
   <a href="#get-started">Connect</a> ·
   <a href="#germany-accounting-vat-and-year-end">Germany</a> ·
   <a href="#poland-kpir-full-books-and-jpk">Poland</a> ·
   <a href="#documentation">Documentation</a>
</p>

Connect Norman Finance to your AI assistant to create invoices, organize receipts,
reconcile transactions, keep your books up to date and prepare tax returns.
Work from the same company records you use in the Norman app.

Use the remote MCP connection with Claude, ChatGPT, Gemini, Grok, Perplexity,
Cursor and other compatible clients. [Client setup instructions](docs/connecting.md)
distinguish directory installs, extensions and custom connections.

## See Norman in action

https://github.com/user-attachments/assets/10718781-34f2-4640-9253-be4c82de6159

[Watch the full Norman demo](https://github.com/user-attachments/assets/10718781-34f2-4640-9253-be4c82de6159) ·
[Explore workflow examples](docs/gallery.md) ·
[Watch the Poland introduction](#poland-kpir-full-books-and-jpk)

## What you can do

| Workflow | Ask Norman to help you |
| :-- | :-- |
| **Invoicing** | Create and send invoices, quotes and recurring invoices. Use your branding, product catalog, VAT codes, discounts and service dates. |
| **Bookkeeping** | Organize receipts, categorize and verify transactions, match documents and reconcile your books. |
| **Full accounting** | Inspect accounts, journal entries, balances and reports. Follow a figure back to its source documents. |
| **VAT and taxes** | Calculate and review VAT, prepare returns and submit supported German returns after explicit confirmation. Review Polish registers, estimates and existing filing status. |
| **Year-end preparation** | Review balances, prepare a German annual-close workspace and closing adjustments, or inspect existing Polish financial statements. |
| **Clients and reminders** | Manage clients, track invoice delivery and prepare or send payment reminders when requested. |
| **Automation** | Preview bookkeeping rules, start month-end or reconciliation workflows, answer their questions and schedule recurring work. |

### Try asking

- "Create a draft invoice for consulting and use my saved company branding."
- "Which transactions are missing a receipt?"
- "What did we spend on software this quarter?"
- "Review my books and tell me what still needs attention before year-end."
- "Prepare my German VAT return preview. Do not submit it yet."
- "Show my Polish company's JPK register and explain excluded operations."

<a id="-get-started"></a>

## Get started

1. [Create a Norman account](https://app.norman.finance/sign-up?utm_source=mcp_server), or use your existing one.
2. Add Norman in your AI client's directory or as a remote HTTP MCP server:
   `https://mcp.norman.finance/mcp`.
3. Complete Norman OAuth, then confirm the company you want to work with.

For clients that accept an MCP configuration file:

```json
{
  "mcpServers": {
    "norman-finance": {
      "url": "https://mcp.norman.finance/mcp"
    }
  }
}
```

**Using Claude Code?**

```bash
/plugin marketplace add norman-finance/norman-mcp-server
/plugin install norman-finance@norman-finance
```

[All setup guides](docs/connecting.md): Claude Connectors, Claude Code, ChatGPT,
Gemini, Grok, Perplexity, Cursor, Replit, OpenClaw, n8n and other MCP clients.

Your company is the accounting context, not the language of the conversation.
Use `list_companies` and `switch_company` to change it; `company://current`
identifies its country, currency, legal form and chart of accounts.

## Market-specific capabilities

One connection supports both Germany and Poland. The workflows differ by jurisdiction:

| | Germany | Poland |
| :-- | :-- | :-- |
| **Bookkeeping** | SKR03/SKR04, transactions and Ledger | KPiR for JDG; full books for sp. z o.o. |
| **VAT and tax review** | Finanzamt previews, VAT and annual reports | JPK registers, PIT/ZUS or CIT estimates |
| **Year-end** | Draft annual close, closing adjustments and workbook review | Review already prepared statements, notes and XML issues |
| **Accountant handoff** | DATEV EXTF exports and preflight checks | General, Optima and EPP export compatibility previews |
| **Filing through MCP** | Supported returns after preview and explicit confirmation | Existing filing status and UPO checks; no signing or submission |

## Germany: accounting, VAT and year-end

Keep day-to-day bookkeeping and full GmbH/UG accounting connected to the same AI
workflow. Review SKR03/SKR04 accounts, reconcile transactions, calculate VAT and
prepare supported VAT and annual tax returns.

For year-end, create a **Draft annual-close workspace**, review the workbook and
post closing adjustments. Preparing that workspace does not lock the year or
submit a return. Tax submission is a separate, explicitly confirmed action.

German invoice workflows also support **ZUGFeRD**, cancellations
(**Stornorechnung**), corrections (**Rechnungskorrektur**) and delivery notes
(**Lieferschein**).

Additional workflows include German GmbH/UG payroll and company-formation
preparation. Payroll tools cover calculation, approval, payslips and supported
Lohnsteuer-Anmeldung filing; sensitive employee identifiers stay in the app.
Formation tools prepare draft documents and a notary handoff, not a legal incorporation
by chat. [Detailed workflows](docs/tool-workflows.md).

### DATEV MCP support: EXTF, SKR03 and SKR04

Prepare a **DATEV EXTF Buchungsstapel** with **SKR03 or SKR04** for your tax advisor
(**Steuerberater**), with linked documents when requested. The complete GmbH/UG
Ledger export includes opening balances, manual entries, payroll, depreciation
and closing postings.

- `trigger_datev_export`: prepare the export and download package.
- `validate_ledger_datev_export`: check structure, source coverage and documents before handoff.
- `read_datev_file`: inspect an **EXTF/DTVF** file without importing postings into your books.

Try: "Check the full GmbH Ledger export before I give it to my accountant."

[DATEV details and API requirements](docs/tool-workflows.md#datev-files-and-complete-ledger-exports).
Validation is a handoff check, not certification of tax correctness or DATEV import acceptance.

## Poland: KPiR, full books and JPK

### Cześć, Polsko

https://github.com/user-attachments/assets/aea417ad-64aa-4623-896f-ff8dc4559d4a

**[Watch the Poland film](docs/assets/poland-en-pl-subtitles.mp4)** · 24 seconds ·
English on-screen text with Polish subtitles built into the video.

This is a product introduction, not a recording of MCP tool calls.
The [Polish landing page](https://norman.finance/pl/mcp) and
[English landing page](https://norman.finance/pl/en/mcp) introduce the connection
in each language.

### What the Polish tools cover

- **JDG / KPiR:** review monthly or annual tax books and explain why an operation
  is included or excluded.
- **Sp. z o.o. / full books:** inspect the journal, chart of accounts, account
  sheets and trial balance; review prepared financial statements and their notes.
- **VAT / JPK_V7:** compare sales, purchases, totals and exclusions with source operations.
- **Tax estimates and status:** review PIT/ZUS or CIT estimates, existing JPK/PIT
  filing status and UPO availability.
- **Invoices, receipts and assets:** use shared tools with Polish VAT codes,
  document currencies and depreciation inputs; create proforma quotes and record
  incoming bills in their original currency. Search receipts by supplier and date.
- **Ryczałt settings:** propose a revenue category's rate for the owner to review
  and apply in Norman. The assistant does not change tax settings directly.
- **Import review and routines:** inspect CSV import batches, preview an exact
  batch rollback, and confirm or dismiss detected routines. A rollback requires
  the user's approval and the preview token; confirming a routine does not send invoices.
- **Accountant handoff:** preview General, Optima or EPP compatibility and review blockers.

Try asking:

- "Pokaż KPiR mojej JDG za wrzesień i wyjaśnij pominięte koszty."
- "Pokaż zestawienie obrotów i sald mojej spółki za trzeci kwartał."
- "Sprawdź rejestr JPK_V7: sprzedaż, zakupy i pominięte operacje."
- "Sprawdź status wysyłki JPK i dostępność UPO. Niczego nie wysyłaj."

The Polish MCP tools do **not** sign or submit returns to MF/KRS, create manual
Polish journal postings, or generate or close annual statements. They inspect
existing filing state; an XML download is not an acceptance receipt or UPO.

[Polish tool guide, arguments and examples](docs/polish-accounting.md) ·
[Public/internal sync details](docs/pl-internal-sync-2026-10-23.md) ·
[Start with a Polish company](https://app.norman.finance/sign-up?country=PL&lang=pl&utm_source=mcp_server)

## Interactive UI inside your AI assistant

MCP Apps-compatible hosts can show focused accounting workspaces inside the conversation:

| Workspace | What you can review |
| :-- | :-- |
| **Norman Inbox** | Balances, bookkeeping tasks, blocked workflows and pending approvals |
| **Document Review** | Uploaded invoices, receipts and missing transaction matches |
| **Reconciliation Cockpit** | Missing documents, categories and bookkeeping issues |
| **German Ledger Explorer** | SKR accounts, balances and linked postings |
| **German Tax Preview & Submission** | Finanzamt test PDF, tax lines and readiness checks before a separate confirmed filing |

Clients without MCP Apps support receive structured or text results.
Polish accounting uses the [dedicated structured tools](docs/polish-accounting.md);
the German workspaces do not imply equivalent Polish filing functionality.

## Skills

Ready-to-use skills compatible with **Claude Code**, **OpenClaw**, and the [Agent Skills](https://agentskills.io) standard.

| Skill | What it does |
|:--|:--|
| `financial-overview` | Full dashboard : balance, transactions, invoices, and tax status |
| `create-invoice` | Step-by-step invoice creation and sending |
| `manage-clients` | List, create, and update client records |
| `manage-products` | List, create, update, and archive catalog products; fill invoice lines from them |
| `tax-report` | German reports: review, preview, and file with the Finanzamt |
| `run-payroll-month` | German payroll : changes, calculation, approval, social insurance, payment, and Lohnsteuer-Anmeldung |
| `categorize-transactions` | Categorize and verify bank transactions |
| `find-receipts` | Find missing receipts from Gmail or email and attach them |
| `overdue-reminders` | Identify overdue invoices and send payment reminders |
| `expense-report` | Expense breakdown by category, top vendors, and trends |
| `tax-deduction-finder` | Scan transactions for missed deductions and suggest fixes |
| `monthly-reconciliation` | Full monthly close : transactions, invoices, receipts, and taxes |
| `run-workflow` | Start a Norman workflow, answer its questions, and schedule it to run by itself |
| `company-incorporation` | Found a German GmbH/UG : data, documents, name check, and notary hand-off |


Browse the [skills directory](skills). Each skill guides an accounting task
while the Norman API enforces access and action permissions.

## Control and privacy

- **You choose the company.** Company-scoped records stay in the selected accounting context.
- **Review before binding actions.** Tax filing, payments, external messages and automation approvals require their own decision.
- **Keep sensitive identifiers in Norman.** Complete restricted identity and payment setup in the app, not in chat.
- **Check the result.** A draft, preview, queued request or downloaded XML is not proof of filing or payment success.

Polish KPiR and estimate reads can synchronize derived records and therefore
declare `readOnlyHint=false`. Country and book-type guards prevent German
procedures from being applied to Polish books. Technical rollout and tool-specific
limits are documented in the linked guides.

## Documentation

| Guide | Contents |
| :-- | :-- |
| [Connect your AI client](docs/connecting.md) | Hosted OAuth, client installs and local options |
| [Polish accounting](docs/polish-accounting.md) | KPiR, full books, JPK, estimates, filing status and limits |
| [Tool workflows](docs/tool-workflows.md) | Invoice settings, emails, uploads, company formation and DATEV details |
| [German VAT item workflows](docs/vat-item-workflows.md) | Mixed VAT, input tax, refunds and corrections |
| [Norman Inbox and MCP Events](docs/inbox-and-events.md) | UI behavior, resource subscriptions and optional webhook deployment |
| [Workflow gallery](docs/gallery.md) | Invoices, transactions, documents and VAT examples |

<details>
<summary>Links retained from earlier README versions</summary>

<a id="invoice-appearance-and-updates"></a>

[Invoice appearance and updates](docs/tool-workflows.md#invoice-appearance-and-updates)

<a id="client-emails-and-payment-reminders"></a>

[Client emails and payment reminders](docs/tool-workflows.md#client-emails-and-payment-reminders)

<a id="mixed-vat-and-documented-input-tax"></a>

[Mixed VAT and documented input tax](docs/tool-workflows.md#mixed-vat-and-documented-input-tax)

<a id="norman-inbox-and-mcp-events-development"></a>

[Norman Inbox and MCP Events](docs/inbox-and-events.md)

<a id="datev-files-and-complete-ledger-exports"></a>

[DATEV files and complete Ledger exports](docs/tool-workflows.md#datev-files-and-complete-ledger-exports)

</details>

---

[Website](https://norman.finance/?utm_source=mcp_server) ·
[Report an issue or suggest a feature](https://github.com/norman-finance/norman-mcp-server/issues) ·
[MIT license](LICENSE)

<p align="center">
   <a href="https://mcpbeat.com/mcp-servers/norman/mcp-server/"><img src="https://mcpbeat.com/badge/norman/mcp-server.svg" alt="mcpbeat"></a>
   <a href="https://glama.ai/mcp/servers/@norman-finance/norman-mcp-server"><img src="https://glama.ai/mcp/servers/@norman-finance/norman-mcp-server/badge" alt="Norman Finance MCP server" width="200" /></a>
</p>

<!-- mcp-name: finance.norman/mcp-server -->
