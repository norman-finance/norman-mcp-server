import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Configuration for the Norman MCP server."""
    
    @property
    def NORMAN_EMAIL(self):
        return os.getenv("NORMAN_EMAIL", "")
    
    @property
    def NORMAN_PASSWORD(self):
        return os.getenv("NORMAN_PASSWORD", "")
    
    @property
    def NORMAN_ENVIRONMENT(self):
        return os.getenv("NORMAN_ENVIRONMENT", "production")
    
    @property
    def NORMAN_API_TIMEOUT(self):
        return int(os.getenv("NORMAN_API_TIMEOUT", "200"))
    
    @property
    def api_base_url(self) -> str:
        if self.NORMAN_ENVIRONMENT.lower() == "production":
            return "https://api.norman.finance/"
        else:
            return "https://sandbox.norman.finance/"

config = Config() 