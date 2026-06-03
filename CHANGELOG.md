# Changelog

All notable changes to Ambara will be documented in this file.

This project uses [Semantic Versioning](https://semver.org/). During the `0.x`
series, the API may change between minor versions.

## [0.5.1] — Unreleased

### Changed

- **Honest branch-only receipts** — write and cleanup responses now say when a
  review branch was created without opening a pull request
- **GitHub Action bootstrap** — action capture now prepares the knowledge repo
  from the configured remote/token inputs before processing commits
- **Capture content-policy parity** — commit capture now evaluates the content
  policy gate in addition to secret scanning
- **Shared signal refresh path** — coordination, curation, and snapshot flows
  now use one cache/health refresh helper

## [0.5.0] — 2026-06-03

First public open source release.

### Added

- **MCP server** with 14 tools: `startup`, `context`, `sync`, `read`,
  `read_many`, `query`, `search`, `list_entries`, `hygiene`, `record`,
  `propose`, `expire`, `explain`, `status`, `validate`
- **CLI** with `serve`, `onboard`, `demo`, `doctor`, `startup`, `validate`,
  `import-docs`, `import-context`, `install-hook`, `install-claude-md`,
  `posture-check`, `read-model`, `explain`, `value`, `feedback`, and `html`
- **Local demo proof** — `ambara demo` creates a no-network knowledge repo,
  wired project repo, fixture signal, value ledger path, static HTML proof path,
  and a runnable `run-proof.sh` that verifies startup, selective read, explicit
  active record, proposal branch, import branch, ambient capture, posture,
  value, and restricted-entry filtering
- **File adapter** — `ambara startup` writes `.ambara/context.md` so any agent
  client can read project context without MCP, using project config as a remote
  fallback after onboarding
- **Pure core / IO split** — all policy, schema, indexing, and ranking logic is
  deterministic with zero I/O, enforced by AST guard in CI
- **Content safety gate** — blocks credentials and secrets, flags PII for
  review, warns on risky phrasing, before any write reaches git
- **Privacy boundary** — no query logging, no read receipts, no participation
  tracking, no presence inference. Restricted entries excluded from search and
  context
- **Governance model** — 5 entry types (decision, workflow, project, active,
  principle) with 4 escalation levels (L0–L3), expiration, and visibility
  controls
- **Coordination signals** — reads labeled PRs (GitHub) and issues (Jira) from
  configured sources, classifies effects (continue, reuse, revise, pause,
  handoff, clarify)
- **BM25 search** with recency decay, type weighting, repo affinity, and
  restricted-entry exclusion
- **Guided onboarding** — `ambara onboard` creates knowledge repo, writes
  CLAUDE.md startup contract, configures MCP, sets tool permissions
- **Client setup** — generated Claude Code instructions and MCP config, plus a
  plain file adapter for agents that can read a local context file
- **Curation system** — lifecycle advisories for stale entries, reviewable
  curation branches
- **Context packs** — starter templates for `generic`, `engineering`, and
  `training` setups
- **Schema v2** with visibility, sensitivity, and recorded-by fields; backward
  compatible with v1 entries
- **Open source governance** — Apache 2.0 license, DCO 1.1 contribution
  certification, repo-wide SPDX headers, local DCO hook, and PR sign-off check

[0.5.0]: https://github.com/ostinato-forge/ambara/releases/tag/v0.5.0
