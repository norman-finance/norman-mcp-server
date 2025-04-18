"""Pytest configuration for Norman Finance MCP server tests."""

import os
import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def mock_env_vars():
    """Automatically mock environment variables for all tests."""
    with patch.dict(os.environ, {
        "NORMAN_EMAIL": "test@example.com",
        "NORMAN_PASSWORD": "test-password",
        "NORMAN_ENVIRONMENT": "production",
        "NORMAN_API_TIMEOUT": "200"
    }):
        yield


@pytest.fixture(autouse=True)
def disable_actual_api_calls():
    """Prevent any actual HTTP requests during tests."""
    with patch("requests.request"), patch("requests.post"):
        yield 