import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file in project root
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path, override=True)

class Config:
    """Configuration for the Norman MCP server.
    
    Environment Variables:
        NORMAN_EMAIL: Email for stdio transport authentication
        NORMAN_PASSWORD: Password for stdio transport authentication
        NORMAN_ENVIRONMENT: 'production' or 'sandbox' (default: production)
        NORMAN_API_TIMEOUT: API request timeout in seconds (default: 200)
        NORMAN_OAUTH_CLIENT_ID: OAuth client ID for Norman OAuth server (required for HTTP transports)
        NORMAN_OAUTH_CLIENT_SECRET: OAuth client secret (optional, for confidential clients)
        NORMAN_MCP_HOST: Host to bind to (default: 0.0.0.0)
        NORMAN_MCP_PORT: Port to bind to (default: 3001)
        NORMAN_MCP_PUBLIC_URL: Public URL for OAuth callbacks (default: http://localhost:{port})
    """
    
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
    def NORMAN_OAUTH_CLIENT_ID(self):
        """OAuth client ID - required for HTTP transports."""
        return os.getenv("NORMAN_OAUTH_CLIENT_ID")
    
    @property
    def NORMAN_OAUTH_CLIENT_SECRET(self):
        """OAuth client secret - optional for public clients."""
        return os.getenv("NORMAN_OAUTH_CLIENT_SECRET")
    
    @property
    def api_base_url(self) -> str:
        if self.NORMAN_ENVIRONMENT.lower() == "production":
            return "https://api.norman.finance/"
        else:
            return "https://sandbox.norman.finance/"

config = Config() 