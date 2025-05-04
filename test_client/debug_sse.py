#!/usr/bin/env python3
"""Debug utility for testing SSE connections with OAuth tokens."""

import sys
import requests
import json
import time
import argparse
import sseclient

def test_token(token, base_url="http://localhost:3001"):
    """Test if a token is valid using the debug endpoint."""
    headers = {"Authorization": f"Bearer {token}"}
    
    # Test with our debug endpoint
    debug_url = f"{base_url}/norman/token-debug"
    try:
        response = requests.get(debug_url, headers=headers)
        print(f"Token debug response ({response.status_code}):")
        print(json.dumps(response.json(), indent=2))
        return response.status_code == 200
    except Exception as e:
        print(f"Error testing token: {str(e)}")
        return False

def test_sse_connection(token, base_url="http://localhost:3001"):
    """Test connecting to the SSE endpoint with the token."""
    headers = {"Authorization": f"Bearer {token}"}
    
    # Connect to SSE endpoint
    sse_url = f"{base_url}/sse"
    print(f"Connecting to SSE endpoint at {sse_url}")
    
    try:
        response = requests.get(sse_url, headers=headers, stream=True)
        
        if response.status_code != 200:
            print(f"Failed to connect to SSE: Status {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
        print("SSE connection established!")
        
        # Use SSE client to parse events
        client = sseclient.SSEClient(response)
        
        # Listen for a few events
        print("Waiting for events...")
        event_count = 0
        try:
            for event in client.events():
                event_count += 1
                print(f"Received event {event_count}:")
                print(f"  Event: {event.event}")
                print(f"  Data: {event.data[:100]}..." if len(event.data) > 100 else f"  Data: {event.data}")
                
                if event_count >= 3:
                    break
                    
        except KeyboardInterrupt:
            print("Interrupted!")
        finally:
            response.close()
            
        return True
    except Exception as e:
        print(f"Error in SSE connection: {str(e)}")
        return False

def main():
    """Main entry point for the debug utility."""
    parser = argparse.ArgumentParser(description="Debug utility for testing SSE connections with OAuth tokens")
    parser.add_argument("token", help="OAuth token to test")
    parser.add_argument("--base-url", default="http://localhost:3001", help="Base URL of the MCP server")
    
    args = parser.parse_args()
    
    # First check if the token is valid
    print("Testing token validity...")
    if not test_token(args.token, args.base_url):
        print("Token validation failed! Cannot continue.")
        return 1
    
    print("\nTesting SSE connection...")
    test_sse_connection(args.token, args.base_url)
    
    return 0

if __name__ == "__main__":
    sys.exit(main()) 