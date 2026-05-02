# Jurati

Shared team intelligence layer for agentic workflows. Git-backed knowledge repo + MCP server.

**Spec:** `docs/superpowers/specs/2026-05-02-jurati-design.md` is the authoritative design document.

## Architecture

- `core/` — pure, deterministic, zero I/O. Schema, index, search, validation, path derivation, write-intent planning.
- `git/` — I/O boundary. Clone, fetch, branch, commit, PR operations.
- `server.py` — MCP tool handlers. Orchestration glue between core/ and git/.
- `cli.py` — `jurati serve`, `jurati init`, `jurati validate`.

**Never cross the streams.** core/ must never import from git/ or perform I/O. Current time, repo snapshots, and config enter core as explicit inputs.

## Code vs Knowledge Repo

`jurati` (this repo) is the software. `jurati-knowledge` is the team-owned content repository. Never confuse the two in docs, config, or code.

## Escalation Model

Protected `main` is the default. No MCP tool pushes directly to main.

- L0 (active): non-main active overlay refs (`jurati/active/<client>/<entry-id>`)
- L1 (project): short-lived branch + lightweight PR
- L2 (workflow, decision): branch + PR, human review
- L3 (principle): branch + PR, human review

`record()` handles L0/L1. `propose()` handles L2/L3. Higher-stakes tools cannot create lower-stakes content and vice versa.

## Privacy

The server must not persist or report: query text, read patterns, participation metrics, absence signals, or agent activity outside explicit tool calls. Git provenance (commits, PRs, authorship) exists for accountability — it must not be repurposed as participation tracking inside jurati.

## Dev

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Conventions

- Python 3.13+
- Conventional Commits: `feat:`, `fix:`, `refactor:`, etc.
- Ruff for linting, mypy strict mode
- Tests mirror src/ structure under tests/
- Entry IDs: `^[a-z0-9][a-z0-9-]{2,120}$`
- Timestamps: UTC ISO-8601 ending in `Z`
