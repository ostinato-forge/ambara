# Pre-Release Readiness Review

Tracking issue: https://github.com/ostinato-forge/jurati/issues/43

Review date: 2026-05-12

## Decision

Jurati is ready to move to a first external-user candidate after this
pre-release hardening patch set lands and CI is green.

The automated evidence is strong enough to move from feature-building into
release-candidate closure, and the single-repo connected-agent startup gate now
passes from a clean disposable repo. The multi-repo connected-agent gate also
passes: a real client surfaced upstream coordination before editing the
downstream shared contract, without making the user understand Jurati mechanics.

## Automated Gate Evidence

Static gates passed:

- `timeout 180s python -m pytest -q`
  - Result: 583 passed, 1 skipped, 53 warnings.
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
  - Evidence: `/tmp/jurati-multi-repo-dogfood.RT7pRv/evidence.md`
  - PR signal fixture:
    `/tmp/jurati-multi-repo-dogfood.RT7pRv/pr-signals.json`
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
- Multi-repo coordination gate:
  - Command: `claude -p --mcp-config .mcp.json --strict-mcp-config --setting-sources project ...`
  - Repo: `/tmp/jurati-multi-repo-dogfood.RT7pRv/web-app`
  - MCP server: `jurati-159fba87`
  - Session: `f60347ff-8457-46e3-ac25-0008b52e5f53`
  - Result: passed. The agent called `sync()`, `context()`, and then
    `query()` before local repo exploration, had no permission denials, and
    stated that the upstream auth API PR changes `refreshWindowSeconds` from
    300 to 900 and adds `rotationPolicy: server-driven`.

Adversarial smoke passed:

- Command: `scripts/pre-release-adversarial-smoke.sh`
- Result: 29 passed, 5 warnings.
- Coverage map: [pre-release-adversarial-hardening.md](pre-release-adversarial-hardening.md)

## Blockers

1. Land and verify this pre-release hardening patch set:
   - The local tree contains the release-plan, dogfood, stdio, adversarial, and
     readiness changes.
   - Before declaring release-candidate status, these changes need to be
     committed, pushed, reviewed, and checked by CI.

## Deferrable Polish

- Build isolation needs network the first time pip resolves `hatchling` and
  wheel dependencies. That is acceptable for release packaging, but future
  offline release work could prebuild a local wheelhouse.
- Keep the fixture-backed multi-repo gate small and obvious. If it grows into a
  broad scenario suite, move the cases into explicit fixtures instead of making
  the shell harness opaque.

## Open Issues

- [#43 Pre-release quality plan](https://github.com/ostinato-forge/jurati/issues/43)
  - Release blocker until this patch set lands and CI is green.
- [#19 Roadmap: make Jurati ambient in daily agent work](https://github.com/ostinato-forge/jurati/issues/19)
  - Roadmap item. Not a first external user blocker.

## Next Action

Commit and push the fixture-backed PR-signal source and connected-agent
evidence to the release-candidate PR. Once CI is green on that PR, Jurati can
move to a first external-user candidate.
