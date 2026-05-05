# Contributing to Jurati

Thanks for your interest in contributing. Jurati is a personal open source
project and contributions are welcome.

## Developer Certificate of Origin

All contributions must include a `Signed-off-by` line in each commit message.
This certifies that you have the right to submit the contribution under
Jurati's Apache 2.0 license. Jurati uses the
[Developer Certificate of Origin](https://developercertificate.org/) instead of
a Contributor License Agreement.

Use `git commit -s` to add the sign-off automatically:

```text
fix: reject expired active entries

Signed-off-by: Your Name <your.email@example.com>
```

Commits without a valid sign-off will need to be amended before they can be
accepted.

## Development Setup

```bash
git clone https://github.com/ostinato-forge/jurati.git
cd jurati
python3.13 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest                  # full suite
ruff check src/ tests/  # lint
mypy src/jurati/        # type checking
```

All three must pass before submitting a PR. Pre-commit hooks enforce ruff and
mypy automatically.

## Architecture

Jurati enforces a strict pure/IO split:

```
src/jurati/
  core/       ← pure, deterministic, zero I/O imports
  git/        ← I/O boundary: clone, fetch, branch, commit, PR
  providers/  ← I/O boundary: signal provider protocol + implementations
  server.py   ← MCP tool handlers (orchestration glue)
  cli.py      ← CLI commands
```

**The rule:** `core/` must never import from `git/` or `providers/` or perform
any I/O. `test_architecture.py` walks the AST to enforce this at CI. Current
time, repo snapshots, and config enter `core/` as explicit function parameters.

### Key modules

| Layer | Module | Purpose |
|-------|--------|---------|
| core | `schema.py` | Pydantic models: Entry, Frontmatter, Visibility, Sensitivity |
| core | `changes.py` | WriteIntent/ExpireIntent planning (pure) |
| core | `events.py` | EventType/EventRecord for L1+ lifecycle events |
| core | `contract.py` | Integration contract: AccessMode, query_knowledge, check_constraints |
| core | `privacy.py` | opaque_identity salted hashing |
| core | `scoring.py` | BM25 search ranking |
| core | `validate.py` | Entry validation rules |
| git | `repo.py` | Repo cloning, fetching, index loading |
| git | `commit.py` | Materializing write/expire intents into git commits |
| git | `config.py` | JuratiConfig from environment variables |
| providers | `protocol.py` | SignalProvider runtime-checkable Protocol |
| providers | `github_prs.py` | GitHub PR signal provider |

## Submitting Changes

1. Fork the repository and create a feature branch.
2. Write tests for new functionality. Tests mirror `src/` structure under
   `tests/`.
3. Follow existing code patterns — `core/` is pure (no I/O), `git/` and
   `providers/` are the I/O boundary, `server.py` is orchestration glue.
4. Use [Conventional Commits](https://www.conventionalcommits.org/) for commit
   messages: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`.
5. Sign off every commit with `git commit -s`.
6. Open a pull request against `main`.

## Code Style

- Python 3.13+
- Ruff for linting and formatting
- mypy strict mode
- No comments unless the *why* is non-obvious

## Adding a Signal Provider

To add a new coordination signal source (e.g., Jira, Linear):

1. Create `src/jurati/providers/your_provider.py`
2. Implement the `SignalProvider` protocol from `providers/protocol.py`
3. Map your domain objects to `CoordinationSignal` (defined in
   `core/pr_signals.py`)
4. Add tests in `tests/providers/`

The provider protocol requires `fetch_signals()` (I/O) and `needs_refresh()`.
The pure classification logic in `core/pr_signals.py` handles ranking and
effect classification for all providers.

## License

By contributing, you agree that your contributions will be licensed under
Jurati's Apache License 2.0 and certified through the DCO sign-off above.
