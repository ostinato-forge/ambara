# Jurati Build Plan

## Purpose

Jurati's next work is adoption reliability, not feature breadth. A first
external user should be able to install Jurati, connect one project, start a
normal agent task, and feel that the agent came prepared without learning
Jurati internals.

This plan is the execution surface for that work. It replaces loose roadmap
ideas with ordered phases, acceptance criteria, and scope boundaries.

## Product Guardrails

Keep Jurati narrow:

- Shared agent context stays backed by reviewable git source.
- Developers should not need to run Jurati commands during normal work.
- Developer-facing agent responses should talk about the work, not Jurati
  plumbing.
- Durable context writes go through reviewed branches and pull requests.
- Short-lived active context stays opt-in and expires.
- Restricted entries stay out of broad context, search, ranking, static HTML,
  and derived read models.

Do not add these until dogfood evidence proves the need:

- hosted services
- dashboards
- broad activity mining
- chat scraping
- editor telemetry
- read receipts or presence inference
- vector search
- new external signal providers

If a phase grows too large, cut scope to the smallest change that satisfies the
acceptance criteria. Do not widen the product to rescue a phase.

## Phase 1: Agent Discipline

Goal: connected agents reliably load Jurati context before local exploration
and keep implementation details out of developer-facing responses.

Work:

- Strengthen project instructions so `sync()` and `context()` are treated as a
  startup contract, not a suggestion.
- Add a prompt-battery test or scripted connected-agent checklist that catches
  agents reading files, checking git, or planning before Jurati startup context.
- Tighten response guidance for `record()`, `propose()`, and `expire()` so
  confirmations are one short work-focused sentence.
- Add regression coverage that developer-facing confirmations do not expose
  entry IDs, ref paths, branch plumbing, context layers, or knowledge repo
  chores.

Acceptance:

- A clean connected-agent trial shows `sync()` followed by `context()` before
  local repo exploration.
- First-user trial evidence records the exact first agent actions.
- Write confirmations do not expose internal IDs, refs, branch names, or
  review mechanics unless the user explicitly asks for debugging details.
- `python -m pytest -q` and `scripts/pre-release-adversarial-smoke.sh` pass.

## Phase 2: Retrieval Quality Baseline

Goal: measure whether Jurati returns the right context before changing write
flows or capture prompts.

Work:

- Add a small evaluation fixture knowledge repo with decisions, workflows,
  projects, active handoffs, restricted entries, and ambiguous queries.
- Define gold expectations for `context()`, `query()`, and `search()`:
  expected hits, expected exclusions, and cases where asking for clarification
  is better than inventing relevance.
- Add a CLI or test helper that runs the retrieval fixtures in CI.
- Record the current baseline in test output or docs without treating the
  metric as a product promise.

Acceptance:

- Retrieval fixtures run without network access.
- Restricted and expired entries are excluded in every broad retrieval path.
- Baseline results are stable enough to catch regressions.
- Phase 3 changes must not regress the baseline without an explicit plan update.

## Phase 3: Write And Repair Flows

Goal: post-task capture and setup repair become ordinary and low-friction.

Work:

- Improve post-task capture language so a user can say normal things like
  "record that decision" or "save this handoff" without knowing Jurati tool
  names.
- Add deduplication and staleness checks that help agents avoid recording the
  same decision or leaving active handoffs behind.
- Extend `jurati doctor` from diagnosis toward guided repair for project-local
  setup problems.
- Consider a bounded `jurati doctor --fix-project-config` only for safe,
  project-local writes such as `.mcp.json` and `.claude/settings.json`.

Acceptance:

- Capture prompts produce the right write path for active handoffs, durable
  decisions, workflows, and project status updates.
- Doctor repair handles documented first-user setup failures without asking the
  user to understand raw MCP protocol details.
- Retrieval quality fixtures do not regress after capture changes.
- All repair writes are project-local, reviewable, and clearly reported.

## Dogfood Checkpoint

Goal: avoid writing a pilot guide from stale assumptions.

Work:

- Run one single-repo dogfood where the value is decision and workflow recall.
- Run one multi-repo dogfood where the value is coordination across PRs,
  active context, and handoff.
- Record first agent actions, useful context surfaced, missed context, fallback
  behavior, leaked internals, and final confidence.
- Turn failures into Phase 1, 2, or 3 follow-ups before moving to the pilot.

Acceptance:

- Dogfood evidence is captured in repo docs or a durable review artifact.
- No known first-user blocker remains undocumented.
- The build plan is updated if dogfood changes the execution order.

## Phase 4: External Readiness

Goal: a non-contributor can adopt Jurati from the docs and package alone.

Work:

- Publish a first external pilot guide that starts with `pipx install`,
  `jurati onboard`, `jurati doctor --check-startup`, and one normal agent task.
- Keep the pilot guide focused on what the user sees and what the agent should
  do, not on implementation internals.
- Prepare the package release path: version check, changelog/release notes,
  install command, wheel smoke, and release checklist alignment.
- Keep legacy comparison language out of public docs so Jurati stands on its
  own product contract.

Acceptance:

- A fresh walkthrough completes without ad hoc maintainer help.
- The installed-package smoke passes from a clean wheel install.
- Public docs describe one coherent setup path and one product boundary.
- Release notes explain who should try Jurati, what it does, and what remains
  intentionally out of scope.

## Current Next Step

Start with Phase 1. The highest-risk gap is not that Jurati lacks more
features; it is that a connected agent may skip startup context or describe
Jurati mechanics to the person instead of simply doing the work.
