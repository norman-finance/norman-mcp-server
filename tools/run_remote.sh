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

# Export the environment variable
export NORMAN_MCP_PUBLIC_URL=$NGROK_URL

# Start the Norman MCP server
echo "Starting Norman MCP server..."
python -m norman_mcp --transport sse --public-url "$NGROK_URL"

# Clean up ngrok when the server stops
kill $NGROK_PID
echo "Ngrok tunnel closed." 