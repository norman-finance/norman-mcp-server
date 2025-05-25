# Norman MCP OAuth Authentication

This directory contains the implementation of OAuth 2.0 authentication for the Norman MCP server. 
This allows users to authenticate with their Norman Finance credentials through a web interface
instead of providing them as environment variables.

## How it works

The authentication flow works as follows:

1. When a client connects to the MCP server, they'll be redirected to the OAuth authorization
   endpoint.
2. The server will present a login form where the user enters their Norman Finance email and password.
3. The server sends these credentials to the Norman API to get an access token.
4. If successful, the server creates an OAuth session and redirects the user back to the client
   with an authorization code.
5. The client exchanges this code for an access token and refresh token.
6. The server maps these tokens to the actual Norman API tokens.
7. All subsequent API calls use the Norman API token we got from login page.

## Implementation Details

The implementation consists of several components:

- `provider.py`: Contains the `NormanOAuthProvider` class which implements the `OAuthAuthorizationServerProvider` 
  protocol from the MCP library. This provider handles token generation, validation, and management.
  
- `routes.py`: Defines the routes for the login page and form handlers.

- `templates/login.html`: A simple login form with fields for email and password.

## Configuration

The OAuth implementation is configured in the main server file. It uses the following settings:

- Server URL: `http://{host}:{port}`
- Scopes: `norman.read` and `norman.write`

## Usage

When a user connects to the MCP server through a compatible client (like MCP Inspector), they'll be
directed to the login page if they haven't authenticated yet. After entering their Norman Finance
credentials, they'll be redirected back to the client and can start using the API.

No additional configuration is needed on the client side, as this follows standard OAuth 2.0 flows.

## Security Considerations

- Credentials are never stored in the server. They are used only to obtain tokens from the Norman API.
- The server maintains a mapping between MCP tokens and Norman API tokens.
- All communication should be over HTTPS in production.
- If you configure default credentials via environment variables, these will be used for initial server operation
  but users will still need to log in through the web interface to get their own tokens. 