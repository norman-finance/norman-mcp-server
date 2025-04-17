"""Main entry point for the Norman Finance MCP server."""

from .server import mcp

if __name__ == "__main__":
    # Call mcp.run() directly - it handles its own event loop
    mcp.run() 