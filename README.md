<div align="center">
   <a href="https://norman.finance/?utm_source=mcp_server">
      <img width="140px" src="https://github.com/user-attachments/assets/d2cb1df3-69f1-460e-b675-beb677577b06" alt="Norman" />
   </a>
   <h1>Norman MCP Server</h1>
   <p>German accounting, from daily transactions to the annual close, inside your AI assistant.<br/>
   Norman connects invoicing, SKR03/SKR04 bookkeeping, the Ledger, assets, taxes, and company workflows to any MCP-compatible AI.</p>
   <br/>
   <p>
      <img src="https://img.shields.io/badge/Protocol-MCP-black?style=flat-square" alt="MCP" />
      <img src="https://img.shields.io/badge/Transport-Streamable_HTTP-black?style=flat-square" alt="Streamable HTTP" />
      <img src="https://img.shields.io/badge/Auth-OAuth_2.1-black?style=flat-square" alt="OAuth 2.1" />
      <img src="https://img.shields.io/badge/License-MIT-black?style=flat-square" alt="MIT" />
   </p>
   <code>https://mcp.norman.finance/mcp</code>
   <br/><br/>
   <strong>Claude</strong> &nbsp;·&nbsp; <strong>ChatGPT</strong> &nbsp;·&nbsp; <strong>Cursor</strong> &nbsp;·&nbsp; <strong>OpenClaw</strong> &nbsp;·&nbsp; <strong>n8n</strong> &nbsp;·&nbsp; <strong>Any MCP Client</strong>
</div>
<br/>
<div align="center">

   <a href="https://github.com/user-attachments/assets/10718781-34f2-4640-9253-be4c82de6159"></a>
</div>
<br/>

---

<br/>

### What you can do

**Invoicing** — Create, send, and track invoices including recurring and ZUGFeRD e-invoices

**Daily bookkeeping** — Categorize transactions, split line items, match receipts, manage vendors, and verify entries

**Company accounting** — Configure SKR03/SKR04 charts of accounts, inspect the accounting setup, create manual postings, and export DATEV data

**Ledger & reports** — Review the journal, trial balance (SuSa), account sheets, open items, cash book, profit and loss, and balance sheet

**Assets & annual close** — Maintain the asset register, calculate depreciation, add closing entries, and review annual-close workbooks

**Automation rules** — "Always book Telekom to Internet costs": preview, create, and manage rules that categorize matching transactions automatically

**Client Management** — Maintain your client database and contact details

**Tax workflows** — Review tax reports, validate tax data, generate ELSTER previews, and track deadlines before an explicitly confirmed submission

**Company Overview** — Check your balance, revenue, and financial health at a glance

**Company Formation** — Found a German **GmbH or UG**: collect the founders' data, check the name against the Handelsregister, generate the founding documents (Musterprotokoll, Gesellschafterliste), match with a notary, and track every step through to registration

**Documents** — Create receipts, invoices, and supporting documents from Norman upload references, HTTPS URLs, small base64 payloads, and structured metadata

<br/>

### 💬 Try asking

Once connected, talk to your books in plain language:

- *"Generate the ELSTER preview for last month's UStVA and show me what needs attention."*
- *"Send a €1,200 invoice to ACME for consulting."*
- *"What did I spend on software this quarter?"*
- *"Show the newest Ledger postings and explain the tax treatment."*
- *"Review the 2025 trial balance before I start the annual close."*
- *"Find tax deductions I might have missed."*
- *"Which invoices are overdue? Send reminders."*

<br/>

### 🏢 Starting a company

Found a German **GmbH or UG (haftungsbeschränkt)** end-to-end — Norman collects the data, prepares the documents, and hands off to a notary:

- *"I want to start a GmbH in Berlin — walk me through it."*
- *"Found a UG for me and two co-founders, split the shares 60/40."*
- *"Is 'Wunderbar Robotics' still free in the Handelsregister?"*
- *"Reword my business purpose so it's ready for the register."*
- *"Generate the Musterprotokoll and find me a notary who does online notarization."*
- *"What's left before my company is officially registered?"*

> A GmbH or UG can keep its books with **SKR03 or SKR04**. Norman can provision the selected framework and preserve imported or custom accounts. Formation documents are drafts to prepare the notary appointment — not legal advice.

<br/>

### How company accounting fits together

Transactions, vendors, assets, payroll, opening balances, and manual entries are the inputs. Norman turns them into balanced postings in the Ledger. The Ledger then powers the journal, SuSa, open items, cash book, P&L, balance sheet, year-end review, and company tax workflows.

```text
Transactions + Assets + Opening data + Manual entries
                         │
                         ▼
                       Ledger
                         │
             ┌───────────┼───────────┐
             ▼           ▼           ▼
          Reports   Annual close   Tax previews
```

The remote MCP server is the recommended connection. It uses OAuth and keeps the active Norman company in the authenticated session.

For tax workflows, **preview and submission are separate operations**. A client or agent should inspect the preview and ask for explicit user confirmation immediately before any irreversible filing or other external action.

See [MCP priorities and parity roadmap](docs/MCP_ROADMAP.md) for shipped coverage and the next product priorities.

<br/>

### Document ingestion and external archives

An external archive can already send a document through a Norman temporary `file_ref`, a reachable HTTPS `file_url`, or a small base64 payload. It can also provide structured fields such as supplier/customer, invoice number, dates, amounts, currency, VAT, document type, and transaction links. Norman can skip OCR when the required structured fields are already present, or use OCR to complete missing data.

| Input path | Current status |
|---|---|
| Norman upload page → temporary `file_ref` | Supported |
| Public or short-lived signed HTTPS URL | Supported |
| Small base64 payload | Supported, size-limited |
| Structured invoice metadata | Supported |
| Native file attached directly to a ChatGPT tool call | Planned; requires the official MCP `openai/fileParams` file-object contract |
| Atomic deduplication, match-or-create, provenance, batch status, and webhooks | Planned |

For normal PDFs, use `file_ref` or a signed HTTPS URL rather than base64. A URL must remain reachable long enough for Norman to download it. Files sent to the remote Norman MCP server leave the AI host and are processed under Norman's security, residency, and retention controls.

The target archive workflow is:

```text
Document archive → Norman ingest + validation → bookkeeping/bank matching → DATEV/tax advisor
```

See the [external document archive ingestion](docs/MCP_ROADMAP.md#2-external-document-archive-ingestion) P0 item for the portable `ingest_document` contract and native ChatGPT attachment work.

<br/>

<details open>
<summary>
<h3>👀 See it in action</h3>
</summary>
<br/>
<table>
   <tr>
      <td align="center">
         <p><strong>Filing a VAT return</strong></p>
         <img src="https://github.com/user-attachments/assets/00bdf6df-1e37-4ecd-9f12-2747d8f53484" alt="Filing VAT tax report" width="400">
      </td>
      <td align="center">
         <p><strong>Transaction insights</strong></p>
         <img src="https://github.com/user-attachments/assets/534c7aac-4fed-4b28-8a5e-3a3411e13bca" alt="Transaction insights" width="400">
      </td>
   </tr>
   <tr>
      <td align="center">
         <p><strong>Syncing Stripe payments</strong></p>
         <img src="https://github.com/user-attachments/assets/2f13bc4e-6acb-4b39-bddc-a4a1ca6787f0" alt="Syncing Stripe payments" width="400">
      </td>
      <td align="center">
         <p><strong>Receipts from Gmail</strong></p>
         <img src="https://github.com/user-attachments/assets/2380724b-7a79-45a4-93bd-ddc13a175525" alt="Creating transactions from Gmail receipts" width="200">
      </td>
   </tr>
   <tr>
      <td align="center">
         <p><strong>Chasing overdue invoices</strong></p>
         <img src="https://github.com/user-attachments/assets/d59ed22a-5e75-46f6-ad82-db2f637cf7a2" alt="Managing overdue invoices" width="300">
      </td>
      <td align="center">
         <p><strong>Sending payment reminders</strong></p>
         <img src="https://github.com/user-attachments/assets/26cfb8e9-4725-48a9-b413-077dfb5902e7" alt="Sending payment reminders" width="350">
      </td>
   </tr>
</table>
</details>

<br/>

---

<br/>

## 🚀 Get Started

Before connecting, [create a free Norman account](https://app.norman.finance/sign-up?utm_source=mcp_server) if you don't have one yet. Log in with your Norman credentials via OAuth — your password never touches the AI.

<details>
<summary><strong>Claude Connectors</strong></summary>
<br/>

1. Go to [Claude Connectors](https://claude.ai/new#settings/customize-connectors)
2. Click **Add**
3. Find and connect: **Norman Finance**
</details>

<details>
<summary><strong>Claude Code</strong></summary>
<br/>

Norman is available as a [Claude Code plugin](https://code.claude.com/docs/en/plugins) with built-in skills.

```bash
/plugin marketplace add norman-finance/norman-mcp-server
/plugin install norman-finance@norman-finance
```

Or install directly from GitHub:

```bash
claude /plugin install github:norman-finance/norman-mcp-server
```
</details>

<details>
<summary><strong>ChatGPT Plugins</strong></summary>
<br/>

1. Install it from the official [ChatGPT Plugins Directory](https://chatgpt.com/plugins/plugin_asdk_app_6981ec32565481919b1c5a1627b1e330).

</details>

<details>
<summary><strong>Cursor</strong></summary>
<br/>

[![Install MCP Server](https://cursor.com/deeplink/mcp-install-dark.svg)](https://cursor.com/en-US/install-mcp?name=norman-finance&config=eyJ1cmwiOiJodHRwczovL21jcC5ub3JtYW4uZmluYW5jZS9tY3AifQ%3D%3D)
</details>

<details>
<summary><strong>Replit</strong></summary>
<br/>

[![Add to Replit](https://replit.com/badge?caption=Add%20to%20Replit)](https://replit.com/integrations?mcp=eyJkaXNwbGF5TmFtZSI6Ik5vcm1hbiBNQ1AgU2VydmVyIiwiYmFzZVVybCI6Imh0dHBzOi8vbWNwLm5vcm1hbi5maW5hbmNlL21jcCJ9)
</details>

<details>
<summary><strong>OpenClaw</strong></summary>
<br/>

**Option 1 — Remote with OAuth**

Run in OpenClaw:

```
mcp add https://mcp.norman.finance/mcp
```

You'll be prompted to log in with your Norman account on first use.

**Option 2 — Skills only**

```bash
git clone https://github.com/norman-finance/norman-mcp-server.git
cp -r norman-mcp-server/skills/* ~/.openclaw/skills/
openclaw gateway restart
```

**Option 3 — Local stdio**

```bash
pip install norman-mcp-server
```

```bash
openclaw mcp add norman -- norman-mcp --transport stdio
```

Set your credentials as environment variables (`NORMAN_EMAIL`, `NORMAN_PASSWORD`) before starting the gateway.
</details>

<details>
<summary><strong>n8n</strong></summary>
<br/>

1. Create an **MCP OAuth2 API** credential
2. Enable **Dynamic Client Registration**
3. Set Server URL: `https://mcp.norman.finance/`
4. Click **Connect my account** and log in with Norman
5. Add an **MCP Client Tool** node to your AI Agent workflow
6. Set the URL to `https://mcp.norman.finance/mcp` and select the credential
</details>

<details>
<summary><strong>Any MCP Client</strong></summary>
<br/>

Add a remote HTTP MCP server with URL:

```
https://mcp.norman.finance/mcp
```
</details>

<br/>

---

<br/>

## Skills

Ready-to-use skills compatible with **Claude Code**, **OpenClaw**, and the [Agent Skills](https://agentskills.io) standard.

| Skill | What it does |
|:--|:--|
| `financial-overview` | Full dashboard — balance, transactions, invoices, and tax status |
| `create-invoice` | Step-by-step invoice creation and sending |
| `manage-clients` | List, create, and update client records |
| `tax-report` | Review and preview tax reports; submit only after explicit confirmation |
| `categorize-transactions` | Categorize and verify bank transactions |
| `suggest-category` | Suggest the best bookkeeping category for a transaction |
| `find-receipts` | Find missing receipts from Gmail or email and attach them |
| `overdue-reminders` | Identify overdue invoices and send payment reminders |
| `expense-report` | Expense breakdown by category, top vendors, and trends |
| `tax-deduction-finder` | Scan transactions for missed deductions and suggest fixes |
| `monthly-reconciliation` | Full monthly close — transactions, invoices, receipts, and taxes |
| `company-incorporation` | Found a German GmbH/UG — data, documents, name check, and notary hand-off |
| `corporate-tax-registration` | Prepare the corporate tax registration questionnaire for a GmbH/UG |
| `gewerbe-registration` | Prepare a German trade registration workflow |
| `ta-company-review` | Tax-advisor review of a company's books and compliance status |
| `ta-datev-preparation` | Prepare a company and its bookkeeping data for DATEV hand-off |
| `ta-missing-receipts` | Review missing receipts across tax-advisor companies |
| `ta-tax-compliance` | Review company filing status, deadlines, and tax compliance |

<br/>

> **Claude Code** &nbsp;—&nbsp; `/plugin marketplace add norman-finance/norman-mcp-server`
>
> **Claude Code (local)** &nbsp;—&nbsp; `claude --plugin-dir ./norman-mcp-server`
>
> **OpenClaw** &nbsp;—&nbsp; `cp -r skills/* ~/.openclaw/skills/ && openclaw gateway restart`

<br/>

---

<br/>

<p align="center">
   Have a feature idea? <a href="../../issues"><strong>Share your suggestion →</strong></a>
</p>

<br/>

<p align="center">
   <a href="https://glama.ai/mcp/servers/@norman-finance/norman-mcp-server"><img src="https://glama.ai/mcp/servers/@norman-finance/norman-mcp-server/badge" alt="Norman Finance MCP server" width="200" /></a>&nbsp;&nbsp;&nbsp;
   <a href="https://mseep.ai/app/norman-finance-norman-mcp-server"><img src="https://mseep.net/pr/norman-finance-norman-mcp-server-badge.png" alt="MseeP.ai Security Assessment" height="41" /></a>
</p>

<p align="center">
   <br/>
   <a href="https://norman.finance/?utm_source=mcp_server">
      <img width="80px" src="https://github.com/user-attachments/assets/d2cb1df3-69f1-460e-b675-beb677577b06" alt="Norman" />
   </a>
   <br/><br/>
   <sub>Make business effortless</sub>
</p>

<!-- mcp-name: finance.norman/mcp-server -->
