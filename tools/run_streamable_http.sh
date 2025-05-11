#!/bin/bash

# Run Norman MCP Server with Streamable HTTP transport
# This script sets the necessary environment variables for authentication and starts the server

# Check if .env file exists and source it if it does
if [ -f .env ]; then
    source .env
fi

# Default values
HOST="0.0.0.0"
PORT=3001
PUBLIC_URL=""
STATELESS=false
JSON_RESPONSE=false
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
    --json-response)
      JSON_RESPONSE=true
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

if [ "$JSON_RESPONSE" = true ]; then
  ARGS+=("--json-response")
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
echo "Starting Norman MCP Server with Streamable HTTP transport"
echo "Host: $HOST"
echo "Port: $PORT"
echo "Public URL: $PUBLIC_URL"

if [ "$STATELESS" = true ]; then
  echo "Mode: Stateless (no session tracking)"
else
  echo "Mode: Stateful (with session tracking)"
fi

if [ "$JSON_RESPONSE" = true ]; then
  echo "Response format: JSON"
else
  echo "Response format: SSE streams"
fi

if [ ! -z "$EMAIL" ]; then
  echo "Using credentials for: $EMAIL"
fi

echo "Environment: $ENVIRONMENT"
echo ""

echo "Starting server with: python -m norman_mcp ${ARGS[@]}"
echo ""

# Start the server
python -m norman_mcp "${ARGS[@]}" 