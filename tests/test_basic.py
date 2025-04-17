"""Basic tests for the Norman Finance MCP server."""

import norman_mcp
from unittest.mock import patch
from norman_mcp.server import Config, NormanAPI


def test_version():
    """Test that the package has a version defined."""
    assert norman_mcp.__version__ is not None
    assert isinstance(norman_mcp.__version__, str)


def test_config_class():
    """Test the Config class."""
    config = Config()
    assert config.NORMAN_ENVIRONMENT == "production"
    assert config.api_base_url == "https://api.norman.finance/"
    
    # Test sandbox URL
    with patch.dict('os.environ', {'NORMAN_ENVIRONMENT': 'sandbox'}):
        config = Config()
        assert config.NORMAN_ENVIRONMENT == "sandbox"
        assert config.api_base_url == "https://sandbox.norman.finance/"


def test_norman_api_class():
    """Test the NormanAPI class initialization without actual API calls."""
    # With missing credentials
    with patch.dict('os.environ', {'NORMAN_EMAIL': '', 'NORMAN_PASSWORD': ''}):
        api = NormanAPI()
        assert api.access_token is None
        assert api.refresh_token is None
        assert api.company_id is None 