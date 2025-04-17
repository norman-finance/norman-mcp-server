"""Command line interface for the Norman Finance MCP server."""

import os
import argparse
import logging
from dotenv import load_dotenv

from .server import mcp

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def setup_environment(args):
    """Set up environment variables from command line arguments."""
    if args.email:
        os.environ["NORMAN_EMAIL"] = args.email
    if args.password:
        os.environ["NORMAN_PASSWORD"] = args.password
    if args.environment:
        os.environ["NORMAN_ENVIRONMENT"] = args.environment
    if args.timeout:
        os.environ["NORMAN_API_TIMEOUT"] = str(args.timeout)


def main():
    """Main entry point for the CLI."""
    # Load environment variables
    load_dotenv()
    
    parser = argparse.ArgumentParser(description='Norman Finance MCP Server')
    parser.add_argument('--email', help='Norman Finance account email')
    parser.add_argument('--password', help='Norman Finance account password')
    parser.add_argument('--environment', choices=['production', 'sandbox'], 
                        help='API environment (production or sandbox)')
    parser.add_argument('--timeout', type=int, help='API request timeout in seconds')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    # Set up logging level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Set up environment variables
    setup_environment(args)
    
    # Run the server
    try:
        # Call mcp.run() directly - it handles its own event loop
        mcp.run()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Error running server: {str(e)}")
        raise


if __name__ == "__main__":
    main() 