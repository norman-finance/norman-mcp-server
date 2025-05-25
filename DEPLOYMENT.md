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


## Environment Variables

The main environment variables that control the MCP server:

- `NORMAN_ENVIRONMENT`: Set to "production" for production deployments
- `NORMAN_API_BASE_URL`: The Norman API base URL
- `MCP_SERVER_HOST`: Server host (0.0.0.0 for Docker)
- `MCP_SERVER_PORT`: Server port (default: 3001)