# Norman MCP OAuth authentication

Norman MCP delegates sign-in to Norman OAuth, then issues MCP access and refresh
handles bound to that authorization. The MCP server never receives the user's
password through its own login form.

## Browser flow

1. The MCP client registers or reuses its saved OAuth client and starts an
   authorization-code request with PKCE S256.
2. MCP creates a unique upstream state for this browser attempt, retaining the
   original client state, registered return URI and PKCE challenge.
3. Norman authenticates the user and returns to the MCP `/oauth/callback`.
4. MCP exchanges the Norman code, persists a short-lived MCP code and returns it
   with the original state to the validated client callback.
5. The client redeems that code with its PKCE verifier and uses the issued MCP
   handles to access Norman.

Pending browser attempts and codes expire after ten minutes. They are saved in
`MCP_OAUTH_STATE_FILE` alongside the existing registered clients and credentials,
so a sequential server restart does not lose a valid reconnect attempt. Expired
transactions and their associated code credentials are removed. This JSON
backend is for one process; it does not coordinate concurrent workers or
start-first deployment overlap.

## Recovery

A terminal upstream HTTP 400 with OAuth `invalid_grant` invalidates only that
connection's access handles, refresh handle and credential aliases. Revocation
has the same effect, including when a refresh is in flight. Other authorizations
and the saved OAuth client registration remain available. The client can start
OAuth again using its existing registration; reinstalling the plugin is not
required by this server flow.

Network failures, rate limits, upstream server errors and invalid-client
configuration errors retain credentials so a temporary failure does not force
reauthorization. Valid callback failures return a normalized OAuth error and the
original state to the registered client. Unknown, expired or replayed attempts
stay on a generic local error page because they have no validated return target.

## Configuration and storage

HTTP transports require `NORMAN_OAUTH_CLIENT_ID`; confidential upstream clients
also use `NORMAN_OAUTH_CLIENT_SECRET`. Configure `NORMAN_MCP_PUBLIC_URL` to the
public MCP origin used by Norman's registered callback. Persist
`MCP_OAUTH_STATE_FILE` on a private volume; replacement files have mode 0600.
Browser-stage logs use a hashed attempt identifier rather than raw state, codes,
tokens or upstream response bodies.
