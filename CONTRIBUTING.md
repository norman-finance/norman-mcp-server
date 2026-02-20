# Contributing to Norman MCP Server

Thanks for your interest in contributing! Here's how to get started.

## Getting Started

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended) or pip

### Setup

```bash
git clone https://github.com/norman-finance/norman-mcp-server.git
cd norman-mcp-server
pip install -e ".[dev]"
```

### Environment

Copy the example env and fill in your credentials:

```bash
cp .env.example .env
```

```
NORMAN_EMAIL=your-email@example.com
NORMAN_PASSWORD=your-password
NORMAN_ENVIRONMENT=sandbox
NORMAN_MCP_HOST=0.0.0.0
NORMAN_MCP_PORT=3001
```

Use `sandbox` for development to avoid touching production data.

### Running locally

```bash
# Streamable HTTP (recommended)
python -m norman_mcp --transport streamable-http

# SSE
python -m norman_mcp --transport sse

# stdio (for Claude Desktop)
python -m norman_mcp
```

## Project Structure


```
norman-mcp-server/
├── norman_mcp/
│   ├── server.py              # MCP server setup, middleware, patches
│   ├── cli.py                 # CLI entry point
│   ├── context.py             # Request context and token management
│   ├── config/
│   │   └── settings.py        # Configuration and environment variables
│   ├── auth/
│   │   └── provider.py        # OAuth provider (delegates to Norman API)
│   └── tools/
│       ├── clients.py          # Client CRUD operations
│       ├── invoices.py         # Invoice management and e-invoicing
│       ├── transactions.py     # Transaction search, categorization
│       ├── taxes.py            # Tax reports, VAT filing, Finanzamt
│       ├── documents.py        # Attachment upload and linking
│       └── company.py          # Company details and balance
├── skills/                     # Claude Code / OpenClaw skills
├── .claude-plugin/             # Plugin manifest and marketplace
└── pyproject.toml
```

## Adding a New Tool

1. Find the appropriate file in `norman_mcp/tools/` or create a new one
2. Add your tool function with the `@mcp.tool()` decorator
3. Include `title` and `annotations` (ToolAnnotations) for proper metadata
4. If you created a new file, register it in `server.py`

Example:

```python
from mcp.types import ToolAnnotations

@mcp.tool(
    title="My New Tool",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def my_new_tool(ctx: Context, param: str) -> Dict[str, Any]:
    """Description of what this tool does."""
    api_client = await get_api_client(ctx)
    response = api_client.get("/api/v1/endpoint/")
    return response.json()
```

## Adding a New Skill

1. Create a directory under `skills/` with your skill name
2. Add a `SKILL.md` file with YAML frontmatter
3. Include OpenClaw-compatible metadata for cross-platform support
4. Update the skills table in `README.md`

## Code Style

This project uses:

- **black** for formatting (line length 100)
- **isort** for import sorting (black profile)
- **mypy** for type checking

```bash
black norman_mcp/
isort norman_mcp/
mypy norman_mcp/
```

## Pull Requests

1. Fork the repository
2. Create a feature branch from `main`
3. Make your changes
4. Run formatting and type checks
5. Submit a pull request with a clear description of what changed and why

## Reporting Issues

Found a bug or have a feature idea? [Open an issue](https://github.com/norman-finance/norman-mcp-server/issues) with:

- What you expected to happen
- What actually happened
- Steps to reproduce (if applicable)
- Your environment (Python version, OS, MCP client)

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
