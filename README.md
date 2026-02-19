<div align="center">
   <a href="https://norman.finance/?utm_source=mcp_server">
      <img width="140px" src="https://github.com/user-attachments/assets/d2cb1df3-69f1-460e-b675-beb677577b06" alt="Norman" />
   </a>
   <h1>Norman MCP Server</h1>
   <p>Your finances, inside your AI assistant.<br/>
   Norman connects your accounting, invoicing, and VAT filing directly to Claude, Cursor, and any MCP-compatible AI.</p>
   <br/>
   <p>
      <img src="https://img.shields.io/badge/Protocol-MCP-black?style=flat-square" alt="MCP" />
      <img src="https://img.shields.io/badge/Transport-Streamable_HTTP-black?style=flat-square" alt="Streamable HTTP" />
      <img src="https://img.shields.io/badge/Auth-OAuth_2.1-black?style=flat-square" alt="OAuth 2.1" />
      <img src="https://img.shields.io/badge/License-MIT-black?style=flat-square" alt="MIT" />
   </p>
   <code>https://mcp.norman.finance/mcp</code>
   <br/><br/>
   <strong>Claude</strong> &nbsp;·&nbsp; <strong>ChatGPT</strong> &nbsp;·&nbsp; <strong>Cursor</strong> &nbsp;·&nbsp; <strong>n8n</strong> &nbsp;·&nbsp; <strong>Any MCP Client</strong>
</div>

<br/>

---

<br/>

### What you can do

**Invoicing** — Create, send, and track invoices including recurring and ZUGFeRD e-invoices

**Bookkeeping** — Categorize transactions, match receipts, and verify entries

**Client Management** — Maintain your client database and contact details

**Tax Filing** — Generate Finanzamt previews, file VAT returns, and track deadlines

**Company Overview** — Check your balance, revenue, and financial health at a glance

**Documents** — Upload and attach receipts, invoices, and supporting files

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

1. Go to [claude.ai/settings/connectors](https://claude.ai/settings/connectors)
2. Click **Add custom connector**
3. Paste:

```
https://mcp.norman.finance/mcp
```
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
<summary><strong>ChatGPT Apps</strong></summary>
<br/>

1. Open **Settings → Apps → Advanced**
2. Click **Create App**
3. Paste:

```
https://mcp.norman.finance/mcp
```
</details>

<details>
<summary><strong>Cursor</strong></summary>
<br/>

[![Install MCP Server](https://cursor.com/deeplink/mcp-install-dark.svg)](https://cursor.com/en-US/install-mcp?name=norman-finance&config=eyJ1cmwiOiJodHRwczovL21jcC5ub3JtYW4uZmluYW5jZS9tY3AifQ%3D%3D)
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

<br/>

> **Claude Code** &nbsp;—&nbsp; `/plugin marketplace add norman-finance/norman-mcp-server`
>
> **Claude Code (local)** &nbsp;—&nbsp; `claude --plugin-dir ./norman-mcp-server`
>
> **OpenClaw** &nbsp;—&nbsp; `cp -r skills/<skill-name> ~/.openclaw/skills/`

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
