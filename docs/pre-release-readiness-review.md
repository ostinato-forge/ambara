# Pre-Release Readiness Review

Tracking issue: https://github.com/ostinato-forge/jurati/issues/43

Review date: 2026-05-12

## Decision

Jurati is not ready for a first external user yet.

The automated evidence is strong enough to move from feature-building into
release-candidate closure, but the release-candidate definition still requires
real connected-agent behavior: the agent must call `sync()` and `context()`
before local repo exploration and summarize coordination without exposing
Jurati internals. That gate remains manual because running an external agent
with normal auth/network access from the current dirty local workspace would
cross the project privacy boundary.

## Automated Gate Evidence

Static gates passed:

- `timeout 180s python -m pytest -q`
  - Result: 573 passed, 1 skipped, 53 warnings.
- `python -m ruff check .`
  - Result: passed.
- `python -m mypy src`
  - Result: passed.
- `git diff --check`
  - Result: passed.
- `bash -n scripts/pre-release-first-user-trial.sh scripts/pre-release-installed-package-smoke.sh scripts/pre-release-single-repo-dogfood.sh scripts/pre-release-multi-repo-dogfood.sh scripts/pre-release-adversarial-smoke.sh`
  - Result: passed.

Installed-package smoke passed after network was allowed for build dependency
resolution:

- Command: `scripts/pre-release-installed-package-smoke.sh --keep`
- Evidence: `/tmp/jurati-installed-smoke.Xyjyh3/evidence.md`
- Result: wheel built, installed into a clean virtual environment, first-user
  trial passed from the installed `jurati` command.

Dogfood harnesses passed:

- Single-repo dogfood:
  - Command: `scripts/pre-release-single-repo-dogfood.sh --keep`
  - Evidence: `/tmp/jurati-single-repo-dogfood.YNnvNU/evidence.md`
  - Result: scripted first-agent sequence called `sync()`, `context()`, and
    `query()` and surfaced the expected release-quality context.
- Multi-repo coordination dogfood:
  - Command: `scripts/pre-release-multi-repo-dogfood.sh --keep`
  - Evidence: `/tmp/jurati-multi-repo-dogfood.azzP4k/evidence.md`
  - Result: goal-only context surfaced the upstream coordination signal, and
    path-specific context returned `pause` guidance for the shared contract.

Adversarial smoke passed:

- Command: `scripts/pre-release-adversarial-smoke.sh`
- Result: 29 passed, 5 warnings.
- Coverage map: [pre-release-adversarial-hardening.md](pre-release-adversarial-hardening.md)

## Blockers

1. Manual single-repo connected-agent gate:
   - Run a fresh connected agent session in the generated single-repo dogfood
     project.
   - Confirm `sync()` and `context()` happen before local repo exploration
     without prompting.
   - Confirm the response summarizes useful context without entry IDs, ref
     paths, branch plumbing, or knowledge repo chores.

2. Manual multi-repo connected-agent gate:
   - Run a fresh connected agent session in the generated downstream dogfood
     repo.
   - Confirm the agent states the upstream PR coordination plainly before
     editing the shared target.
   - Confirm the user is not asked to understand Jurati mechanics.

3. Land and verify this pre-release hardening patch set:
   - The local tree contains the release-plan, dogfood, stdio, adversarial, and
     readiness changes.
   - Before declaring release-candidate status, these changes need to be
     committed, pushed, reviewed, and checked by CI.

## Deferrable Polish

- Build isolation needs network the first time pip resolves `hatchling` and
  wheel dependencies. That is acceptable for release packaging, but future
  offline release work could prebuild a local wheelhouse.
- The manual connected-agent evidence should be summarized back into issue #43
  and this document once run.

## Open Issues

- [#43 Pre-release quality plan](https://github.com/ostinato-forge/jurati/issues/43)
  - Release blocker until the manual connected-agent gates are complete and
    this patch set is landed.
- [#19 Roadmap: make Jurati ambient in daily agent work](https://github.com/ostinato-forge/jurati/issues/19)
  - Roadmap item. Not a first external user blocker.

## Next Action

Create a release-candidate branch or PR for this patch set, then run the two
manual connected-agent gates from a clean disposable branch or outside the Codex
sandbox. If both pass without startup skipping or over-disclosure, Jurati can
move to a first external-user candidate.
