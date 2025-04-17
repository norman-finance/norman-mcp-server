FROM python:3.11-slim

WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on

# Install dependencies
COPY pyproject.toml README.md LICENSE ./

# Install the package
RUN pip install --no-cache-dir .

# Copy the actual code
COPY norman_mcp ./norman_mcp

# Run the application
CMD ["norman-mcp"] 