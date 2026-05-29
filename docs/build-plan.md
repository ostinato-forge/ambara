# Jurati Build Plan

## Purpose

Get Jurati into production use. The product surface is built. The remaining
work is proving it works with real teams, fixing what breaks, and closing the
last gaps that prevent confident daily use.

## GitHub Tracking

Main tracker:
[#89](https://github.com/ostinato-forge/jurati/issues/89).

Related docs:

- [Context Compiler Pivot](context-compiler-pivot.md) — architecture rationale
- [Constraint Trust And Correctness Plan](constraint-trust-and-correctness-plan.md)
  — compiler-default authority, correctness, and lifecycle gate
- [Security, Privacy, And Content Safety Gate](security-privacy-content-safety.md) — trust gate
- [Test Gate Runs](dogfood-gate-runs.md) — evidence log

## Product Guardrails

- Shared agent context stays backed by reviewable git source.
- Developers should not need to run Jurati commands during normal work.
- Developer-facing agent responses talk about the work, not Jurati plumbing.
- Durable context writes go through reviewed branches and pull requests.
- Short-lived active context stays opt-in, explicit, and expiring.
- Developers can disable Jurati, mute irrelevant scopes, and retire completed
  project context without hand-editing client config or rewriting git history.
- Do not market Jurati as an immutable, tamper-evident, SOC2-ready audit ledger
  until the audit-ledger gate proves signed commits, append-only evidence,
  protected history, and authenticated identity.
- Restricted entries stay out of broad context, search, ranking, and derived
  read models.
- Team adoption surfaces show repo readiness, not person-by-person presence or
  installation status.
- No read receipts, user presence, editor activity tracking, chat scraping,
  raw query logging, per-person participation dashboards, or hosted services
  that centralize private team content.

## What's Shipped (v1.3.0)

Everything below is merged, tested, and published to PyPI.

| Area | Status | Key PRs |
|------|--------|---------|
| Core MCP tools (context, query, search, read, record, propose, expire) | Complete | — |
| Context compiler with manifest-first token efficiency | Complete | #118, #121, #122 |
| startup-v2 (combined sync+context) | Complete | #120, #122 |
| CLI file adapter (Direction C: core lib + transport adapters) | Complete | #125 |
| Package trust and correctness (Phase 0) | Complete | #82 |
| Server shape cleanup (Phase 0.5) | Complete | #100, #123 |
| Repo-discovered team adoption (Phase 1 first slice) | Complete | #83, #84 |
| Knowledge bootstrap — Markdown, ADR, RFC, Obsidian import (Phase 2) | Complete | #85, #109 |
| Privacy-safe active coordination — repo policy wiring (Phase 3 first slice) | Complete | #86 |
| Auto-curation — lifecycle metadata, advisories, hygiene (Phase 4 first slice) | Complete | #106-#112 |
| Content safety — 4-layer policy engine | Complete | #67, #116 |
| Labeled PR + Jira signal coordination | Complete | #62 |
| Privacy/security hardening (red team review) | Complete | #126 |
| Pre-release quality gates (all 6 workstreams) | Passed | #43 closed |
| Team-loop test gate | Passed | #90 |
| PyPI publishing (tempo-64 account) | Live | v1.3.0 |

Test suite: 1134 tests. Ruff, mypy strict, pre-commit hooks all green.

## Road to Production

### Step 1: Testing — Real Team Loop

**This gate has passed.** The repo now has repeatable scripted evidence,
connected-agent active-refs-disabled evidence, import/curation evidence, and an
active-refs-enabled connected-agent pass.

GitHub issue: [#90](https://github.com/ostinato-forge/jurati/issues/90).

Goal: prove the adoption loop with real client behavior before widening the
product.

Completed work:

- Ran a two-user, two-repo test with a real MCP client on real work.
- First pass used active refs disabled, durable context and PR signals only.
- Captured setup friction, first agent actions, missed context, leaked
  internals, curation usefulness, lifecycle friction, whether imported knowledge
  seeded enough context.
- Included lifecycle escape-hatch work: disable Jurati for a project, mute a
  no-longer-relevant scope, or retire completed project context without making
  the agent expose configuration chores.
- Converted failures into targeted fixes before continuing.
- Completed the active-refs-enabled connected-agent pass after the first pass
  justified it.

Scripted harnesses exist (`scripts/pre-release-single-repo-dogfood.sh`,
`scripts/pre-release-multi-repo-dogfood.sh`, and
`scripts/pre-release-active-context-connected-agent.sh`) and have passed.
Connected-agent gates passed on disposable real-repo clones.

Exit criteria met:

- Evidence shows startup context happens before local exploration.
- A fresh teammate can connect without maintainer-only knowledge.
- Imported or seeded knowledge produces useful context in normal work.
- The user has an obvious escape hatch when Jurati is wrong, stale, or no longer
  relevant to the current project.
- No leaked entry IDs, ref paths, branch plumbing, or knowledge repo chores in
  agent-facing output.

### Step 2: Fix What Testing Finds

Testing will surface issues. Based on the red team review and prior testing,
the likely categories are:

- **Startup friction**: MCP config setup, permission prompts, auth resolution.
- **Context quality**: missing entries, stale context, wrong ranking, token
  waste.
- **Agent instruction tuning**: agents falling back to local-only reasoning,
  not following the startup contract, exposing plumbing.
- **Curation gaps**: entries that should expire or be superseded but aren't.
- **Lifecycle gaps**: no easy disable, mute, or retire path when a project ends
  or a developer changes assignments.
- **Audit/compliance gaps**: signed commits, append-only event evidence,
  protected history verification, and authenticated identity are not in place
  for immutable-ledger or tamper-evident claims.
- **Import gaps**: existing team docs that don't import cleanly.

These fixes should be small, targeted PRs — not new phases.

### Step 3: Remaining Polish

Items that shipped during the final gate sprint:

- [#124](https://github.com/ostinato-forge/jurati/issues/124): Bulk
  clear/reset for team context. This should follow the lifecycle model in
  [Constraint Trust And Correctness Plan](constraint-trust-and-correctness-plan.md):
  local disable/mute first, reviewed retire for shared cleanup, emergency purge
  separate. The first safe slice is a reviewed `jurati clear` branch that bulk
  expires matching current entries with dry-run and filters; destructive purge
  remains out of scope. Shipped in #132.
- [#91](https://github.com/ostinato-forge/jurati/issues/91): Complete
  repo-discovered team adoption — remaining work is keeping social proof at
  the repo level.
- [#100](https://github.com/ostinato-forge/jurati/issues/100): Continue MCP
  server modularity cleanup — closed after the facade stayed within the
  architecture guardrail and behavior stayed covered.

## Future Work (Post-Production)

Gated behind testing evidence. Do not start until the team loop is proven.

| Issue | Area | Gate |
|-------|------|------|
| [#93](https://github.com/ostinato-forge/jurati/issues/93) | Active coordination hardening | Production use justifies ephemeral coordination |
| [#94](https://github.com/ostinato-forge/jurati/issues/94) | Auto-curation depth | Production use reveals what curation is missing |
| [#92](https://github.com/ostinato-forge/jurati/issues/92) | Knowledge bootstrap expansion | Teams need import modes beyond Markdown/Obsidian |
| [#115](https://github.com/ostinato-forge/jurati/issues/115) | Graded knowledge via Sluicebox scoring | Core scoring model needs evidence |
| [#95](https://github.com/ostinato-forge/jurati/issues/95) | Privacy-preserving impact metrics | Privacy design required first |
| [#96](https://github.com/ostinato-forge/jurati/issues/96) | Enterprise content safety + write audit | Larger team demand |
| [#97](https://github.com/ostinato-forge/jurati/issues/97) | Non-engineer read surface | PM/manager demand |
| [#98](https://github.com/ostinato-forge/jurati/issues/98) | Packaging, Docker, fleet install | Scale demand |
| [#99](https://github.com/ostinato-forge/jurati/issues/99) | IDE and agent-client surfaces | IDE integration demand |

## Current Next Step

Move from proving the gate to targeted production-use fixes. Keep future roadmap
work behind evidence from actual use, and put active-coordination depth under
#93 rather than reopening #90.
