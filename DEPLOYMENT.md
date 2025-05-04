# Norman MCP Server Deployment Guide

This document outlines how the Norman MCP Server is deployed using Docker, GitHub Actions, and Ansible.

## Deployment Architecture

The Norman MCP Server is deployed with the following components:

- **Docker**: Container runtime
- **Traefik**: Reverse proxy and SSL termination
- **GitHub Actions**: CI/CD pipeline
- **Ansible**: Configuration management

## Deployment Process

The deployment process is fully automated:

1. Code is pushed to GitHub (master or develop branch)
2. GitHub Actions workflow builds a Docker image
3. Docker image is pushed to GitHub Container Registry (ghcr.io)
4. For production deployments, Ansible is used to:
   - Pull the latest Docker image
   - Update the Docker Compose configuration
   - Deploy the service with Traefik integration

## Manual Deployment

If you need to deploy manually, you can use the Ansible playbook directly:

```bash
# Clone the devops repository
git clone https://github.com/norman-finance/norman-devops.git
cd norman-devops

# Add the vault password file
echo "your-vault-password" > .vault-key

# Run the playbook
ansible-playbook -i hosts site.yml --tags mcp-server
```

## Environment Variables

The main environment variables that control the MCP server:

- `NORMAN_ENVIRONMENT`: Set to "production" for production deployments
- `NORMAN_TRANSPORT`: Set to "sse" for Server-Sent Events transport
- `NORMAN_API_BASE_URL`: The Norman API base URL
- `MCP_SERVER_HOST`: Server host (0.0.0.0 for Docker)
- `MCP_SERVER_PORT`: Server port (default: 3001)

## OAuth Configuration

For OAuth authentication, you need to configure:

- `NORMAN_OAUTH_CLIENT_ID`: OAuth client ID
- `NORMAN_OAUTH_CLIENT_SECRET`: OAuth client secret
- `NORMAN_OAUTH_REDIRECT_URI`: OAuth redirect URI

These values are stored securely in the Ansible vault.

## Monitoring

The MCP server exposes a `/health` endpoint that can be used to monitor the service's health. Traefik is configured to use this endpoint for health checks. 