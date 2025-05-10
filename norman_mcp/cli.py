#!/usr/bin/env python
"""Command line interface for the Norman Finance MCP server."""

import os
import argparse
import logging
from dotenv import load_dotenv

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
    if args.host:
        os.environ["NORMAN_MCP_HOST"] = args.host
    if args.port:
        os.environ["NORMAN_MCP_PORT"] = str(args.port)
    if args.public_url:
        os.environ["NORMAN_MCP_PUBLIC_URL"] = args.public_url


def main():
    """Main entry point for the CLI."""
    # Load environment variables
    load_dotenv()
    
    parser = argparse.ArgumentParser(description='Norman Finance MCP Server with OAuth')
    parser.add_argument('--email', help='Norman Finance account email (optional)')
    parser.add_argument('--password', help='Norman Finance account password (optional)')
    parser.add_argument('--environment', choices=['production', 'sandbox'], default='production',
                        help='API environment (production or sandbox)')
    parser.add_argument('--timeout', type=int, help='API request timeout in seconds')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument("--host", type=str, default=os.environ.get("NORMAN_MCP_HOST", "0.0.0.0"), 
                        help="Host to bind to")
    parser.add_argument("--port", type=int, default=int(os.environ.get("NORMAN_MCP_PORT", "3001")), 
                        help="Port to bind to")
    parser.add_argument("--public-url", type=str, 
                        default=os.environ.get("NORMAN_MCP_PUBLIC_URL", 
                                              f"http://{os.environ.get('NORMAN_MCP_HOST', '0.0.0.0')}:{os.environ.get('NORMAN_MCP_PORT', '3001')}"), 
                        help="Public URL for OAuth callbacks")
    parser.add_argument('--transport', choices=['stdio', 'sse'], default='sse',
                       help='Transport protocol to use (default: sse)')
    
    args = parser.parse_args()
    
    # Set up logging level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Set up environment variables before importing server
    setup_environment(args)
    
    # Import server module after environment setup
    from .server import create_app
    
    # Create and run the server
    try:
        # Log information about the server
        logger.info(f"Starting Norman MCP server with OAuth authentication")
        logger.info(f"Server listening on http://{args.host}:{args.port}")
        logger.info(f"Using transport: {args.transport}")
        logger.info(f"Using email: {os.environ.get('NORMAN_EMAIL', '')}")
        logger.info(f"Using environment: {os.environ.get('NORMAN_ENVIRONMENT', 'production')}")
        
        # Create the app with the provided arguments
        mcp = create_app(host=args.host, port=args.port, public_url=args.public_url, transport=args.transport)
        
        # Run the server
        mcp.run(transport=args.transport)

    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Error running server: {str(e)}")
        raise


if __name__ == "__main__":
    main() 