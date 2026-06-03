# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Ambara, please report it responsibly.

**Do not open a public issue.**

Use GitHub's private vulnerability reporting for this repository. Include:

- A description of the vulnerability
- Steps to reproduce
- Potential impact

If private vulnerability reporting is unavailable, open a public issue asking
for a private security contact, but do not include vulnerability details in the
issue.

You should receive a response within 72 hours. Once confirmed, a fix will be
developed privately and released as a patch before public disclosure.

## Scope

Ambara's security surface includes:

- The MCP server (`ambara serve`)
- The CLI (`ambara` commands, including `install-claude-md`)
- The capture pipeline and git hook
- The GitHub Action (`action/`)
- Schema validation and path derivation (`core/validate.py`, `core/paths.py`)
- The integration contract and access mode filtering (`core/contract.py`)
- Identity salting at integration boundaries (`core/privacy.py`)
- Signal provider protocol and implementations (`providers/`)

The knowledge repository content is user-managed and outside Ambara's security
scope.

### Privacy boundary

Ambara enforces a privacy boundary at the API layer:

- No query logging, read receipts, or participation tracking
- Restricted entries (`sensitivity: restricted`) are excluded from search,
  context, and the BM25 index — accessible only via explicit `read(id=...)`
- Cross-system identity salting via `opaque_identity()` prevents correlation
  of author identities across different requesting systems
- Session handoffs are enabled by default (`AMBARA_ACTIVE_REFS_ENABLED=true`)
- Value receipts and the optional local value ledger store aggregate token
  estimates and omission/suppression counts only. They do not store query text,
  response text, body snippets, caller identity, or durable per-entry read
  receipts.
- Local relevance feedback is stored in project-local config or process memory,
  not in the shared context repo by default.

Note: the privacy boundary operates at the API layer, not the storage layer.
Raw git history and markdown files in the knowledge repo still expose
identities to anyone with repo access.

## Supported Versions

Only the latest release on `main` receives security fixes.
