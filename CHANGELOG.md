# Changelog

All notable changes to Ambara will be documented in this file.

This project uses [Semantic Versioning](https://semver.org/). During the `0.x`
series, the API may change between minor versions.

## [Unreleased]

### Added

- The source-artifact schema is frozen as v1 (ADR 0001): field names, types,
  and vocabulary enums in `ambara.sources.types` are pinned by a guard test,
  and changes now require a superseding ADR in the same change.

### Changed

- Add `hypothesis` as a development dependency and a property-based test suite
  covering core domain invariants (token accounting, content policy, schema id
  validation).
- Coordination and curation now reflect source state truthfully: when a
  configured source successfully reports zero open items, Ambara shows zero
  instead of preserving the last non-empty result. Stale data is still served
  within the source freshness window, and a failed refresh still preserves the
  last successful snapshot (it is never treated as "no risk").

### Removed

- The legacy server-side signal cache and its parallel fetch path. Source
  artifacts from the source kernel are now the single path feeding coordination,
  curation, and context snapshots, so the injectable `fetch_signals` server seam
  is gone. The MCP status and snapshot-coverage payloads no longer emit the
  `legacy_signal_cache_*` or `legacy_signals_considered` fields; the
  `signal_cache_*` fields remain as source-backed aliases of `source_cache_*`.

- The legacy `AMBARA_SIGNAL_PROVIDER`, `AMBARA_PR_SIGNAL_REPOS`, and
  `AMBARA_PR_SIGNAL_FIXTURE` source-selector env vars. Use the `AMBARA_SOURCE_*`
  names; setting a removed variable without its replacement now raises a clear
  error instead of silently defaulting to the github selector.
- The legacy `ambara.signal_providers` entry-point group for third-party signal
  providers. Built-in GitHub, GitLab, Jira, and fixture providers remain; new
  providers target the `ambara.sources.types.SourceProvider` contract.
- The vestigial `ambara.providers.resolve_signal_provider` and
  `RegisteredSignalProvider` signal-provider registry. Provider resolution now
  lives entirely in the source kernel; the built-in GitHub, GitLab, Jira, and
  fixture providers resolve directly and unknown providers fail clearly.

### Fixed

- `safe_artifact_ref` rejects malformed source artifact refs (such as
  unterminated IPv6 literals) instead of raising, hardening the untrusted
  source-render path.

## [0.7.0] — 2026-06-04

### Added

- **Ambient token value rollup** — startup packets include local 7-day token
  savings by default, while currency remains managed-deployment metadata only
- **Signal provider registry** — GitHub and GitLab remain built-in review
  providers, and additional providers can register through the
  `ambara.signal_providers` Python entry-point group
- **Client smoke harness** — `ambara client-smoke` verifies the plain
  file-adapter path for Claude Code, Codex, Cursor, and Gemini against a
  no-network knowledge repo
- **Production-day simulation** — deterministic 100-user / 100-agent proof with
  GitHub, GitLab, and Jira signals feeding the shared context layer

### Changed

- **Release truth tightening** — Python 3.14 is included in CI/release matrices,
  public docs describe the automatic local value ledger, and token scanning
  covers current GitLab and Slack token families
- **CLI structure** — the client-smoke command lives outside the historical
  `cli.py` module so future command-family splits can happen in smaller slices

## [0.6.0] — 2026-06-03

### Added

- **First-class GitLab review backend** — durable writes can open GitLab merge
  requests, hygiene can inspect stale GitLab review artifacts, and branch-only
  fallback generates truthful GitLab review links when review creation is not
  available
- **GitLab review signals** — GitLab merge requests now flow through the same
  coordination model as GitHub pull requests, alongside Jira issue signals
- **GitLab CI capture path** — CI capture is now truthfully documented and
  supported for GitHub Actions, GitLab CI, and direct generic CI entrypoints

### Changed

- **Forge-aware review model** — Ambara now treats review as the product
  concept and adapts receipts, URLs, and orchestration across GitHub and
  GitLab instead of assuming GitHub everywhere
- **Multi-forge release proof** — the local demo fixture and release-proof path
  now verify the no-network GitHub-plus-GitLab story that v0.6.0 claims
- **Support-surface truth** — README, onboarding, troubleshooting, and CLI
  output now distinguish first-class GitHub and GitLab support from branch-only
  compatibility on other git hosts

## [0.5.1] — 2026-06-03

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
[0.5.1]: https://github.com/ostinato-forge/ambara/releases/tag/v0.5.1
[0.6.0]: https://github.com/ostinato-forge/ambara/releases/tag/v0.6.0
[0.7.0]: https://github.com/ostinato-forge/ambara/releases/tag/v0.7.0
