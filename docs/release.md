# Release Checklist

Jurati is published to the public PyPI project under the `tempo-64` account.
The primary install path is:

```bash
pip install jurati
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

1. Bump the version in **both** `pyproject.toml` and `src/jurati/__init__.py`.
2. Review the trust gate:

   ```bash
   $EDITOR docs/security-privacy-content-safety-audit.md
   ```

   The release must not proceed with open P0 findings in the security,
   privacy, or content-safety gate.

3. Run local checks:

   ```bash
   python -m pytest -q
   python -m ruff check .
   python -m mypy src
   ```

4. Run the installed-package smoke:

   ```bash
   scripts/pre-release-installed-package-smoke.sh --keep
   ```

   The script builds a wheelhouse, installs Jurati into a clean virtual
   environment, runs the first-user trial from the installed CLI, and writes an
   evidence file.

5. Run the dogfood harnesses:

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

6. Run the adversarial smoke:

   ```bash
   scripts/pre-release-adversarial-smoke.sh
   scripts/pre-release-active-context-privacy-smoke.sh
   ```

   This runs the high-signal tests named in
   [pre-release-adversarial-hardening.md](pre-release-adversarial-hardening.md)
   plus the focused active-context privacy gate.

7. Update the release-readiness review:

   ```bash
   $EDITOR docs/pre-release-readiness-review.md
   ```

   The review must make a yes/no decision and separate blockers, deferrable
   polish, and post-release roadmap work.

8. Verify onboarding creates `.claude/settings.json` and `.mcp.json` in the
   smoke evidence
   directory printed by the script:

   ```bash
   SMOKE_DIR=/tmp/jurati-installed-smoke.example
   cat "$SMOKE_DIR/first-user-trial/example-project/.claude/settings.json"
   cat "$SMOKE_DIR/first-user-trial/example-project/.mcp.json"
   ```

## Publishing

### How It Works

Jurati uses GitHub Actions for automated publishing. Tagging a release
triggers `.github/workflows/release.yml`, which:

1. Builds the wheel and sdist
2. Runs the full test suite on Python 3.12 and 3.13
3. Publishes to public PyPI at <https://pypi.org/>

### One-Time GitHub Setup

Before the first release, configure the GitHub repository:

1. **Create the `pypi` environment** in the repo settings:

   Settings → Environments → New environment → Name: `pypi`

2. **Configure PyPI Trusted Publishing** for the `jurati` project from the
   `tempo-64` PyPI account:

   - Publisher: GitHub
   - Owner: `ostinato-forge`
   - Repository: `jurati`
   - Workflow: `release.yml`
   - Environment: `pypi`

3. **Optional: Add environment protection rules** to require approval
   before publishing:

   Settings → Environments → `pypi` → Required reviewers

### Cutting a Release

```bash
# Bump version in both locations
$EDITOR pyproject.toml src/jurati/__init__.py

# Branch, commit, PR, merge
git checkout -b release/vX.Y.Z
git add pyproject.toml src/jurati/__init__.py
git commit -m "chore: bump version to X.Y.Z"
git push -u origin release/vX.Y.Z
gh pr create --title "chore: release vX.Y.Z" --base main
gh pr merge --squash --admin

# Tag and push
git checkout main && git pull
git tag -a vX.Y.Z -m "Jurati X.Y.Z"
git push origin vX.Y.Z
```

The tag push triggers the release workflow. Monitor it:

```bash
gh run list --workflow=release.yml --repo ostinato-forge/jurati
gh run watch --repo ostinato-forge/jurati
```

### Manual Publishing

If you need to publish without GitHub Actions (e.g., first-time setup
verification):

```bash
# Install build tools (if not already available)
pip3 install --user build twine

# Build wheel and sdist
rm -rf dist/
python3 -m build

# Upload to PyPI
python3 -m twine upload dist/* \
  --username __token__ \
  --password "$jurati_pypi"
```

The `jurati_pypi` environment variable must contain a PyPI API token from the
`tempo-64` account, scoped to the `jurati` project. On the release machine this
is set in `~/.bashrc`. Verify with `echo $jurati_pypi | head -c 10` — it should
start with `pypi-`.

**GitHub account**: The `ostinato-forge/jurati` repo is accessed via the
`edgarparenti` GitHub account. Switch before pushing or creating PRs:

```bash
gh auth switch --user edgarparenti
```

### Verifying the Published Package

```bash
pip install --index-url https://pypi.org/simple jurati==X.Y.Z
jurati --version
```

## Signal Providers

Jurati ships with two signal providers:

- **GitHub** (default) — reads labeled PRs via the GitHub API. Configure with
  `JURATI_PR_SIGNAL_REPOS`.
- **Jira** — reads labeled issues via the Jira REST API v3. Configure with
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
