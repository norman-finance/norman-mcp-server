# Contributing

Thanks for helping improve Norman's MCP server.

This repository holds the documentation, skills and client manifests of the
hosted server at `https://mcp.norman.finance/mcp`. The server itself is
developed in a private repository and deployed by the Norman team; this
repository is updated with each release.

## Report a bug or suggest a feature

[Open an issue](https://github.com/norman-finance/norman-mcp-server/issues) with:

- what you asked your AI assistant to do,
- what you expected and what happened instead,
- the AI client you used (Claude, ChatGPT, Cursor, Gemini CLI and so on),
- the tool name, if your client shows it.

Never include passwords, tokens, bank details, tax IDs or other personal data.
Report security issues privately as described in [SECURITY.md](SECURITY.md).

## Improve a skill or a guide

Skills live in [`skills/`](skills), one directory per skill with a `SKILL.md`
that has YAML frontmatter. Guides live in [`docs/`](docs).

Pull requests with fixes or new skills are welcome. We review them, port
accepted changes into the main source and publish them with the next release,
so your pull request is closed rather than merged here. Your change and credit
appear in the [changelog](CHANGELOG.md).

A good skill:

- names the Norman tools it uses and the order to call them in,
- asks the user before anything binding: filing, payments, sending emails,
- works for the company's country and does not assume German or Polish rules,
- keeps sensitive identifiers in the Norman app instead of the chat.

## License

By contributing, you agree that your contributions to this repository are
licensed under the [MIT License](LICENSE).
