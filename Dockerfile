FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --upgrade pip

# Copy project files
COPY . /app/

# Install the package and additional dependencies
RUN pip install -e . && \
    pip install fastapi uvicorn pydantic

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose server port
EXPOSE 3001

# Run the server
CMD ["python", "-m", "norman_mcp", "--transport", "sse", "--environment", "production"]
