# Remote Hosting Guide for Norman MCP Server

This guide explains how to configure the Norman MCP server for remote hosting so it can be accessed from anywhere, not just localhost.

## Environment Variables

The server now reads these environment variables for configuration:

- `NORMAN_MCP_HOST`: The host address to bind to (default: "0.0.0.0")
- `NORMAN_MCP_PORT`: The port to bind to (default: 3001)
- `NORMAN_MCP_PUBLIC_URL`: The public URL where the server can be accessed (default: "http://{HOST}:{PORT}")

## Remote Hosting Setup

### 1. Server Configuration

To make your server available remotely, you need to:

1. Set the `NORMAN_MCP_PUBLIC_URL` to your public domain or IP address:

```bash
# Using a domain
export NORMAN_MCP_PUBLIC_URL="https://norman-mcp.example.com"

# Or using a public IP
export NORMAN_MCP_PUBLIC_URL="http://203.0.113.1:3001"
```

2. Launch the server with the appropriate parameters:

```bash
python -m norman_mcp.server --transport sse --public-url "https://norman-mcp.example.com"
```

### 2. Using with MCP Inspector or Claude Desktop

When connecting from MCP Inspector or Claude Desktop, you need to:

1. Set the API URL to your public address:
   - For example: `https://norman-mcp.example.com`

2. Ensure OAuth is enabled

### 3. Security Considerations

For production environments:

1. Use HTTPS with a valid certificate for your domain
2. Configure firewalls to restrict access as needed
3. Modify `norman_mcp/auth/provider.py` to use stricter redirect URI validation
4. Set up proper user authentication and authorization

## Tunneling for Development

For development, you can use tools like ngrok to make your localhost accessible over the internet:

```bash
# Install ngrok
npm install -g ngrok

# Start Norman MCP server
python -m norman_mcp.server --transport sse

# In another terminal, create a tunnel
ngrok http 3001
```

Then use the ngrok URL (e.g., https://abcd1234.ngrok.io) as your `NORMAN_MCP_PUBLIC_URL`.

## Troubleshooting

### CORS Issues

If you experience CORS issues, make sure your public URL is properly configured and that clients are using the correct URL.

### OAuth Failures

If OAuth authentication fails:

1. Check that your redirect URIs are being accepted
2. Verify that you're using the correct public URL
3. Make sure the Norman API token is being correctly obtained and stored 