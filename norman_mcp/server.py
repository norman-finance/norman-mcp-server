import os
import logging
from typing import Any, Dict
from mcp.server.fastmcp import FastMCP, Context
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from norman_mcp.api.client import NormanAPI
from norman_mcp.tools.clients import register_client_tools
from norman_mcp.tools.invoices import register_invoice_tools
from norman_mcp.tools.taxes import register_tax_tools
from norman_mcp.tools.transactions import register_transaction_tools
from norman_mcp.tools.documents import register_document_tools
from norman_mcp.tools.company import register_company_tools
from norman_mcp.prompts.templates import register_prompts
from norman_mcp.resources.endpoints import register_resources

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Server context manager for startup/shutdown
@asynccontextmanager
async def lifespan(ctx: FastMCP):
    """Context manager for startup/shutdown events."""
    # Setup
    api_client = NormanAPI()
    # Create a context dictionary to yield
    context = {"api": api_client}
    
    yield context
    
    # Cleanup - nothing needed for now

# Create the MCP server with guardrails
mcp = FastMCP(
    "Norman Finance API", 
    lifespan=lifespan,
    guardrails={
        "block_indirect_prompt_injections_in_tool_output": True,
        "block_looping_tool_calls": True,
        "block_moderated_content_in_tool_output": True,
        "block_pii_in_tool_output": False,  # Set to false because we need to handle financial data with PII
        "block_secrets_in_messages": True,
        "prevent_empty_user_messages": True, 
        "prevent_prompt_injections_in_user_input": True,
        "prevent_urls_in_agent_output": True,
    }
)

# Register all modules
register_client_tools(mcp)
register_invoice_tools(mcp)
register_tax_tools(mcp)
register_transaction_tools(mcp)
register_document_tools(mcp)
register_company_tools(mcp)
register_prompts(mcp)
register_resources(mcp)

if __name__ == "__main__":
    # This will be used by the MCP CLI
    mcp.run()