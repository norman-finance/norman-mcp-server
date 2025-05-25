#!/usr/bin/env python3
"""Get an OAuth token from the Norman MCP server for testing."""

import sys
import requests
import json
import base64
import hashlib
import secrets
import urllib.parse
import webbrowser
import http.server
import socketserver
import threading
import time

# Server configuration
SERVER_HOST = "localhost"
SERVER_PORT = 8989
CALLBACK_HOST = f"http://{SERVER_HOST}:{SERVER_PORT}"
CALLBACK_PATH = "/callback"
CALLBACK_URL = f"{CALLBACK_HOST}{CALLBACK_PATH}"

# MCP Server configuration
MCP_HOST = "localhost"
MCP_PORT = 3001
MCP_URL = f"http://{MCP_HOST}:{MCP_PORT}"

# Global variables to store token information
access_token = None
refresh_token = None
token_event = threading.Event()

def generate_code_verifier():
    """Generate a code verifier for PKCE."""
    code_verifier = secrets.token_urlsafe(43)  # Generate at least 43 bytes of random data
    return code_verifier

def generate_code_challenge(code_verifier):
    """Generate a code challenge from code verifier using S256 method."""
    code_verifier_bytes = code_verifier.encode('ascii')
    hash_object = hashlib.sha256(code_verifier_bytes)
    code_challenge_bytes = hash_object.digest()
    code_challenge = base64.urlsafe_b64encode(code_challenge_bytes).decode('ascii').rstrip('=')
    return code_challenge

def register_client():
    """Register a test client with the server."""
    client_id = f"test_client_{secrets.token_hex(4)}"
    register_url = f"{MCP_URL}/norman/register-client?client_id={client_id}&redirect_uri={urllib.parse.quote(CALLBACK_URL)}"
    
    print(f"Registering client with ID: {client_id}")
    response = requests.get(register_url)
    
    if response.status_code != 200:
        print(f"Failed to register client: {response.text}")
        sys.exit(1)
        
    client_data = response.json()
    print(f"Client registered successfully:")
    print(f"  Client ID: {client_data['client_id']}")
    print(f"  Client Secret: {client_data['client_secret']}")
    print(f"  Redirect URI: {client_data['redirect_uri']}")
    
    return client_data

class TokenHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler to receive OAuth callback."""
    
    def do_GET(self):
        """Handle GET request - this will be the OAuth callback."""
        global access_token, refresh_token
        
        if not self.path.startswith(CALLBACK_PATH):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return
            
        print(f"Received callback: {self.path}")
        
        # Extract the code parameter
        query_params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = query_params.get('code', [''])[0]
        
        if not code:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No code parameter in callback")
            return
            
        print(f"Received authorization code: {code}")
        
        # Exchange code for token
        client_id = self.server.client_data["client_id"]
        client_secret = self.server.client_data["client_secret"]
        code_verifier = self.server.code_verifier
        
        token_url = f"{MCP_URL}/token"
        token_data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret, 
            "code": code,
            "redirect_uri": CALLBACK_URL,
            "code_verifier": code_verifier
        }
        
        try:
            response = requests.post(token_url, data=token_data)
            
            if response.status_code != 200:
                error_html = f"""
                <html><body>
                <h1>Error getting token</h1>
                <p>Status code: {response.status_code}</p>
                <p>Response: {response.text}</p>
                </body></html>
                """.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.send_header('Content-Length', len(error_html))
                self.end_headers()
                self.wfile.write(error_html)
                return
                
            token_response = response.json()
            access_token = token_response.get("access_token")
            refresh_token = token_response.get("refresh_token")
            
            print(f"Received access token: {access_token}")
            if refresh_token:
                print(f"Received refresh token: {refresh_token}")
                
            # Notify the main thread that we have the token
            token_event.set()
            
            # Return success page
            success_html = f"""
            <html><body>
            <h1>Authentication Successful!</h1>
            <p>You can now close this window and return to the terminal.</p>
            <h2>Token Information:</h2>
            <pre>{json.dumps(token_response, indent=2)}</pre>
            </body></html>
            """.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(success_html))
            self.end_headers()
            self.wfile.write(success_html)
            
        except Exception as e:
            print(f"Error exchanging code for token: {str(e)}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Error: {str(e)}".encode('utf-8'))
    
    def log_message(self, format, *args):
        """Override to disable logging."""
        return

def start_callback_server(client_data, code_verifier):
    """Start the callback server to receive the OAuth redirect."""
    handler = TokenHandler
    
    with socketserver.TCPServer((SERVER_HOST, SERVER_PORT), handler) as httpd:
        print(f"Callback server started at {CALLBACK_URL}")
        
        # Add client data and code verifier to the server instance
        httpd.client_data = client_data
        httpd.code_verifier = code_verifier
        
        # Run the server until we get the token
        while not token_event.is_set():
            httpd.handle_request()

def main():
    """Main entry point."""
    # Register a client
    client_data = register_client()
    
    # Generate PKCE code verifier and challenge
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    
    print(f"Code verifier: {code_verifier}")
    print(f"Code challenge: {code_challenge}")
    
    # Start the callback server in a separate thread
    server_thread = threading.Thread(
        target=start_callback_server,
        args=(client_data, code_verifier)
    )
    server_thread.daemon = True
    server_thread.start()
    
    # Build the authorization URL
    client_id = client_data["client_id"]
    authorize_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": CALLBACK_URL,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = f"{MCP_URL}/authorize?{urllib.parse.urlencode(authorize_params)}"
    
    print(f"Opening browser to authorize URL: {authorize_url}")
    webbrowser.open(authorize_url)
    
    # Wait for the token to be received
    print("Waiting for authorization...")
    token_event.wait(timeout=300)  # 5 minutes timeout
    
    if not access_token:
        print("Failed to get access token within the timeout period.")
        return 1
        
    print("\nAccesss token for use in debugging:")
    print(f"{access_token}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main()) 