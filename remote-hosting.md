# Remote Hosting Guide for Norman MCP Server

This guide explains how to configure the Norman MCP server for remote hosting so it can be accessed from anywhere, not just localhost.

## Environment Variables

The server now reads these environment variables for configuration:

- `NORMAN_MCP_HOST`: The host address to bind to (default: "0.0.0.0")
- `NORMAN_MCP_PORT`: The port to bind to (default: 3001)
- `NORMAN_MCP_PUBLIC_URL`: The public URL where the server can be accessed (default: "http://{HOST}:{PORT}")

## Transport Options

The Norman MCP server supports three different transport protocols:

### SSE (Server-Sent Events)

The default transport method, best for web-based clients:

```bash
python -m norman_mcp --transport sse
```

### StreamableHTTP

A newer transport method that offers better performance and flexibility:

```bash
# Run with default options (stateful mode with SSE responses)
python -m norman_mcp --transport streamable_http

# Run in stateless mode (no session tracking)
python -m norman_mcp --transport streamable_http --stateless

# Use JSON responses instead of SSE streams
python -m norman_mcp --transport streamable_http --json-response
```

### stdio (Standard Input/Output)

For command-line tools or local use, requires credentials in environment variables:

```bash
python -m norman_mcp --transport stdio
```

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
# For SSE transport
python -m norman_mcp --transport sse --public-url "https://norman-mcp.example.com"

# For StreamableHTTP transport
python -m norman_mcp --transport streamable_http --public-url "https://norman-mcp.example.com"
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

# Start Norman MCP server (with your preferred transport)
python -m norman_mcp --transport streamable_http

# In another terminal, create a tunnel
ngrok http 3001
```

Then use the ngrok URL (e.g., https://abcd1234.ngrok.io) as your `NORMAN_MCP_PUBLIC_URL`.

## Streamable HTTP vs SSE

When deciding which transport to use, consider these factors:

1. **Compatibility**: SSE has wider client compatibility, while StreamableHTTP is newer but more flexible.
2. **Performance**: StreamableHTTP can offer better performance for high-traffic scenarios.
3. **Features**:
   - **Stateless Mode**: StreamableHTTP can operate in stateless mode, which is useful for serverless environments.
   - **JSON Responses**: StreamableHTTP can return JSON responses instead of SSE streams, which may be easier to process for some clients.

For most use cases, either transport will work well. The StreamableHTTP transport provides backward compatibility with SSE clients.

## Troubleshooting

If you experience issues with remote hosting:

1. Check your firewall settings to ensure the server port is open
2. Verify that your `NORMAN_MCP_PUBLIC_URL` is correctly set and accessible
3. For SSL/TLS issues, ensure your certificates are valid
4. Check the server logs for any error messages 