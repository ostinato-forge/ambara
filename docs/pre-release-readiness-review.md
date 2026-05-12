# Pre-Release Readiness Review

Tracking issue: https://github.com/ostinato-forge/jurati/issues/43

Review date: 2026-05-12

## Decision

Jurati is not ready for a first external user yet.

The automated evidence is strong enough to move from feature-building into
release-candidate closure, and the single-repo connected-agent startup gate now
passes from a clean disposable repo. Jurati still needs the multi-repo
connected-agent gate before first external use: a real client must surface
upstream coordination before editing the downstream shared contract.

## Automated Gate Evidence

Static gates passed:

- `timeout 180s python -m pytest -q`
  - Result: 575 passed, 1 skipped, 53 warnings.
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
  - Evidence: `/tmp/jurati-single-repo-dogfood.B0BIZi/evidence.md`
  - Result: scripted first-agent sequence called `sync()`, `context()`, and
    `query()` and surfaced the expected release-quality context.
- Multi-repo coordination dogfood:
  - Command: `scripts/pre-release-multi-repo-dogfood.sh --keep`
  - Evidence: `/tmp/jurati-multi-repo-dogfood.AEnVcT/evidence.md`
  - Result: goal-only context surfaced the upstream coordination signal, and
    path-specific context returned `pause` guidance for the shared contract.

Connected-agent evidence:

- Single-repo gate:
  - Command: `claude -p --mcp-config .mcp.json --strict-mcp-config --setting-sources project ...`
  - Repo: `/tmp/jurati-single-repo-dogfood.B0BIZi/project-repo`
  - MCP server: `jurati-5f128038`
  - Result: passed. The agent called `sync()` and `context()` before file reads
    or git inspection, had no permission denials, and summarized the
    pre-release quality constraint without entry IDs, ref paths, branch
    plumbing, or knowledge repo chores.
  - Follow-through note: after startup context, the agent used local release
    docs before a deeper `query()`. That is not a blocker for this gate but
    should be watched in future instruction tuning.

Adversarial smoke passed:

- Command: `scripts/pre-release-adversarial-smoke.sh`
- Result: 29 passed, 5 warnings.
- Coverage map: [pre-release-adversarial-hardening.md](pre-release-adversarial-hardening.md)

## Blockers

1. Manual multi-repo connected-agent gate:
   - Run a fresh connected agent session in the generated downstream dogfood
     repo.
   - Confirm the agent states the upstream PR coordination plainly before
     editing the shared target.
   - Confirm the user is not asked to understand Jurati mechanics.
   - Use a live labeled upstream PR or add a fixture-backed PR-signal source;
     the scripted harness injects a simulated PR signal that a standalone MCP
     server process cannot yet receive.

2. Land and verify this pre-release hardening patch set:
   - The local tree contains the release-plan, dogfood, stdio, adversarial, and
     readiness changes.
   - Before declaring release-candidate status, these changes need to be
     committed, pushed, reviewed, and checked by CI.

## Deferrable Polish

- Build isolation needs network the first time pip resolves `hatchling` and
  wheel dependencies. That is acceptable for release packaging, but future
  offline release work could prebuild a local wheelhouse.
- Build a fixture-backed PR-signal source for future fully offline
  connected-agent multi-repo validation, or maintain a tiny live test repo with
  a labeled PR.

## Open Issues

- [#43 Pre-release quality plan](https://github.com/ostinato-forge/jurati/issues/43)
  - Release blocker until the multi-repo connected-agent gate is complete and
    this patch set is landed.
- [#19 Roadmap: make Jurati ambient in daily agent work](https://github.com/ostinato-forge/jurati/issues/19)
  - Roadmap item. Not a first external user blocker.

## Next Action

Commit and push the hash-specific permission fix and connected-agent evidence
to the release-candidate PR, then either run the multi-repo gate against a live
labeled PR or add a fixture-backed signal source for `jurati serve`. Once that
gate passes and CI is green, Jurati can move to a first external-user
candidate.
