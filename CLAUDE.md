# Jurati

Shared team intelligence layer for agentic workflows. Git-backed knowledge repo + MCP server.

## Architecture

- `core/` — pure, deterministic, zero I/O. All logic lives here.
- `git/` — I/O boundary. Clone, commit, branch, PR operations.
- `server.py` — MCP tool handlers. Thin glue between core/ and git/.
- `cli.py` — `jurati serve`, `jurati init`.

**Never cross the streams.** core/ must never import from git/ or perform I/O.

## Escalation Model

- L0/L1 (active, project): direct commit to main
- L2/L3 (workflow, decision, principle): branch + PR, requires human review

## Privacy

Jurati is structurally incapable of surveillance. No telemetry, no participation tracking, no absence signals, no query logging. This is architecture, not policy.

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
