import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Configuration for the Norman MCP server."""
    NORMAN_EMAIL = os.getenv("NORMAN_EMAIL", "")
    NORMAN_PASSWORD = os.getenv("NORMAN_PASSWORD", "")
    NORMAN_ENVIRONMENT = os.getenv("NORMAN_ENVIRONMENT", "production")
    NORMAN_API_TIMEOUT = int(os.getenv("NORMAN_API_TIMEOUT", "200"))
    
    @property
    def api_base_url(self) -> str:
        if self.NORMAN_ENVIRONMENT.lower() == "production":
            return "https://api.norman.finance/"
        else:
            return "https://sandbox.norman.finance/"

config = Config() 