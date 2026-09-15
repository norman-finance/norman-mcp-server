# ChatGPT resubmission: shared MCP endpoint restored

Updated 2026-09-15 after the owner requested removal of the separate ChatGPT URL.

## Current decision

All connectors use the original `https://mcp.norman.finance/mcp` endpoint with the
same full tool inventory. The separate `/chatgpt/mcp` route, filtered server,
profile-specific skill overrides, and 131-tool submission artifact/generators are
withdrawn. Their previous versions remain recoverable from Git history.

No OAuth issuer, token handling, client registration, DCR or redirect rules change.
No hidden client-based filtering replaces the removed endpoint.

## Retained fixes

- Explicit/corrected annotations for contract, invoice, quote, preview, download
  and public name-search tools.
- Correct preview-image MIME metadata.
- Correct widget pagination/date query parameters and an explicit empty Ledger state.

Registration and payment-capable tools remain on the common endpoint, as before.
The public general-purpose `skills/` package is unchanged.

## Submission remains paused

The earlier 131-tool JSON and ChatGPT-only skills do not describe the shared endpoint
and must not be reused for submission. Rescan `/mcp` in the OpenAI draft, restore the
original general-purpose skills, and review the full exposed tool inventory.

OpenAI's rejection concerns about personal identifier solicitation and payment
initiation are **not resolved by reverting the endpoint**. A separate decision is
needed on changing the common tool behavior or clarifying acceptance with OpenAI.
Do not claim the no-payment-initiation attestation while `pay_bill` remains exposed.

The dedicated review account's VAT preview also remains blocked by missing business
tax setup (HTTP 400 wrapping an upstream 422). Do not invent a business tax number
or alter new-admission status to force a pass. No binding filing or payment was made.

Actual ChatGPT web/mobile tests, demo recording review, compliance attestations and
resubmission remain outstanding. The removal patch must be deployed and verified:
`/mcp` should retain its OAuth challenge and `/chatgpt/mcp` should return 404.
