import re
import logging
from typing import Optional
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def validate_input(input_str: Optional[str]) -> Optional[str]:
    """Validate and sanitize input strings to prevent injection attacks."""
    if input_str is None:
        return None
        
    # Remove any suspicious patterns that might indicate injection attempts
    # This prevents SQL injection, command injection, etc.
    dangerous_patterns = [
        r'--|;|\/\*|\*\/|@@|@|char|nchar|varchar|nvarchar|alter|begin|cast|create|cursor|declare|delete|drop|end|exec|execute|fetch|insert|kill|open|select|sys|sysobjects|syscolumns|table|update',
        r'<script|javascript:|onclick|onload|onerror|onmouseover|alert\(|confirm\(|prompt\(|eval\(|setTimeout\(|setInterval\(',
    ]
    
    sanitized = input_str
    for pattern in dangerous_patterns:
        if re.search(pattern, sanitized, re.IGNORECASE):
            logger.warning(f"Potential injection attack detected in input: {input_str}")
            # Replace potential injection patterns with empty string
            sanitized = re.sub(pattern, '', sanitized, flags=re.IGNORECASE)
    
    return sanitized

def validate_file_path(file_path: str) -> bool:
    """Validate a file path to prevent path traversal attacks."""
    if not file_path:
        return False
    
    # Validate file extension for uploads (only allow safe extensions)
    if any(file_path.lower().endswith(ext) for ext in ['.pdf', '.jpg', '.jpeg', '.png', '.txt', '.csv', '.xlsx']):
        return True
    
    logger.warning(f"Unsupported file extension in: {file_path}")
    return False

def validate_url(url: str) -> bool:
    """Validate URL to prevent SSRF attacks."""
    if not url:
        return False
        
    try:
        parsed = urlparse(url)
        # Only allow http and https schemes
        if parsed.scheme not in ('http', 'https'):
            return False
                
        return True
    except:
        return False 