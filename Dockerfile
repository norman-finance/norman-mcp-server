FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including Poppler for pdf2image
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
RUN pip install --upgrade pip

# Copy project files
COPY . /app/

# Install the package and additional dependencies
RUN pip install -e . && \
    pip install fastapi uvicorn pydantic pdf2image pillow requests

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose server port
EXPOSE 3001

# Run the server with streamable-http transport (OAuth-enabled).
#
# --stateless is REQUIRED for hosted connectors. In stateful mode FastMCP keeps
# each session in memory and demands the exact Mcp-Session-Id be replayed on
# every request after initialize. Hosted clients (claude.ai, ChatGPT) do not
# reliably thread that session id across their conversation runtime, and a
# redeploy/restart wipes the single replica's in-memory sessions. Symptom:
# tools show in the connector settings (cached from the discovery sync) but
# fail to load in conversations with "400 Bad Request: Missing session ID".
# Stateless makes every request self-contained. Do not remove without moving
# session state to a shared store.
CMD ["python", "-m", "norman_mcp", "--transport", "streamable-http", "--stateless", "--environment", "production", "--host", "0.0.0.0", "--port", "3001"]
