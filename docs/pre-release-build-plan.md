# Pre-Release Build Plan

Tracking issue: https://github.com/ostinato-forge/jurati/issues/43

## Objective

Move Jurati from a substantial pre-release implementation to a release-candidate
system that has been proven through repeatable setup checks, dogfood runs, and
adversarial workflow tests.

The quality plan defines the bar. This build plan defines the work order.

## Current State

Jurati already has the core product surface:

- MCP context, query, search, read, validate, record, propose, and expire tools.
- Reviewable git source for durable context.
- Active refs for short-lived handoffs.
- Labeled PR coordination signals.
- Ambient capture from `jurati:` commit messages.
- Context pack import, graph validation, static HTML, and a derived SQLite read
  model.
- Quickstart, MCP config, Claude instruction install, doctor checks, and serve
  preflight.

The remaining work is confidence work. The project needs repeatable evidence
that these capabilities behave coherently when a new user, an agent client,
local git state, MCP config, and real work all meet.

## Workstream 1: Reproducible First-User Trial

Status: implemented locally.

Goal: anyone working on Jurati can run the same disposable setup and see the
same pre-agent baseline before starting a manual agent trial.

Build:

- Add a runnable local trial script that creates a disposable knowledge repo,
  pushes it to a local bare remote, creates a disposable project repo, installs
  Jurati client instructions, writes collision-resistant MCP config, and runs
  startup checks.
- Emit an evidence file with the paths, command results, and manual prompts to
  use with a connected agent.
- Keep the existing blog draft parked; do not fold it into this workstream.

Acceptance:

- The script runs from the source checkout without network access.
- The generated project has `CLAUDE.md`, `.claude/settings.json`, and `.mcp.json`.
- `jurati doctor --check-startup`, `jurati serve --check`, and
  `jurati validate` pass against the disposable repos.
- The evidence file tells the tester what to ask the agent and what behavior to
  observe.

## Workstream 2: Installed-Package Smoke

Status: implemented locally.

Goal: prove the supported install path works without relying on source-checkout
paths.

Build:

- Add a scripted smoke that builds a wheel into a temporary directory.
- Install that wheel into a clean virtual environment.
- Run the same quickstart, install-claude-md, MCP config, doctor, validate, and
  serve checks from the installed `jurati` command.
- Record command evidence in a local artifact that can be attached to issue
  #43 or summarized in a follow-up comment.

Acceptance:

- The installed-package smoke passes from a clean environment.
- The release checklist commands match the scripted smoke.
- Any source-checkout assumptions become bugs or patches.

## Workstream 3: Single-Repo Dogfood

Status: scripted harness passed; manual connected-agent startup gate passed
from a clean disposable repo.

Goal: verify ordinary work, where the value is decision and workflow recall.

Build:

- Pick one active repo and one knowledge repo.
- Install Jurati with the normal user path.
- Run the repeatable single-repo dogfood harness to validate setup, startup
  checks, and the real MCP handler sequence.
- Start a real task and record the first agent actions.
- Capture what context surfaced, what context was missed, and whether the agent
  fell back to local-only reasoning too early.

Acceptance:

- Evidence shows whether Jurati improved the initial planning step.
- Any skipped startup context, leaked internals, or prompt burden becomes a
  focused issue.

## Workstream 4: Multi-Repo Coordination Dogfood

Status: implemented locally; scripted coordination harness passed, manual
connected-agent run pending because the harness injects a simulated PR signal
that a standalone `jurati serve` process cannot yet receive.

Goal: prove the strongest product claim: an agent avoids a plausible
coordination mistake because Jurati supplied cross-repo context first.

Build:

- Use two related repos with a real or simulated dependency.
- Add a labeled PR signal in the upstream repo.
- Start or continue dependent work in the downstream repo.
- Capture whether Jurati context surfaced before local-only reasoning.
- For a real connected-agent gate, use either a live labeled upstream PR or add
  a fixture-backed PR-signal source for `jurati serve`.

Acceptance:

- The downstream agent sees the upstream coordination signal before acting.
- The agent gives useful guidance without making the person manage knowledge
  repo mechanics.
- Any missing PR detail, unavailable path behavior, or fallback to GitHub is
  classified as either acceptable belt-and-suspenders behavior or a bug.

## Workstream 5: Adversarial Hardening

Status: implemented locally; adversarial matrix and smoke passed.

Goal: convert known failure modes into tests, scripted smokes, or documented
manual checks.

Build:

- Cover duplicate MCP config, missing remote, unavailable GitHub auth, stale
  active context, restricted backlinks, bad context pack layout, context pack
  secret rejection, missing PR changed paths, unlabeled relevant PRs, and agent
  over-disclosure.
- Prefer automated tests where the behavior lives in deterministic code.
- Use scripted smoke or manual evidence only when the behavior depends on a
  real MCP client or agent.

Acceptance:

- Every adversarial scenario in the quality plan has a validation owner:
  automated test, scripted smoke, or documented manual run.
- New failures become issue-backed build slices.

## Workstream 6: Release-Readiness Review

Status: documented locally; decision is not ready until the multi-repo
connected-agent gate passes and this patch set lands.

Goal: make a grounded yes/no decision about first external use.

Build:

- Run static gates.
- Run installed-package smoke.
- Summarize first-user trial evidence.
- Summarize single-repo and multi-repo dogfood evidence.
- Review open issues against the release-candidate definition.

Acceptance:

- The project has a documented release-readiness decision.
- Blockers, deferrable polish, and post-release roadmap items are separated.

## Immediate Build Slice

Continue with Workstream 6 while the Workstream 4 connected-agent gate remains
manual.

Tasks:

1. Run static gates, installed-package smoke, dogfood harnesses, and
   adversarial smoke from a clean release-candidate branch.
2. Record the passed single-repo connected-agent gate and use a live or
   fixture-backed PR signal for the remaining multi-repo connected-agent gate.
3. Review the open issue list against the release-candidate definition.
4. Write the release-readiness decision with blockers, deferrable polish, and
   post-release roadmap items separated.

## Notes

The build order intentionally avoids new product features until the first-user
and dogfood evidence says they are necessary. Jurati's pre-release risk is now
workflow reliability, not feature inventory.
