# Changelog

All notable changes to Jurati will be documented in this file.

This project uses [Semantic Versioning](https://semver.org/). During the `0.x`
series, the API may change between minor versions.

## [0.5.0] — 2026-06-XX

First public open source release.

### Added

- **MCP server** with 14 tools: `startup`, `context`, `sync`, `read`,
  `read_many`, `query`, `search`, `list_entries`, `hygiene`, `record`,
  `propose`, `expire`, `explain`, `status`, `validate`
- **CLI** with `serve`, `onboard`, `doctor`, `validate`, `import-docs`,
  `import-context`, `install-hook`, `install-claude-md`, `explain`, `html`
- **File adapter** — `jurati startup` writes `.jurati/context.md` so any agent
  client can read project context without MCP
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
- **Guided onboarding** — `jurati onboard` creates knowledge repo, writes
  CLAUDE.md startup contract, configures MCP, sets tool permissions
- **Cross-client support** — tested with Claude Code and Gemini CLI; works with
  any client that can read a file
- **Curation system** — lifecycle advisories for stale entries, reviewable
  curation branches
- **Context packs** — importable starter templates (`engineering`, `training`,
  `minimal`)
- **Schema v2** with visibility, sensitivity, and recorded-by fields; backward
  compatible with v1 entries

[0.5.0]: https://github.com/ostinato-forge/jurati/releases/tag/v0.5.0
