# Release Checklist

Jurati should be installable without cloning the source repo. Until a package is
published to an index, the supported frictionless install path is GitHub over
HTTPS:

```bash
pipx install git+https://github.com/ostinato-forge/jurati.git
```

For one-off use without a persistent install:

```bash
uvx --from git+https://github.com/ostinato-forge/jurati.git jurati quickstart ./jurati-knowledge
```

## Before Release

1. Verify the version in `pyproject.toml`.
2. Run local checks:

   ```bash
   python -m pytest -q
   python -m ruff check .
   python -m mypy src
   ```

3. Run the installed-package smoke:

   ```bash
   scripts/pre-release-installed-package-smoke.sh --keep
   ```

   The script builds a wheelhouse, installs Jurati into a clean virtual
   environment, runs the first-user trial from the installed CLI, and writes an
   evidence file.

4. Run the dogfood harnesses:

   ```bash
   scripts/pre-release-single-repo-dogfood.sh --keep
   scripts/pre-release-multi-repo-dogfood.sh --keep
   ```

   The first harness validates ordinary single-repo startup context. The second
   validates multi-repo coordination with a fixture-backed labeled upstream PR
   signal. Run one connected-agent check from the generated downstream repo and
   record the result in the readiness review. For Claude Code checks, keep the
   normal Claude `HOME`; isolate Jurati with `--mcp-config .mcp.json`,
   `--strict-mcp-config`, and the MCP server env rather than moving Claude's
   auth/config directory to a temporary home.

5. Run the adversarial smoke:

   ```bash
   scripts/pre-release-adversarial-smoke.sh
   ```

   This runs the high-signal tests named in
   [pre-release-adversarial-hardening.md](pre-release-adversarial-hardening.md).

6. Update the release-readiness review:

   ```bash
   $EDITOR docs/pre-release-readiness-review.md
   ```

   The review must make a yes/no decision and separate blockers, deferrable
   polish, and post-release roadmap work.

7. Verify quickstart creates `.claude/settings.json` in the smoke evidence
   directory printed by the script:

   ```bash
   SMOKE_DIR=/tmp/jurati-installed-smoke.example
   cat "$SMOKE_DIR/first-user-trial/jurati-knowledge/.claude/settings.json"
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
doctor, install-claude-md, and serve preflight smoke must still run from the
installed package.
