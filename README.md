<div align="center">
   <a href="https://norman.finance/?utm_source=mcp_server">
      <img width="140px" src="https://github.com/user-attachments/assets/d2cb1df3-69f1-460e-b675-beb677577b06" alt="Norman" />
   </a>
   <h1>Norman MCP Server</h1>
   <p>AI-powered bookkeeping, accounting, and taxes for European businesses, inside your AI assistant.<br/>
   Norman connects invoicing, transactions, receipts, ledgers, reports, taxes, and company workflows to any MCP-compatible AI.</p>
   <br/>
   <p>
      <img src="https://img.shields.io/badge/Protocol-MCP-black?style=flat-square" alt="MCP" />
      <img src="https://img.shields.io/badge/Transport-Streamable_HTTP-black?style=flat-square" alt="Streamable HTTP" />
      <img src="https://img.shields.io/badge/Auth-OAuth_2.1-black?style=flat-square" alt="OAuth 2.1" />
      <img src="https://img.shields.io/badge/License-MIT-black?style=flat-square" alt="MIT" />
   </p>
   <code>https://mcp.norman.finance/mcp</code>
   <br/><br/>
   <strong>Claude</strong> &nbsp;·&nbsp; <strong>ChatGPT</strong> &nbsp;·&nbsp; <strong>Gemini</strong> &nbsp;·&nbsp; <strong>Grok</strong> &nbsp;·&nbsp; <strong>Perplexity</strong> &nbsp;·&nbsp; <strong>Cursor</strong> &nbsp;·&nbsp; <strong>Any MCP Client</strong>
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

**Bookkeeping** — Categorize transactions, match receipts, and verify entries

**Automation rules** — "Always book Telekom to Internet costs": preview, create, and manage rules that categorize matching transactions automatically

**Client Management** — Maintain your client database and contact details

**Tax Filing** — Generate Finanzamt previews, file VAT returns, and track deadlines

**Company Overview** — Check your balance, revenue, and financial health at a glance

**Company Formation** — Found a German **GmbH or UG**: collect the founders' data, check the name against the Handelsregister, generate the founding documents (Musterprotokoll, Gesellschafterliste), match with a notary, and track every step through to registration

**Documents** — Upload and attach receipts, invoices, and supporting files

Norman is built as a multi-market European accounting platform. Market-specific capabilities are added as Norman expands; current German coverage includes SKR03/SKR04, DATEV, ELSTER, ZUGFeRD, and GmbH/UG workflows.

<br/>

### 💬 Try asking

Once connected, talk to your books in plain language:

- *"Prepare and file my UStVA for last month."*
- *"Send a €1,200 invoice to ACME for consulting."*
- *"What did I spend on software this quarter?"*
- *"Find tax deductions I might have missed."*
- *"Which invoices are overdue? Send reminders."*

<br/>

### Interactive UI inside your AI assistant

Norman is more than a collection of background tools. In MCP Apps-compatible
ChatGPT and Claude clients, Norman can render focused accounting workspaces
directly inside the conversation. You can filter and inspect the underlying
data, move between related views, and use **Ask AI** to continue the discussion
with the current accounting context.

| Interactive workspace | Use case |
|:--|:--|
| **Document Review** | Review uploaded invoices and receipts, find documents that still need a transaction match, and inspect linked records. |
| **Reconciliation Cockpit** | Find transactions with missing documents, missing categories, or accounts from a previous SKR before month-end or year-end close. |
| **Ledger Explorer** | Browse the chart of accounts, inspect balances, and drill into the postings behind an account. |
| **Tax Preview & Submission** | Review the Finanzamt test PDF, tax lines, period, total, and readiness checks before filing. Submission is a separate explicit action and stays disabled until the user confirms the preview. |

Try prompts such as:

- *"Open my Document Review for the last 60 days."*
- *"Show my Reconciliation Cockpit and highlight missing documents or categories."*
- *"Open the Ledger Explorer and show the postings for account 1200."*
- *"Open my VAT return for July, generate the Finanzamt test preview, and explain anything I should review before submission."*

The Norman API remains the source of truth. Opening or filtering a workspace
does not change accounting data. Binding actions, including tax submission,
remain separate MCP tool calls with their normal confirmation and permission
checks. Clients without MCP Apps support receive the same underlying results as
structured or text tool output.

<br/>

### 🏢 Starting a company

Found a German **GmbH or UG (haftungsbeschränkt)** end-to-end — Norman collects the data, prepares the documents, and hands off to a notary:

- *"I want to start a GmbH in Berlin — walk me through it."*
- *"Found a UG for me and two co-founders, split the shares 60/40."*
- *"Is 'Wunderbar Robotics' still free in the Handelsregister?"*
- *"Reword my business purpose so it's ready for the register."*
- *"Generate the Musterprotokoll and find me a notary who does online notarization."*
- *"What's left before my company is officially registered?"*

> Choosing GmbH/UG also sets your Norman account to the corporate **SKR04** chart of accounts, so bookkeeping and taxes are ready from day one. The documents are drafts to prepare the notary appointment — not legal advice.

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

MCP Apps-compatible Claude hosts can open Norman's [interactive accounting
workspaces](#interactive-ui-inside-your-ai-assistant) directly in the
conversation. Other Claude clients receive the same data as normal tool output.
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

The plugin includes Norman's [interactive accounting
workspaces](#interactive-ui-inside-your-ai-assistant), including Document
Review, Reconciliation, Ledger Explorer, and the explicit tax preview and
submission flow.

</details>

<details>
<summary><strong>Gemini</strong></summary>
<br/>

**Gemini CLI extension**

```bash
gemini extensions install https://github.com/norman-finance/norman-mcp-server
```

Start Gemini CLI and authenticate the remote server when prompted, or run:

```text
/mcp auth norman-finance
```

**Gemini Spark custom app**

Create a Spark, add a custom app, and use
`https://mcp.norman.finance/mcp` as its MCP server URL. Availability depends on
your Gemini account and region. See Google's [custom app
guide](https://support.google.com/gemini/answer/17209137).
</details>

<details>
<summary><strong>Perplexity</strong></summary>
<br/>

1. Open **Account settings → Connectors**
2. Click **+ Custom Connector** and select **Remote**
3. Enter **Norman Finance** and `https://mcp.norman.finance/mcp`
4. Save the connector and complete Norman OAuth

Organization administrators can share the remote connector with their team.
</details>

<details>
<summary><strong>Grok</strong></summary>
<br/>

**Grok web**

1. Go to [Grok Connectors](https://grok.com/connectors)
2. Click **New Connector → Custom**
3. Enter `https://mcp.norman.finance/mcp` and complete Norman OAuth

**Grok CLI**

```bash
grok mcp add --transport http norman-finance https://mcp.norman.finance/mcp
```

Grok CLI also discovers this repository's `.mcp.json` automatically.
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
| `tax-report` | Review, preview, and file tax reports with the Finanzamt |
| `categorize-transactions` | Categorize and verify bank transactions |
| `find-receipts` | Find missing receipts from Gmail or email and attach them |
| `overdue-reminders` | Identify overdue invoices and send payment reminders |
| `expense-report` | Expense breakdown by category, top vendors, and trends |
| `tax-deduction-finder` | Scan transactions for missed deductions and suggest fixes |
| `monthly-reconciliation` | Full monthly close — transactions, invoices, receipts, and taxes |
| `company-incorporation` | Found a German GmbH/UG — data, documents, name check, and notary hand-off |

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
   <a href="https://mcpbeat.com/mcp-servers/norman/mcp-server/"><img src="https://mcpbeat.com/badge/norman/mcp-server.svg" alt="mcpbeat"></a>
   <a href="https://glama.ai/mcp/servers/@norman-finance/norman-mcp-server"><img src="https://glama.ai/mcp/servers/@norman-finance/norman-mcp-server/badge" alt="Norman Finance MCP server" width="200" /></a>&nbsp;&nbsp;&nbsp;
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
