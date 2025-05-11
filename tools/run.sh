#!/bin/bash

# Run Norman MCP Server with different transport options
# This script sets up a Norman MCP server with the specified transport

# Check if .env file exists and source it if it does
if [ -f .env ]; then
    source .env
fi

# Default values
HOST="0.0.0.0"
PORT=3001
PUBLIC_URL=""
TRANSPORT="sse"
DEBUG=false
EMAIL=""
PASSWORD=""
ENVIRONMENT="production"
STATELESS=false
JSON_RESPONSE=false

# Usage information
usage() {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  --transport TRANSPORT    Transport protocol to use (sse, stdio, streamable-http)"
    echo "  --host HOST              Host to bind to"
    echo "  --port PORT              Port to bind to"
    echo "  --public-url URL         Public URL for OAuth callbacks"
    echo "  --debug                  Enable debug logging"
    echo "  --email EMAIL            Norman Finance account email"
    echo "  --password PASSWORD      Norman Finance account password"
    echo "  --environment ENV        API environment (production or sandbox)"
    echo "  --stateless              Run streamable-http transport in stateless mode"
    echo "  --json-response          Use JSON responses for streamable-http transport"
    echo "  --help                   Show this help message"
    exit 1
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --help)
      usage
      ;;
    --transport)
      TRANSPORT="$2"
      shift 2
      ;;
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
    --stateless)
      STATELESS=true
      shift
      ;;
    --json-response)
      JSON_RESPONSE=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      usage
      ;;
  esac
done

# Validate transport option
if [[ "$TRANSPORT" != "sse" && "$TRANSPORT" != "stdio" && "$TRANSPORT" != "streamable-http" ]]; then
  echo "Error: Invalid transport option. Must be 'sse', 'stdio', or 'streamable-http'."
  usage
fi

# If public URL is not set, generate it based on host and port
if [ -z "$PUBLIC_URL" ]; then
  PUBLIC_URL="http://${HOST}:${PORT}"
fi

# Build the command arguments
ARGS=("--host" "$HOST" "--port" "$PORT" "--public-url" "$PUBLIC_URL" "--transport" "$TRANSPORT")

# Add optional arguments
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

# Add streamable-http-specific options
if [ "$TRANSPORT" = "streamable-http" ]; then
  if [ "$STATELESS" = true ]; then
    ARGS+=("--stateless")
  fi
  
  if [ "$JSON_RESPONSE" = true ]; then
    ARGS+=("--json-response")
  fi
fi

# Print server information
echo "Starting Norman MCP Server"
echo "Transport: $TRANSPORT"
echo "Host: $HOST"
echo "Port: $PORT"
echo "Public URL: $PUBLIC_URL"

if [ "$TRANSPORT" = "streamable-http" ]; then
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