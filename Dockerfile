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
    pip install fastapi uvicorn pydantic pdf2image pillow

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose server port
EXPOSE 3001

# Run the server
CMD ["python", "-m", "norman_mcp", "--transport", "sse", "--environment", "production"]
