#!/usr/bin/env python
"""
Test client for the Norman MCP Server with Streamable HTTP transport and OAuth.

This script connects to the Norman MCP server using the Streamable HTTP transport
with OAuth authentication and tests basic functionality by listing available tools.

Usage:
    python streamable_http_client.py [server_url]
    
    Example:
        python streamable_http_client.py http://localhost:3001
"""

import asyncio
import logging
import sys
import os
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import AnyUrl

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)


class InMemoryTokenStorage(TokenStorage):
    """In-memory token storage implementation for OAuth tokens."""

    def __init__(self):
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        """Get stored tokens."""
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        """Store tokens."""
        self.tokens = tokens
        logger.info(f"Stored OAuth tokens: access_token={tokens.access_token[:20]}...")

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        """Get stored client information."""
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        """Store client information."""
        self.client_info = client_info
        logger.info(f"Stored client info: client_id={client_info.client_id}")


async def handle_redirect(auth_url: str) -> None:
    """Handle OAuth redirect by printing the URL for the user to visit."""
    print(f"\n{'='*60}")
    print("OAuth Authorization Required")
    print(f"{'='*60}")
    print(f"\nPlease visit this URL to authorize:\n\n{auth_url}\n")


async def handle_callback() -> tuple[str, str | None]:
    """Handle OAuth callback by prompting user for the callback URL."""
    print("\nAfter authorizing, paste the callback URL here:")
    callback_url = input("> ").strip()
    
    # Parse the callback URL to extract code and state
    parsed = urlparse(callback_url)
    params = parse_qs(parsed.query)
    
    code = params.get("code", [None])[0]
    state = params.get("state", [None])[0]
    
    if not code:
        raise ValueError("No authorization code found in callback URL")
    
    logger.info(f"Extracted authorization code: {code[:10]}...")
    return code, state


async def main():
    """Connect to the Norman MCP server and test basic functionality."""
    # Default server URL - can be overridden with a command line argument
    server_url = os.environ.get("NORMAN_MCP_URL", "http://localhost:3001")
    if len(sys.argv) > 1:
        server_url = sys.argv[1]

    # Ensure the URL has the /mcp path for streamable HTTP
    mcp_endpoint = f"{server_url.rstrip('/')}/mcp"

    logger.info(f"Connecting to Norman MCP server at {mcp_endpoint}")
    logger.info(f"Using Streamable HTTP transport with OAuth authentication")

    # Set up OAuth authentication
    oauth_provider = OAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="Norman MCP Test Client",
            redirect_uris=[AnyUrl(f"{server_url}/oauth/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="norman.read norman.write",
        ),
        storage=InMemoryTokenStorage(),
        redirect_handler=handle_redirect,
        callback_handler=handle_callback,
    )

    # Connect to the Streamable HTTP server with OAuth
    try:
        # Create an HTTP client with OAuth authentication
        async with httpx.AsyncClient(
            auth=oauth_provider,
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=10.0),
        ) as http_client:
            async with streamable_http_client(
                mcp_endpoint,
                http_client=http_client,
            ) as (read_stream, write_stream, get_session_id):
                logger.info("Connected to server, initializing session...")

                # Create a client session
                async with ClientSession(read_stream, write_stream) as session:
                    # Initialize the connection
                    await session.initialize()
                    logger.info("Session initialized successfully!")
                    
                    # Get the session ID
                    session_id = get_session_id()
                    if session_id:
                        logger.info(f"Session ID: {session_id}")

                    # List available prompts
                    try:
                        logger.info("\n--- Listing available prompts ---")
                        prompts_result = await session.list_prompts()
                        prompts = prompts_result.prompts if hasattr(prompts_result, 'prompts') else prompts_result
                        logger.info(f"Available prompts: {[p.name for p in prompts]}")
                    except Exception as e:
                        logger.error(f"Error listing prompts: {e}")

                    # List available tools
                    try:
                        logger.info("\n--- Listing available tools ---")
                        tools_result = await session.list_tools()
                        tools = tools_result.tools if hasattr(tools_result, 'tools') else tools_result
                        logger.info(f"Available tools ({len(tools)} total):")
                        for tool in tools:
                            logger.info(f"  - {tool.name}: {tool.description[:50] if tool.description else 'No description'}...")
                    except Exception as e:
                        logger.error(f"Error listing tools: {e}")

                    # List available resources
                    try:
                        logger.info("\n--- Listing available resources ---")
                        resources_result = await session.list_resources()
                        resources = resources_result.resources if hasattr(resources_result, 'resources') else resources_result
                        logger.info(f"Available resources: {[r.uri for r in resources]}")
                    except Exception as e:
                        logger.error(f"Error listing resources: {e}")

                    # Try calling a simple tool
                    try:
                        logger.info("\n--- Calling list_clients tool ---")
                        result = await session.call_tool("list_clients", {})
                        logger.info(f"Tool result: {result}")
                    except Exception as e:
                        logger.error(f"Error calling tool: {e}")

    except Exception as e:
        logger.error(f"Connection error: {e}")
        import traceback
        traceback.print_exc()
        raise


async def main_simple():
    """Simplified connection without OAuth for testing basic connectivity."""
    server_url = os.environ.get("NORMAN_MCP_URL", "http://localhost:3001")
    if len(sys.argv) > 1:
        server_url = sys.argv[1]

    mcp_endpoint = f"{server_url.rstrip('/')}/mcp"

    logger.info(f"Connecting to Norman MCP server at {mcp_endpoint}")
    logger.info(f"Using Streamable HTTP transport (no OAuth)")

    try:
        async with streamable_http_client(
            mcp_endpoint,
            timeout=timedelta(seconds=30),
            sse_read_timeout=timedelta(seconds=300),
        ) as (read_stream, write_stream, get_session_id):
            logger.info("Connected to server, initializing session...")

            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                logger.info("Session initialized")
                
                session_id = get_session_id()
                logger.info(f"Session ID: {session_id}")

                tools_result = await session.list_tools()
                tools = tools_result.tools if hasattr(tools_result, 'tools') else tools_result
                logger.info(f"Available tools: {[t.name for t in tools]}")

    except Exception as e:
        logger.error(f"Connection error: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    # Check if --no-auth flag is passed for simple testing
    if "--no-auth" in sys.argv:
        sys.argv.remove("--no-auth")
        asyncio.run(main_simple())
    else:
        asyncio.run(main())
