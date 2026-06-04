# Ambara Release Proof

This is the release-candidate proof path for Ambara. It is local, no-network,
and should pass from both the source checkout and an installed wheel.

## Source Checkout

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
env UV_CACHE_DIR=/tmp/ambara-uv-cache uv lock --check
```

## Built Artifact

```bash
uv build --out-dir /tmp/ambara-dist
python3.12 -m venv /tmp/ambara-install-smoke
/tmp/ambara-install-smoke/bin/python -m pip install \
  /tmp/ambara-dist/ambara-0.5.1-py3-none-any.whl
/tmp/ambara-install-smoke/bin/ambara --version
/tmp/ambara-install-smoke/bin/ambara --help
/tmp/ambara-install-smoke/bin/ambara explain
/tmp/ambara-install-smoke/bin/ambara doctor
```

`ambara serve --check` should fail cleanly when no remote is configured:

```bash
/tmp/ambara-install-smoke/bin/ambara serve --check
```

## Local Product Proof

```bash
/tmp/ambara-install-smoke/bin/ambara demo --path /tmp/ambara-demo --force
PATH="/tmp/ambara-install-smoke/bin:$PATH" /tmp/ambara-demo/run-proof.sh
```

The proof script validates the generated knowledge repo, checks startup,
compiles compact JSON and Markdown context, proves restricted entries stay out
of startup and static HTML, reads one selected body, records active context,
proposes durable context on a review branch, imports docs through a review
branch, queues and flushes ambient capture, runs posture checks, and writes a
local value receipt.

The tag-triggered release workflow repeats the installed-wheel smoke before
publish in the `artifact smoke` job.

## v0.5.1 Trust And Safety Proof

The v0.5.1 follow-up release adds product-trust checks that matter to the human
user, not only source health:

```bash
pytest -q tests/test_server.py tests/capture/test_pipeline.py tests/action/test_capture_action.py
pytest -q tests/test_privacy_coordination.py tests/test_context_token_efficiency.py tests/core/test_context_compiler.py
```

These checks prove:

- branch-only fallback says that no pull request was created
- GitHub Action capture bootstraps the knowledge repo from the declared remote
  and token inputs
- commit capture and action capture apply the content-policy gate, not only
  regex secret scanning
- coordination, curation, and snapshot surfaces share one signal refresh path

If the release notes claim any of those behaviors, the tests above must remain
green from the source checkout before release.

## v0.6.0 Multi-Forge Proof

The v0.6.0 line widens Ambara's first-class review surface from GitHub-only to
GitHub plus GitLab. The proof path should verify that claim locally, without
network access:

```bash
pytest -q tests/test_cli.py tests/action/test_capture_action.py
pytest -q tests/providers/test_fixture_signals.py tests/providers/test_gitlab_mrs.py
pytest -q tests/git/test_auth.py tests/git/test_pr.py
```

These checks prove:

- the local demo fixture includes both GitHub and GitLab review signals
- the generated `run-proof.sh` path verifies that the local demo fixture keeps
  GitLab review evidence wired into the no-network proof flow
- CI capture can derive source context from GitHub Actions or GitLab CI
- fixture-backed and live GitLab review signals flow through the same
  coordination model as GitHub review signals
- GitLab merge request creation, stale-review listing, and branch-only review
  URLs all work through the forge-aware write path

If Ambara claims that GitHub and GitLab are first-class review backends, the
checks above must remain green before release.

## Governance Proof

```bash
scripts/check-dco.sh origin/main..HEAD
uv run pytest tests/test_license_headers.py -q
```

The release also requires the GitHub DCO workflow to pass on the release PR.

## Publish Gate

Do not push `v0.5.1` until PyPI trusted publishing is confirmed for:

- project/name: `ambara`
- owner/repo: `ostinato-forge/ambara`
- workflow: `.github/workflows/release.yml`
- environment: `pypi`

See [PyPI Trusted Publisher Setup](pypi-trusted-publisher.md) for the exact
PyPI values, the difference between ordinary and pending publishers, and the
rerun path if a tagged release fails before publisher setup is complete.

If a tagged release already failed on the publish step, do not retag. Fix the
publisher on PyPI and rerun the release workflow for that tag.

After the tag workflow publishes, repeat the local product proof from a clean
`pip install ambara` environment.
