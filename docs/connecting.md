# Connect Norman to your AI assistant

Before connecting, [create a free Norman account](https://app.norman.finance/sign-up?utm_source=mcp_server) if you don't have one yet. Log in with your Norman credentials via OAuth — your password never touches the AI.

For a Polish business, use [Polish signup](https://app.norman.finance/sign-up?country=PL&lang=pl&utm_source=mcp_server).
After connecting, confirm the selected company through `company://current`
before inspecting or changing its books.

<details>
<summary><strong>Claude Connectors</strong></summary>
<br/>

1. Go to [Claude Connectors](https://claude.ai/new#settings/customize-connectors)
2. Click **Add**
3. Find and connect: **Norman Finance**

MCP Apps-compatible Claude hosts can open Norman's [interactive accounting
workspaces](../README.md#interactive-ui-inside-your-ai-assistant) directly in the
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
workspaces](../README.md#interactive-ui-inside-your-ai-assistant), including Document
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

[Back to the overview](../README.md)
