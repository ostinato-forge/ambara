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

All three must pass before submitting a PR.

## Submitting Changes

1. Fork the repository and create a feature branch.
2. Write tests for new functionality.
3. Follow existing code patterns — `core/` is pure (no I/O), `git/` is the I/O
   boundary, `server.py` is orchestration glue.
4. Use [Conventional Commits](https://www.conventionalcommits.org/) for commit
   messages: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`.
5. Sign off every commit with `git commit -s`.
6. Open a pull request against `main`.

## Code Style

- Python 3.13+
- Ruff for linting and formatting
- mypy strict mode
- No comments unless the *why* is non-obvious

## License

By contributing, you agree that your contributions will be licensed under
Jurati's Apache License 2.0 and certified through the DCO sign-off above.
