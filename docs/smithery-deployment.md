# Smithery.ai Deployment Guide

This document provides detailed instructions for deploying the Norman Finance MCP server on [Smithery.ai](https://smithery.ai).

## Overview

Smithery Deployments enable hosting of Model Context Protocol (MCP) servers over WebSocket connections, eliminating the need for local installation while maintaining security. The Norman Finance MCP server is configured to work with Smithery.ai out of the box.

## Prerequisites

Before deploying to Smithery.ai, you need:

1. A GitHub account
2. A Smithery.ai account linked to your GitHub account
3. A Norman Finance account (for production or sandbox environment)

## Deployment Files

The repository contains two essential files required for Smithery deployment:

### 1. Dockerfile

The Dockerfile defines how the server is built and packaged. Our Dockerfile:
- Uses Python 3.11 on a slim base
- Installs the necessary dependencies
- Sets up the proper environment for running the server
- Configures the entrypoint to the `norman-mcp` command

### 2. smithery.yaml

The `smithery.yaml` file configures how the server starts up in the Smithery environment:

```yaml
startCommand:
  type: stdio
  configSchema:
    type: object
    required:
      - normanEmail
      - normanPassword
    properties:
      normanEmail:
        type: string
        description: "Norman Finance account email"
      normanPassword:
        type: string
        description: "Norman Finance account password"
      normanEnvironment:
        type: string
        enum: ["production", "sandbox"]
        default: "production"
        description: "API environment (production or sandbox)"
      normanApiTimeout:
        type: integer
        default: 30
        description: "API request timeout in seconds"
  commandFunction: |
    (config) => ({
      command: 'norman-mcp',
      args: [],
      env: {
        NORMAN_EMAIL: config.normanEmail,
        NORMAN_PASSWORD: config.normanPassword,
        NORMAN_ENVIRONMENT: config.normanEnvironment || 'production',
        NORMAN_API_TIMEOUT: config.normanApiTimeout ? String(config.normanApiTimeout) : '30'
      }
    })
```

## Manual Deployment Steps

To deploy the server manually:

1. Fork or clone this repository to your own GitHub account
2. Log in to [Smithery.ai](https://smithery.ai) with your GitHub account
3. Add your repository to Smithery.ai
4. Navigate to the Deployments tab
5. Configure the deployment with your Norman Finance credentials:
   - `normanEmail`: Your Norman Finance account email
   - `normanPassword`: Your Norman Finance account password
   - Optional: Set `normanEnvironment` to "sandbox" for testing
   - Optional: Adjust `normanApiTimeout` as needed
6. Click "Deploy"

## Automated Deployment with GitHub Actions

The repository includes a GitHub Actions workflow file (`.github/workflows/smithery-deploy.yml`) that automates deployment to Smithery.ai whenever changes are pushed to the main branch.

To set up automated deployment:

1. Create a Smithery API token:
   - Log in to Smithery.ai
   - Navigate to your account settings
   - Generate a new API token

2. Add the token to your GitHub repository secrets:
   - Go to your GitHub repository
   - Navigate to Settings > Secrets and variables > Actions
   - Add a new repository secret named `SMITHERY_TOKEN` with your API token

The workflow will now automatically deploy to Smithery.ai whenever changes are pushed to the main branch. You can also manually trigger the workflow from the GitHub Actions tab.

## Using Your Deployed Server

After successful deployment, you can:

1. Access your deployed server from the Smithery.ai dashboard
2. Test it using the built-in MCP playground
3. Configure it to work with Claude or other MCP-compatible LLMs using the WebSocket URL provided by Smithery.ai

### Configuration with Claude

To use your Smithery-deployed MCP server with Claude:

```json
{
  "mcpServers": {
    "norman": {
      "url": "wss://your-smithery-url.smithery.ai/ws",
      "config": {
        "normanEmail": "your-email@example.com",
        "normanPassword": "your-password",
        "normanEnvironment": "production"
      }
    }
  }
}
```

## Troubleshooting

If you encounter issues with your deployment:

1. Check the deployment logs in the Smithery.ai dashboard
2. Verify your Norman Finance credentials are correct
3. Ensure the repository has the latest version of the Dockerfile and smithery.yaml
4. Check the GitHub Actions workflow logs for automated deployment issues

For further assistance, contact [support@smithery.ai](mailto:support@smithery.ai) or open an issue on the GitHub repository. 