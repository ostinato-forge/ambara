# Release Checklist

Jurati is published to the internal PyPI. The primary install path is:

```bash
pip install jurati --index-url https://pypi.apps.tools-na100.dev.ole.redhat.com/simple/
```

Alternatively, install from source:

```bash
pipx install git+https://github.com/ostinato-forge/jurati.git
```

For one-off use without a persistent install:

```bash
uvx --from git+https://github.com/ostinato-forge/jurati.git jurati onboard --remote <knowledge-repo-url>
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

7. Verify onboarding creates `.claude/settings.json` and `.mcp.json` in the
   smoke evidence
   directory printed by the script:

   ```bash
   SMOKE_DIR=/tmp/jurati-installed-smoke.example
   cat "$SMOKE_DIR/first-user-trial/example-project/.claude/settings.json"
   cat "$SMOKE_DIR/first-user-trial/example-project/.mcp.json"
   ```

## Signal Providers

Jurati ships with two signal providers:

- **GitHub** (default) — reads labeled PRs via the GitHub API. Configure with
  `JURATI_PR_SIGNAL_REPOS`.
- **Jira** — reads labeled issues via the Jira REST API v2. Configure with
  `JURATI_SIGNAL_PROVIDER=jira`, `JURATI_JIRA_BASE_URL`, `JURATI_JIRA_PROJECTS`,
  and `JIRA_API_TOKEN`. Supports Bearer and Basic auth.

Both providers emit `CoordinationSignal` objects that flow through the same
classification pipeline. Switching providers does not change the coordination
effects surfaced to agents.

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

## Publishing

Jurati is published to the internal PyPI at
`pypi.apps.tools-na100.dev.ole.redhat.com`. Tagging a release triggers the
`.github/workflows/release.yml` workflow which builds, tests on Python 3.12 and
3.13, and publishes via `twine`. The workflow requires `PS_USER` and
`PS_PASSWORD_PROD` secrets configured in the `pypi` GitHub environment.

```bash
git tag -a v1.0.0 -m "Jurati 1.0.0"
git push origin v1.0.0
```
