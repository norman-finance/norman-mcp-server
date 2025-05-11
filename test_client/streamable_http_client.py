#!/usr/bin/env python
"""
Test client for the Norman MCP Server with Streamable HTTP transport.

This script connects to the Norman MCP server using the Streamable HTTP transport
and tests basic functionality by listing available tools.
"""

import asyncio
import logging
import sys
from datetime import timedelta

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)


async def main():
    """Connect to the Norman MCP server and test basic functionality."""
    # Default server URL - can be overridden with a command line argument
    server_url = "http://localhost:3001"
    if len(sys.argv) > 1:
        server_url = sys.argv[1]

    logger.info(f"Connecting to Norman MCP server at {server_url}")
    logger.info(f"Using Streamable HTTP transport (compatible with the server's streamable-http transport)")

    # Connect to the Streamable HTTP server with a longer timeout for debugging
    try:
        async with streamablehttp_client(
            server_url,
            timeout=timedelta(seconds=30),
            sse_read_timeout=timedelta(seconds=300),
        ) as (read_stream, write_stream, get_session_id):
            logger.info("Connected to server, initializing session...")

            # Create a client session
            async with ClientSession(read_stream, write_stream) as session:
                # Initialize the connection
                await session.initialize()
                logger.info("Session initialized")
                
                # Get the session ID
                session_id = get_session_id()
                logger.info(f"Session ID: {session_id}")

                # List available prompts
                try:
                    logger.info("Listing available prompts...")
                    prompts = await session.list_prompts()
                    logger.info(f"Available prompts: {[p.name for p in prompts]}")
                except Exception as e:
                    logger.error(f"Error listing prompts: {e}")

                # List available tools
                try:
                    logger.info("Listing available tools...")
                    tools = await session.list_tools()
                    logger.info(f"Available tools: {[t.name for t in tools]}")
                except Exception as e:
                    logger.error(f"Error listing tools: {e}")

                # List available resources
                try:
                    logger.info("Listing available resources...")
                    resources = await session.list_resources()
                    logger.info(f"Available resources: {resources}")
                except Exception as e:
                    logger.error(f"Error listing resources: {e}")

                # Call a simple tool if available
                try:
                    logger.info("Calling list_clients tool...")
                    result = await session.call_tool("list_clients", {})
                    logger.info(f"Tool result: {result}")
                except Exception as e:
                    logger.error(f"Error calling tool: {e}")

    except Exception as e:
        logger.error(f"Connection error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main()) 