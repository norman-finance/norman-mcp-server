# <div align="center">[Norman Finance](http://norman.finance?utm_source=mcp_server) MCP Server</div>
<div align="center"><img width="140px" src="https://github.com/user-attachments/assets/d2cb1df3-69f1-460e-b675-beb677577b06"></div>

This [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server enables AI to interact with the Norman Finance API, allowing access to accounting, invoices, companies, clients, taxes, and more through a standardized protocol.

> [!NOTE]
> 
> The Norman Finance MCP Server is currently in Beta. We welcome your feedback and encourage you to report any bugs by opening an issue [here](https://github.com/norman-finance/norman-mcp-server/issues).
  <table>
      <td align="center">
       <a href="https://glama.ai/mcp/servers/@norman-finance/norman-mcp-server">
  <img width="250" height="auto" src="https://glama.ai/mcp/servers/@norman-finance/norman-mcp-server/badge" alt="Norman Finance Server MCP server" />
</a>
      </td>
      <td align="center">
        <a href="https://mseep.ai/app/norman-finance-norman-mcp-server">
  <img src="https://mseep.net/pr/norman-finance-norman-mcp-server-badge.png" alt="MseeP.ai Security Assessment Badge" />
</a>
      </td>
    </tr>
  </table>

## Features

- 🔐 **Authentication**: Securely authenticate with the Norman Finance account
- 💼 **Company Management**: Manage your company details, get company balance, VAT insgihts, etc
- 📊 **Accounting**: Keep an eye on your transactions, categorization
- 📝 **(e-)Invoicing**: Make, view, send, and handle invoices. You can even set up recurring ones based on your contracts
- 👥 **Client Management**: Create and manage your clients (CRM)
- 💰 **Taxes**: View tax information and reports, generate official Finanzamt PDF previews and file your taxes
- 📄 **Documents**: Upload and manage attachments (receipts, invoices, docs, etc)

<details open><summary>

### 👇 Use case examples with Claude Desktop — toggle
</summary>
  <table>
    <tr>
      <td align="center">
        <p><strong>Filing VAT tax report</strong></p>
        <img src="https://github.com/user-attachments/assets/00bdf6df-1e37-4ecd-9f12-2747d8f53484" alt="Filing VAT tax report using Norman MCP" width="400">
      </td>
      <td align="center">
        <p><strong>Getting transaction insights</strong></p>
        <img src="https://github.com/user-attachments/assets/534c7aac-4fed-4b28-8a5e-3a3411e13bca" alt="Getting transaction insights usin Norman MCP" width="400">
      </td>
    </tr>
    <tr>
      <td align="center">
        <p><strong>Syncing Stripe payments with Norman</strong></p>
        <img src="https://github.com/user-attachments/assets/2f13bc4e-6acb-4b39-bddc-a4a1ca6787f0" alt="Syncing Stripe payments with Norman" width="400">
      </td>
       <td align="center">
        <p><strong>Creating transactions using Gmail receipts</strong></p>
        <img src="https://github.com/user-attachments/assets/2380724b-7a79-45a4-93bd-ddc13a175525" alt="Creating transactions using Gmail receipts" width="200">
      </td>
    </tr>
    <tr>
      <td align="center">
        <p><strong>Managing overdue invoices - 1</strong></p>
        <img src="https://github.com/user-attachments/assets/d59ed22a-5e75-46f6-ad82-db2f637cf7a2" alt="Managing overdue invoices - 1" width="300">
      </td>
      <td align="center">
        <p><strong>Managing overdue invoices - 2</strong></p>
        <img src="https://github.com/user-attachments/assets/26cfb8e9-4725-48a9-b413-077dfb5902e7" alt="Managing overdue invoices - 2" width="350">
      </td>
    </tr>
  </table>
</details>

## Prerequisites

Before using this MCP server, you need to:

1. Create an account on [Norman Finance](https://app.norman.finance/sign-up?utm_source=mcp_server)
2. Have your email and password ready for authentication

## Remote MCP Server
Norman now offers a hosted remote MCP server at:

> https://mcp.norman.finance/sse

The remote MCP is recommended because it utilizes OAuth authentication, enabling you to log in directly with your Norman account without the need to create or manage access tokens manually.

## Installation

### Cursor

To add the Norman MCP server to Cursor, copy and paste the following deeplink into your browser:
```markdown
cursor://anysphere.cursor-deeplink/mcp/install?name=norman-finance-mcp&config=eyJjb21tYW5kIjoibnB4IiwidHlwZSI6InNzZSIsImFyZ3MiOlsibWNwLXJlbW90ZSIsImh0dHBzOi8vbWNwLm5vcm1hbi5maW5hbmNlL3NzZSJdfQ==
```

---

### [Claude.ai Integrations](https://www.anthropic.com/news/integrations)
Adding the Norman MCP Server to Claude.ai:

**For Claude Max:**
1. Head to _Settings > Profile_
2. Find the "Integrations" section
3. Tap "Add more"
4. Enter the Norman MCP server URL: ```https://mcp.norman.finance/sse```
5. Click "Add" to finish up

**For Claude Enterprise & Teams:**
1. Go to _Settings > Integrations_ (for Teams) or _Settings > Data management_ (for Enterprise)
2. Find the "Integrations" section
3. Hit "Add more"
4. Enter the Norman MCP server URL: ```https://mcp.norman.finance/sse```
5. Click "Add" to finish up

**Enabling the Norman Integration:**
1. Start a chat with Claude.
2. Open the _Search and tools menu_.
3. Click "Connect" to link your Norman account.
4. <img width="400" alt="image" src="https://github.com/user-attachments/assets/5edfac9c-1fbd-4443-a831-d93bee3b8e15" />
5. After connecting, use the same menu to turn on specific Norman tools.

---

### Adding to Claude Desktop

To run the Norman Finance MCP server with Claude Desktop, you can use the instruction above or add it manually using the following steps:

#### 1. Download and Configure Claude Desktop

1. Download [Claude Desktop](https://claude.ai/download).

2. Launch Claude and navigate to: Settings > Developer > Edit Config.

3. Update your `claude_desktop_config.json` file with the following configuration:

#### Remote MCP
```json
{
  "mcpServers": {
    "norman-mcp-server": {
      "command": "npx",
      "args": ["mcp-remote", "https://mcp.norman.finance/sse"]
    }
  }
}
```
#### Local MCP

#### Install uv

Follow the instructions here: [Installing uv](https://docs.astral.sh/uv/getting-started/installation/)

```json
{
  "mcpServers": {
    "norman-mcp-server": {
      "command": "<home_path>/.local/bin/uvx",
      "args": [
        "--from",
        "norman-mcp-server@latest",
        "norman-mcp"
      ],
      "env": {
        "NORMAN_EMAIL": "your-email@example.com",
        "NORMAN_PASSWORD": "your-password",
        "NORMAN_ENVIRONMENT": "production"
      }
    }
  }
}
```

## Configuration

### Authentication Methods

The Norman MCP server supports two authentication methods:

#### 1. OAuth Authentication (for SSE transport)

When using the server with MCP Inspector, Claude, or other SSE clients, the server uses OAuth 2.0 authentication:

1. Start the server with SSE transport:
   ```bash
   python -m norman_mcp --transport sse
   ```

2. When connecting to the server, you'll be directed to a login page
3. Enter your Norman Finance credentials
4. You'll be redirected back to your application with authentication tokens

#### 2. Environment Variables (for stdio transport)

When using the server with Claude Desktop or stdin/stdout communication, provide credentials through environment variables:

```bash
# .env
NORMAN_EMAIL=your-email@example.com
NORMAN_PASSWORD=your-password
NORMAN_ENVIRONMENT=production  # or "sandbox" for the development environment
NORMAN_API_TIMEOUT=200  # Request timeout in seconds
```

### Environment Variables

The server can be configured using these environment variables:

```bash
# Authentication (for stdio transport)
NORMAN_EMAIL=your-email@example.com
NORMAN_PASSWORD=your-password
NORMAN_ENVIRONMENT=production  # or "sandbox" for the development environment

# Server configuration
NORMAN_MCP_HOST=0.0.0.0  # Host to bind to
NORMAN_MCP_PORT=3001     # Port to bind to
NORMAN_MCP_PUBLIC_URL=http://example.com  # Public URL for OAuth callbacks (important for remote access)
NORMAN_API_TIMEOUT=200   # Request timeout in seconds
```

## Development

This section is for contributors who want to develop or extend the Norman Finance MCP server.

### Local setup

```bash
git clone https://github.com/norman-finance/norman-mcp-server.git
cd norman-mcp-server
pip install -e .
```

Then update your claude_desktop_config.json file to point to the Python module directly:

```json
{
  "mcpServers": {
    "norman-mcp-server": {
      "command": "<path_to_your_python>/python",
      "args": ["-m", "norman_mcp"],
      "env": {
        "NORMAN_EMAIL": "your-email@example.com",
        "NORMAN_PASSWORD": "your-password",
        "NORMAN_ENVIRONMENT": "production"
      }
    }
  }
}
```

Do you have a feature idea or something you'd like to see? [Share your suggestion](../../issues)

---

<p align="center">
Make business effortless <div align="center"><img width="140px" src="https://github.com/user-attachments/assets/d2cb1df3-69f1-460e-b675-beb677577b06"></div>
</p>
