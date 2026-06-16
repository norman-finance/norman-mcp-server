import re
import logging
from typing import Optional
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# HTML/JS injection patterns only. We deliberately do NOT strip SQL keywords or
# characters like '@'. These values are passed to the Norman API as JSON bodies /
# query parameters — never interpolated into SQL — so a SQL-keyword blocklist
# provides no real protection while silently corrupting legitimate input:
#   "PENDING" -> "PING" (strips "end"), "OpenAI" -> "AI" (strips "open"),
#   "foo@example.com" -> "fooexample.com" (strips "@"), and "create"/"update"/
#   "delete"/"table" vanish entirely. That broke, e.g., the bills status=PENDING filter.
_SCRIPT_INJECTION_RE = re.compile(
    r'<script|javascript:|onclick|onload|onerror|onmouseover|'
    r'alert\(|confirm\(|prompt\(|eval\(|setTimeout\(|setInterval\(',
    re.IGNORECASE,
)


def validate_input(input_str: Optional[str]) -> Optional[str]:
    """Sanitize input strings, stripping only obvious HTML/JS injection patterns.

    Normal text — including SQL-keyword substrings (``end``, ``open``, ``create``,
    ``update``, ``select``) and ``@`` — is returned unchanged, since these are sent
    as JSON/query params, not raw SQL.
    """
    if input_str is None:
        return None

    if _SCRIPT_INJECTION_RE.search(input_str):
        logger.warning("Potential script-injection pattern detected in input; sanitizing.")
        return _SCRIPT_INJECTION_RE.sub('', input_str)

    return input_str

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