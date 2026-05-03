# Release Checklist

Jurati should be installable without cloning the source repo. Until a package is
published to an index, the supported frictionless install path is GitHub over
SSH:

```bash
pipx install git+ssh://git@github.com/RedHatTraining/jurati.git
```

For one-off use without a persistent install:

```bash
uvx --from git+ssh://git@github.com/RedHatTraining/jurati.git jurati quickstart ./jurati-knowledge
```

## Before Release

1. Verify the version in `pyproject.toml`.
2. Run local checks:

   ```bash
   python -m pytest -q
   python -m ruff check .
   python -m mypy src
   ```

3. Build a wheel:

   ```bash
   python -m pip wheel . --wheel-dir dist
   ```

4. Install the wheel into a clean environment:

   ```bash
   python -m venv /tmp/jurati-release-smoke
   /tmp/jurati-release-smoke/bin/python -m pip install --no-index --find-links dist jurati
   ```

5. Smoke the installed CLI:

   ```bash
   /tmp/jurati-release-smoke/bin/jurati --help
   /tmp/jurati-release-smoke/bin/jurati quickstart /tmp/jurati-knowledge --remote https://example.com/jurati-knowledge.git
   JURATI_KNOWLEDGE_REMOTE=https://example.com/jurati-knowledge.git /tmp/jurati-release-smoke/bin/jurati doctor
   JURATI_KNOWLEDGE_REMOTE=https://example.com/jurati-knowledge.git /tmp/jurati-release-smoke/bin/jurati serve --check
   ```

## CI Contract

The GitHub Actions workflow runs:

- `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy src`
- wheel build and installed-CLI smoke

The local MCP smoke can also be run directly without network access:

```bash
python -m pytest tests/test_mcp_smoke.py -q
```

Once the workflow is green on `main`, make the `test` check required in branch
protection.

## Publishing Later

If Jurati is published to PyPI or an internal package index, update the README
install command and keep this checklist as the release gate. The quickstart,
doctor, and serve preflight smoke must still run from the installed package.
