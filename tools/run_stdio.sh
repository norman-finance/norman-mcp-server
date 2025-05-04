#!/bin/bash

# Run Norman MCP Server with stdio transport
# This script sets the necessary environment variables for authentication

# Check if .env file exists and source it if it does
if [ -f .env ]; then
    source .env
fi

# Set the environment variables if not already set
if [ -z "$NORMAN_EMAIL" ] || [ -z "$NORMAN_PASSWORD" ]; then
    # Prompt for credentials if not set in environment or .env file
    echo "Norman API Credentials"
    read -p "Email: " NORMAN_EMAIL
    read -sp "Password: " NORMAN_PASSWORD
    echo
    
    # Export the variables
    export NORMAN_EMAIL
    export NORMAN_PASSWORD
fi

echo "Starting Norman MCP server with stdio transport..."
echo "Using credentials for: $NORMAN_EMAIL"

# Run the server
python -m norman_mcp --transport stdio 