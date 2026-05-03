# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Jurati, please report it responsibly.

**Do not open a public issue.**

Instead, email **edgar@parenti.dev** with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact

You should receive a response within 72 hours. Once confirmed, a fix will be
developed privately and released as a patch before public disclosure.

## Scope

Jurati's security surface includes:

- The MCP server (`jurati serve`)
- The CLI (`jurati` commands)
- The capture pipeline and git hook
- The GitHub Action (`action/`)
- Schema validation and path derivation

The knowledge repository content is user-managed and outside Jurati's security
scope.

## Supported Versions

Only the latest release on `main` receives security fixes.
