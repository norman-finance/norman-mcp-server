FROM python:3.11-slim

WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PYTHONPATH=/app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy all files needed for installation first
COPY pyproject.toml README.md LICENSE ./

# Copy the code
COPY norman_mcp ./norman_mcp

# First try to install in development mode
RUN pip install -e . || \
    # If that fails, install dependencies manually and ensure scripts are available
    (pip install requests>=2.25.0 python-dotenv>=0.19.0 pyyaml>=6.0 mcp>=0.3.0 "mcp[cli]>=1.3.0" && \
     pip install -e .)

# Ensure norman-mcp command is available as fallback
RUN ln -sf /app/norman_mcp/cli.py /usr/local/bin/norman-mcp && \
    chmod +x /usr/local/bin/norman-mcp

# Ensure proper permissions
RUN chmod -R 755 /app

# Run the application via Python module as a more reliable approach
CMD ["python", "-m", "norman_mcp"]
