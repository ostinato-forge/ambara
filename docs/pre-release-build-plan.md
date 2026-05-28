# Pre-Release Build Plan

Tracking issue: https://github.com/ostinato-forge/jurati/issues/43 (closed)

## Status: Complete

All 6 workstreams passed. Jurati v1.3.0 is published to PyPI. The readiness
review in [pre-release-readiness-review.md](pre-release-readiness-review.md)
approved the move to first external-user candidate.

| Workstream | Status | Evidence |
|------------|--------|----------|
| 1. Reproducible first-user trial | Passed | Scripted, disposable repos |
| 2. Installed-package smoke | Passed | Clean venv from wheel |
| 3. Single-repo integration test | Passed | Harness + connected-agent gate |
| 4. Multi-repo coordination test | Passed | Fixture-backed PR signal gate |
| 5. Adversarial hardening | Passed | 29 scenarios, scripted smoke |
| 6. Release-readiness review | Approved | Decision documented |

## What Happened After

- v1.2.0 published to PyPI (2026-05-28)
- Direction C architecture validated: core lib + transport adapters (PR #125)
- Red team review: 4-agent audit, privacy/security/architecture hardening (PR #126)
- v1.3.0 published to PyPI (2026-05-28)
- Test suite: 583 → 1098 tests

## Next

The pre-release plan is complete. The active plan is now
[build-plan.md](build-plan.md), which focuses on production testing.
