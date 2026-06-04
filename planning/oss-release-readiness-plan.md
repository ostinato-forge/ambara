# OSS Release Readiness Plan (v0.7.0)

Status legend: ✅ done · 🟡 in progress · ⬜ remaining · 💡 recommendation

Branch: `chore/oss-release-readiness` (working tree only; nothing committed
yet). Target: Ambara v0.7.0, an honest cross-agent release that can be tested
locally like a normal work day with 100 users, 100 agents, GitHub, GitLab, and
Jira.

Product constraint from this review: Ambara must remain invisible by default.
Users should not configure Ambara or pricing. They state intent and tag work in
PRs, merge requests, issues, and Jira; Ambara captures and surfaces useful
ambient context around that flow.

---

## 1. Release Goals

1. Make the README/support matrix literally true, with runnable proof for every
   first-class claim.
2. Keep value visible without dishonest money defaults: token savings are
   automatic; currency appears only when a managed deployment supplies its own
   token price.
3. Prove cross-agent behavior with simulated agents, not copy: Codex, Claude
   Code, Cursor, and Gemini must all exercise the supported path.
4. Preserve the v0.6 multi-forge foundation while adding an extension seam for
   third-party signal providers.
5. Ship v0.7.0 only after source tests, lint, type checks, wheel build,
   installed-wheel smoke, and PyPI publish verification pass.

---

## 2. Completed Work ✅

### 2.1 Release hygiene and security fixes ✅

- Consolidated duplicate PR templates into `.github/PULL_REQUEST_TEMPLATE.md`.
- Added Python 3.14 to CI/release matrices and package classifiers.
- Fixed the brittle tempdir expectation in `tests/curation/test_run_hygiene.py`.
- Expanded secret scanning for GitLab token prefixes and Slack token families.
- Scrubbed CI capture auth tokens from cached `.git/config` after fetch.
- Completed the README CLI-reference truth pass and install/value docs updates.

### 2.2 Ambient value rollup ✅

- Startup packets now include a compact `value_rollup` sourced from the local
  aggregate value ledger.
- `AMBARA_VALUE_LEDGER_ENABLED` defaults to true so value capture just works.
- The ledger records aggregate token estimates and omission/suppression counts
  only; it does not record query text, response text, entry bodies, caller
  identity, or per-entry read receipts.
- Currency estimates are deliberately opt-in for managed environments via
  `AMBARA_INPUT_PRICE_PER_MILLION` and `AMBARA_PRICE_CURRENCY`.
- Invalid, negative, and non-finite prices are rejected instead of guessed.
- README and troubleshooting docs now state that Ambara never invents a
  universal dollar value.

### 2.3 Signal provider registry ✅

- Added `src/ambara/providers/registry.py` with built-in GitHub/GitLab
  providers and entry-point discovery via `ambara.signal_providers`.
- Unknown provider IDs now fail clearly instead of silently falling back.
- `providers/signals.py` resolves providers through the registry.
- Added registry tests for built-ins, fake entry points, callable providers,
  and unknown-provider behavior.
- Added `docs/signal-providers.md` for extension authors.

### 2.4 Client smoke harness ✅

- Added `ambara client-smoke --client <claude-code|codex|cursor|gemini>`.
- The command writes project config/client setup as appropriate, compiles
  startup context through the file-adapter path, reads it back, and emits a
  JSON or human-readable smoke result.
- JSON mode suppresses helper chatter so the output stays machine-readable.
- Tests exercise all four named client surfaces against a local no-network
  knowledge repo.
- The new command is extracted into `src/ambara/cli_client_smoke.py` and
  registered onto the main Click group to avoid growing `cli.py` further.

### 2.5 Production-day cross-agent simulation ✅

- Added `tests/test_prod_day_simulation.py`.
- The simulation covers 100 users, 100 agent sessions, 10 services, and four
  client surfaces: Codex, Claude Code, Cursor, and Gemini.
- Fixture signals include GitHub, GitLab, and Jira artifacts feeding the same
  startup coordination model.
- Assertions prove shared-context selection, client coverage in the aggregate
  value ledger, compact startup markdown, pause guidance, and restricted-body
  non-leakage.

### 2.6 0.7 docs and versioning ✅

- Bumped package version to `0.7.0`.
- Added `docs/release-v0.7.0.md`.
- Updated `docs/release-proof.md` with a v0.7 cross-agent proof section,
  installed-wheel client-smoke loop, and v0.7 publish gate.
- Updated PyPI trusted-publisher rerun/install examples to v0.7.0.
- Updated README positioning/support matrix around ambient token value,
  provider extensions, and client smoke.

---

## 3. In Progress 🟡

### 3.1 Verification sweep 🟡

The focused cross-agent/provider/client proof passed before the docs guard was
updated, with one expected failure: the public-doc allowlist did not include the
new 0.7 docs. That guard has now been updated.

Next verification:

```bash
pytest -q tests/test_architecture_language.py tests/core/test_architecture.py \
  tests/test_prod_day_simulation.py \
  tests/test_cli.py::TestAdoptionHelpers::test_client_smoke_writes_file_adapter_context \
  tests/providers/test_fixture_signals.py tests/providers/test_registry.py \
  tests/test_ambara_providers.py
ruff check .
mypy src
pytest -q
git diff HEAD --check
```

### 3.2 Artifact and publish proof 🟡

After source verification:

```bash
uv build --out-dir /tmp/ambara-dist
python3.12 -m venv /tmp/ambara-install-smoke
/tmp/ambara-install-smoke/bin/python -m pip install \
  /tmp/ambara-dist/ambara-0.7.0-py3-none-any.whl
/tmp/ambara-install-smoke/bin/ambara --version
/tmp/ambara-install-smoke/bin/ambara demo --path /tmp/ambara-demo --force
PATH="/tmp/ambara-install-smoke/bin:$PATH" /tmp/ambara-demo/run-proof.sh
for client in claude-code codex cursor gemini; do
  /tmp/ambara-install-smoke/bin/ambara client-smoke \
    --client "$client" \
    --remote /tmp/ambara-demo/knowledge \
    --project-path "/tmp/ambara-client-smoke-$client" \
    --json
done
```

Publishing is not complete until PyPI shows `ambara==0.7.0` installable from a
clean environment.

---

## 4. Remaining Work ⬜

### 4.1 Full `cli.py` split ⬜

The release now extracts the new client-smoke command and adds a guard that
keeps it out of `cli.py`, but the historical CLI is still large. A full split
into command-family modules remains worthwhile, but it is high-risk release
surgery and should not be claimed as complete for v0.7.0.

Recommended post-0.7 shape:

- `cli_setup.py`: onboard, quickstart, init, demo, install helpers, doctor.
- `cli_context.py`: startup, save, record, propose, active, show, search,
  query, read.
- `cli_lifecycle.py`: import, validate, clear, retire/mute/unmute, capture,
  flush, enable/disable.
- `cli_value.py`: value, feedback, html, read-model, explain, privacy-salt.
- `cli.py`: root group, `serve`, registration only, and compatibility exports
  if tests or users rely on private helper seams.

### 4.2 README positioning copy review ⬜

README copy has been updated enough to keep claims honest, but positioning copy
should still get owner review before merge. The most important guardrail is to
avoid deck-style universal dollar claims in public docs unless a measured,
scenario-specific source is cited and clearly scoped.

### 4.3 PyPI trusted publishing ⬜

Before tagging/publishing:

- Confirm `gh` identity and repository access for `ostinato-forge/ambara`.
- Confirm the PyPI trusted publisher values in
  `docs/pypi-trusted-publisher.md`.
- Run the release proof from both source checkout and installed wheel.
- Publish v0.7.0 only through the verified release path.
- Verify `pip install ambara==0.7.0` from a clean environment after publish.

---

## 5. Recommendations 💡

- Keep "cross-agent" claims tied to tests. If a new client is named, add it to
  `client-smoke` and the production-day simulation first.
- Keep money out of the default product. Tokens are universal enough to report;
  dollars are deployment-specific and should only appear when supplied by a
  managed environment.
- Keep plugin providers behind the same sanitization/coordination path as
  built-ins. Extension should not become a privacy bypass.
- Treat the full CLI split as a post-release refactor with behavior-free
  commits and full-suite checks after each extraction.
- Audit user-facing dates, numbers, and currency formatting before broad
  international positioning.

---

## 6. Files Touched

Key changed files so far:

```text
.github/PULL_REQUEST_TEMPLATE.md
.github/workflows/ci.yml
.github/workflows/release.yml
README.md
docs/install-troubleshooting.md
docs/pypi-trusted-publisher.md
docs/release-proof.md
docs/release-v0.6.0.md
docs/release-v0.7.0.md
docs/signal-providers.md
planning/oss-release-readiness-plan.md
pyproject.toml
src/ambara/__init__.py
src/ambara/action/capture.py
src/ambara/cli.py
src/ambara/cli_client_smoke.py
src/ambara/cli_render.py
src/ambara/core/context_accounting.py
src/ambara/core/secret_patterns.py
src/ambara/git/config.py
src/ambara/providers/__init__.py
src/ambara/providers/registry.py
src/ambara/providers/signals.py
tests/action/test_capture_action.py
tests/core/test_architecture.py
tests/core/test_context_accounting.py
tests/core/test_secrets.py
tests/git/test_config.py
tests/providers/test_fixture_signals.py
tests/providers/test_registry.py
tests/test_architecture_language.py
tests/test_cli.py
tests/test_prod_day_simulation.py
tests/test_startup_v2_rendering.py
```

---

## 7. Suggested Commit Sequence

Use DCO-signed conventional commits:

1. `fix(tests): derive run hygiene temp path from gettempdir`
2. `chore(ci): test Python 3.14 and consolidate PR template`
3. `docs(readme): complete CLI and support-surface truth pass`
4. `feat(security): detect GitLab and Slack tokens`
5. `fix(security): scrub capture token from cached git config`
6. `feat(value): surface ambient token savings rollup`
7. `feat(providers): add signal provider entry-point registry`
8. `feat(clients): add cross-client file-adapter smoke harness`
9. `test(release): simulate 100-user cross-agent workday`
10. `chore(release): prepare Ambara 0.7.0 proof and docs`
