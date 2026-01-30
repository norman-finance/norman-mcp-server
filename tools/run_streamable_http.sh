#!/bin/bash

# Run Norman MCP Server with Streamable HTTP transport
# This script sets the necessary environment variables for authentication and starts the server
#
# Usage:
#   ./run_streamable_http.sh [options]
#
# Options:
#   --host HOST         Host to bind to (default: 0.0.0.0)
#   --port PORT         Port to bind to (default: 3001)
#   --public-url URL    Public URL for OAuth callbacks
#   --stateless         Run in stateless mode (no session tracking)
#   --sse-response      Use SSE streaming responses instead of JSON
#   --debug             Enable debug logging
#   --email EMAIL       Norman account email (optional, for stdio transport)
#   --password PASS     Norman account password (optional, for stdio transport)
#   --environment ENV   API environment: production or sandbox (default: production)

# Check if .env file exists and source it if it does
if [ -f .env ]; then
    source .env
fi

# Default values
HOST="0.0.0.0"
PORT=3001
PUBLIC_URL=""
STATELESS=false
SSE_RESPONSE=false
DEBUG=false
EMAIL=""
PASSWORD=""
ENVIRONMENT="production"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --host)
      HOST="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --public-url)
      PUBLIC_URL="$2"
      shift 2
      ;;
    --stateless)
      STATELESS=true
      shift
      ;;
    --sse-response)
      SSE_RESPONSE=true
      shift
      ;;
    --debug)
      DEBUG=true
      shift
      ;;
    --email)
      EMAIL="$2"
      shift 2
      ;;
    --password)
      PASSWORD="$2"
      shift 2
      ;;
    --environment)
      ENVIRONMENT="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# If public URL is not set, generate it
if [ -z "$PUBLIC_URL" ]; then
  PUBLIC_URL="http://${HOST}:${PORT}"
fi

# Build the command arguments
ARGS=("--host" "$HOST" "--port" "$PORT" "--public-url" "$PUBLIC_URL" "--transport" "streamable-http")

# Add optional arguments
if [ "$STATELESS" = true ]; then
  ARGS+=("--stateless")
fi

# JSON response is now the default, only add --sse-response if needed
if [ "$SSE_RESPONSE" = true ]; then
  ARGS+=("--sse-response")
fi

if [ "$DEBUG" = true ]; then
  ARGS+=("--debug")
fi

if [ ! -z "$EMAIL" ]; then
  ARGS+=("--email" "$EMAIL")
fi

if [ ! -z "$PASSWORD" ]; then
  ARGS+=("--password" "$PASSWORD")
fi

if [ ! -z "$ENVIRONMENT" ]; then
  ARGS+=("--environment" "$ENVIRONMENT")
fi

# Print server information
echo "========================================"
echo "Norman MCP Server - Streamable HTTP"
echo "========================================"
echo ""
echo "Host: $HOST"
echo "Port: $PORT"
echo "Public URL: $PUBLIC_URL"
echo "MCP Endpoint: ${PUBLIC_URL}/mcp"
echo ""

if [ "$STATELESS" = true ]; then
  echo "Mode: Stateless (no session tracking)"
else
  echo "Mode: Stateful (with session tracking)"
fi

if [ "$SSE_RESPONSE" = true ]; then
  echo "Response format: SSE streams"
else
  echo "Response format: JSON (default)"
fi

if [ ! -z "$EMAIL" ]; then
  echo "Using credentials for: $EMAIL"
fi

echo "Environment: $ENVIRONMENT"
echo ""
echo "OAuth endpoints:"
echo "  - Authorization: ${PUBLIC_URL}/authorize"
echo "  - Token: ${PUBLIC_URL}/token"
echo "  - Login: ${PUBLIC_URL}/norman/login"
echo ""
echo "Starting server with: python -m norman_mcp ${ARGS[@]}"
echo ""

# Start the server
python -m norman_mcp "${ARGS[@]}" 