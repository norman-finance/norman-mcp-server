#!/bin/bash

# Run Norman MCP Server with ngrok for remote access
# Prerequisites:
# - ngrok installed (npm install -g ngrok or download from ngrok.com)
# - Norman MCP server installed and configured

# Create directory for the script if it doesn't exist
mkdir -p $(dirname "$0")

# Function to check if a command exists
command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# Check if ngrok is installed
if ! command_exists ngrok; then
  echo "Error: ngrok is not installed. Please install it with 'npm install -g ngrok' or download from ngrok.com"
  exit 1
fi

# Constants
PORT=3001
HOST="0.0.0.0"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --email=*)
      EMAIL="${1#*=}"
      shift
      ;;
    --password=*)
      PASSWORD="${1#*=}"
      shift
      ;;
    --environment=*)
      ENVIRONMENT="${1#*=}"
      shift
      ;;
    --port=*)
      PORT="${1#*=}"
      shift
      ;;
    --host=*)
      HOST="${1#*=}"
      shift
      ;;
    --debug)
      DEBUG=true
      shift
      ;;
    *)
      # Unknown option
      shift
      ;;
  esac
done

# Start the ngrok tunnel
echo "Starting ngrok tunnel on port $PORT..."
ngrok http $PORT > /dev/null &
NGROK_PID=$!

# Wait for ngrok to start
sleep 2

# Get the public URL from ngrok
NGROK_URL=$(curl -s localhost:4040/api/tunnels | grep -o '"public_url":"[^"]*' | grep -o 'http[^"]*')

if [ -z "$NGROK_URL" ]; then
  echo "Error: Failed to get ngrok URL. Check if ngrok is running correctly."
  kill $NGROK_PID
  exit 1
fi

echo "================================================================"
echo "🚀 Norman MCP Server will be accessible at: $NGROK_URL"
echo "================================================================"
echo "Use this URL when configuring Claude Desktop or MCP Inspector."
echo "----------------------------------------------------------------"

# Build command line arguments
ARGS=()
ARGS+=("--host" "$HOST")
ARGS+=("--port" "$PORT")
ARGS+=("--public-url" "$NGROK_URL")
ARGS+=("--transport" "sse")

# Add optional arguments if provided
if [ ! -z "$EMAIL" ]; then
  ARGS+=("--email" "$EMAIL")
fi

if [ ! -z "$PASSWORD" ]; then
  ARGS+=("--password" "$PASSWORD")
fi

if [ ! -z "$ENVIRONMENT" ]; then
  ARGS+=("--environment" "$ENVIRONMENT")
fi

if [ "$DEBUG" = true ]; then
  ARGS+=("--debug")
fi

# Print command for debugging
echo "Starting Norman MCP server with arguments: ${ARGS[@]}"

# Start the Norman MCP server with CLI arguments
python -m norman_mcp "${ARGS[@]}"

# Clean up ngrok when the server stops
kill $NGROK_PID
echo "Ngrok tunnel closed." 