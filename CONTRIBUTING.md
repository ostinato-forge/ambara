# Contributing to Jurati

Thanks for your interest in contributing. Jurati is a personal open source
project and contributions are welcome.

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

All three must pass before submitting a PR.

## Submitting Changes

1. Fork the repository and create a feature branch.
2. Write tests for new functionality.
3. Follow existing code patterns — `core/` is pure (no I/O), `git/` is the I/O
   boundary, `server.py` is orchestration glue.
4. Use [Conventional Commits](https://www.conventionalcommits.org/) for commit
   messages: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`.
5. Open a pull request against `main`.

## Code Style

- Python 3.13+
- Ruff for linting and formatting
- mypy strict mode
- No comments unless the *why* is non-obvious

## License

By contributing, you agree that your contributions will be licensed under the
Apache License 2.0.
