# Jurati Build Plan

## Purpose

Jurati's next work is not just first-user setup. It is turning a useful
single-user install into a durable team habit without weakening the privacy
boundary that makes the product worth trusting.

The plan addresses two classes of feedback:

- correctness and maintainability gaps that can undermine confidence in the
  package
- strategic adoption gaps that can make Jurati feel like a smarter ADR repo
  instead of ambient team coordination

## GitHub Tracking

The canonical GitHub tracker is
[#89](https://github.com/ostinato-forge/jurati/issues/89). Keep that issue as
the open checklist and this document as the repo-owned narrative for ordering,
scope, and guardrails.

## Product Guardrails

Keep the product narrow where the privacy boundary matters:

- Shared agent context stays backed by reviewable git source.
- Developers should not need to run Jurati commands during normal work.
- Developer-facing agent responses should talk about the work, not Jurati
  plumbing.
- Durable context writes go through reviewed branches and pull requests.
- Short-lived active context stays opt-in, explicit, and expiring.
- Restricted entries stay out of broad context, search, ranking, static HTML,
  and derived read models.
- Team adoption surfaces must show repo readiness, not person-by-person
  presence, installation status, or readership.
- Metrics must measure system outcomes, not who read what, who queried what, or
  who was active.

Do not add these without an explicit privacy design and dogfood evidence:

- read receipts
- user presence
- editor activity tracking
- chat scraping
- raw query logging
- per-person participation dashboards
- hosted services that require centralizing private team content

## Execution Order

### Phase 0: Package Trust And Correctness

Status: implemented in the current working branch.

Goal: remove small but trust-eroding defects before asking teams to adopt
Jurati more broadly.

Work:

- Align `src/jurati/__init__.py` with the package version in `pyproject.toml`.
- Remove the duplicate module logger in `server.py`.
- Replace manual frontmatter rendering in `core/changes.py` with a real YAML
  or frontmatter serializer.
- Complete the `jurati capture` command or make it fail loudly until it is
  wired to the pending queue and capture pipeline.
- Resolve the active-ref default mismatch between package configuration and
  starter repo configuration. Starter repos must not enable L0 active context
  unless the team explicitly opts in.
- Fix BM25 cache invalidation around every in-memory index mutation, not only
  `sync()`.
- Wire `opaque_identity()` to an actual salt source or demote it from an
  operational privacy guarantee.
- Decide whether starter repo entries should remain schema v1 fixtures or move
  to schema v2, and document the config-schema versus entry-schema distinction.
- Replace hardcoded starter timestamps with initialization-time timestamps.

Acceptance:

- `jurati --version` matches the package metadata.
- Entries with quotes, colons, multiline strings, nested `source`, and
  `recorded_by` round-trip through generated frontmatter.
- `jurati capture` writes a local pending marker from the post-commit hook; an
  explicit flush or action step creates review branches. If that path remains
  deferred, public docs stop presenting ambient capture as usable.
- Generated starter configuration and runtime defaults agree on the active-ref
  privacy posture.
- Search/context tests prove BM25 results reflect entries added or removed by
  record/propose/expire without requiring a process restart.
- Privacy tests cover the configured salt boundary.
- Full test, lint, format, type, and smoke gates pass.

### Phase 0.5: Server Shape Cleanup

Status: first cleanup implemented in the current working branch.

GitHub issue: [#100](https://github.com/ostinato-forge/jurati/issues/100).

Goal: make the MCP server easier to maintain without changing the public tool
surface.

Work:

- Begin splitting `server.py` into a public facade plus focused state,
  read/retrieval, write/advisory, coordination, and future admin/sync modules.
- Keep `jurati.server` as the public import facade while helper modules move
  behind it, so tests and clients that import existing helper names do not
  break during the split.
- Keep the `core/` and `git/` boundary intact: pure deterministic behavior
  remains in `core/`; side effects remain in `git/`; server modules orchestrate.
- Move helpers only when tests prove behavior is unchanged.

Acceptance:

- Tool names, input shapes, output shapes, and startup behavior are unchanged.
- Existing MCP smoke, server, privacy, write, and coordination tests pass.
- New module boundaries make it clear where read/query, write, sync/health, and
  transport behavior live.
- First extraction has separate state, read/retrieval, write/advisory, and
  coordination modules. A later extraction can move sync/admin and tool
  registration if `server.py` grows again.

### Phase 1: Repo-Discovered Team Adoption

Status: repo-readiness and CI-check slices implemented.

GitHub issue: [#91](https://github.com/ostinato-forge/jurati/issues/91).

Goal: a teammate who clones a participating repo can connect Jurati without
learning MCP internals or manually copying environment variables. This is
"zero-config" only after repo maintainers opt the project into Jurati.

Implemented in first slice:

- Treat repo-owned `.jurati/config.yaml` as the team participation marker.
- Keep `.jurati/config.yaml` free of personal identity, local paths, tokens,
  user installation state, and teammate presence.
- Add a project discovery path that finds the knowledge remote from repo config,
  project MCP config, or existing Jurati instructions before asking questions.
- Extend `jurati doctor` with a team-readiness view that reports repo setup
  health: knowledge remote configured, project MCP config present, startup
  contract installed, read-only tool permissions present, write path available,
  active refs policy known.
- Add a repair path for safe project-local files only, building on
  `doctor --fix-project-config`.
- Add a GitHub Action or local check that can publish repo readiness as a
  status check or badge.

Remaining:

- Keep social proof at the repo level: "this repo participates in Jurati," not
  "these people have Jurati installed."

Acceptance:

- A fresh teammate can clone a project repo, run one command, and get a working
  read-only Jurati connection.
- `doctor --team` or equivalent reports actionable repo readiness without
  exposing teammate installation status.
- The setup path works without raw MCP protocol instructions.
- Existing `doctor --check-startup` and connected-agent smokes still pass.

### Phase 2: Existing Knowledge Bootstrap

Status: first Markdown import slice implemented.

GitHub issue: [#92](https://github.com/ostinato-forge/jurati/issues/92).

Goal: teams should not have to start from an empty knowledge repo.

Work:

- Add import modes for common existing sources:
  - `docs/adr/` and ADR-like Markdown: implemented with `import-docs --mode adr`
  - RFC directories: implemented with `import-docs --mode rfc`
  - existing project docs selected by path allowlist: implemented with
    `import-docs --mode docs`
  - GitHub Discussions or issue threads, behind explicit opt-in, label/date
    filters, and public/private source policy
- Keep the context-pack dry-run model: classify, reject risky content, summarize
  create/skip/reject, then write only through a review branch: implemented for
  local Markdown imports.
- Add mapping guidance for turning source documents into project, workflow,
  decision, or principle entries.
- Preserve source links and provenance without importing private comments or
  broad chat transcripts.
- Reject or redact personal, sensitive, stale, or off-topic discussion content
  during dry-run before any branch is created.

Acceptance:

- A repo with ADRs can generate a reviewable Jurati import PR: implemented for
  local Markdown directories.
- Dry-run output explains rejected files and risky content before any branch is
  created: implemented for local Markdown directories.
- Imported entries pass normal validation, content safety, and privacy filters:
  implemented for local Markdown directories.
- The adoption guide shows migration from existing docs as the default team
  bootstrap path: implemented for local Markdown directories.

### Dogfood Gate: Team Loop Proof

Status: required before Phase 5 or any broader enterprise, dashboard, hosted, or
IDE work.

GitHub issue: [#90](https://github.com/ostinato-forge/jurati/issues/90).

Goal: prove the adoption loop with real client behavior before widening the
product.

Work:

- Run a two-user, two-repo dogfood with a real MCP client.
- Run once with active refs disabled, using only durable context and PR/Jira
  signals.
- Run again with active refs enabled by explicit repo policy, if the first pass
  justifies testing ephemeral coordination.
- Capture first agent actions, missed context, setup friction, leaked internals,
  curation usefulness, and whether existing-doc import seeded enough context.
- Convert failures into Phase 0, 1, 2, 3, or 4 follow-ups before continuing.

Acceptance:

- Evidence shows `sync()` and `context()` happen before local exploration.
- A fresh teammate can connect without maintainer-only knowledge.
- Imported or seeded knowledge produces useful context in normal work.
- Active refs, if tested, behave as intentional broadcast and not surveillance.
- No Phase 5+ work starts while known team-loop blockers remain.

### Phase 3: Privacy-Safe Live Coordination

Status: repo-policy MCP wiring slice implemented.

GitHub issue: [#93](https://github.com/ostinato-forge/jurati/issues/93).

Goal: unlock the real-time value of active context without making activity
tracking the default.

Work:

- Keep `active_refs_enabled=false` as the package default.
- Add a repo policy option for active refs with explicit TTL, allowed entry
  types, client slug rules, and visibility constraints: first slice wires
  repo-owned enablement and TTL into project MCP config; active writes remain
  type `active` and internal visibility.
- Make onboarding explain active context as intentional broadcast, not telemetry.
- Add `doctor` checks that show active-ref policy and whether the current
  client is allowed to write L0 context: first slice reports repo policy and
  TTL.
- Keep PR and Jira signal coordination useful for teams that never enable active
  refs.
- Add tests proving restricted entries cannot be active context and expired
  active refs disappear from broad retrieval.

Acceptance:

- A team can enable active refs as a conscious repo policy, not a hidden user
  preference: implemented for project MCP config generation.
- Developers are never asked to manage active entry lifecycle directly: first
  slice defaults active expiry from repo TTL.
- PR/Jira coordination remains valuable when active refs are disabled.
- The privacy docs clearly explain what active refs broadcast and what they do
  not reveal.

### Phase 4: Auto-Curation And Knowledge Decay

Status: first lifecycle metadata slice implemented.

GitHub issue: [#94](https://github.com/ostinato-forge/jurati/issues/94).

Goal: stop the knowledge repo from becoming a graveyard.

Work:

- Add a curation engine that compares merged PRs, changed files, labels, and
  entry metadata against existing Jurati entries.
- Suggest expiry, supersession, or revalidation for related active, project,
  workflow, decision, and principle entries: first slice surfaces explicit
  `review_after` revalidation prompts in hygiene output.
- Add optional `review_after` or similar lifecycle metadata for durable
  project, workflow, decision, and principle entries: implemented.
- Generate curation plans as normal review PRs, not silent rewrites.
- Extend hygiene beyond expired active and stale proposed entries to cover
  durable entries that have not been revalidated after relevant code or doc
  churn.
- Let agents consume curation advisories silently during normal work.

Acceptance:

- After a representative PR merge, Jurati can propose a review PR that expires
  stale active context and marks related durable entries for review.
- Durable decisions can be superseded or revalidated without inventing a new
  storage system: first slice adds `review_after` metadata and hygiene
  reporting.
- Hygiene output explains why an entry needs attention using only repo state and
  explicit metadata, not reads, presence, or editor activity.
- Curation PRs are deterministic enough to test with fixtures.

### Phase 5: Privacy-Preserving Impact Metrics

Status: planned, requires privacy design before implementation.

GitHub issue: [#95](https://github.com/ostinato-forge/jurati/issues/95).

Goal: give leads and managers evidence that Jurati is helping without turning
Jurati into telemetry.

Measure system events first:

- curation suggestions created
- stale entries expired or superseded
- duplicate-write advisories triggered
- labeled PR or Jira coordination signals fetched and classified by category
- import dry-run rejections that prevented unsafe publication
- write PRs opened, merged, or abandoned
- retrieval fixture quality over time

Be cautious with read-path metrics:

- Do not persist raw queries.
- Do not persist caller identity.
- Do not create entry-level read receipts.
- If context-output inclusion counts are added later, they must be aggregate,
  repo-scoped, identity-free, retention-bounded, and reviewed as a privacy
  design before implementation.

Acceptance:

- A manager can see team-level system outcomes without seeing who queried,
  who read, or who was active.
- Metrics can be disabled entirely.
- The metrics model is documented in the privacy boundary before code ships.
- Tests prove raw query text and caller identity are not written.

### Phase 6: Enterprise Content Safety And Write Auditability

Status: planned.

GitHub issue: [#96](https://github.com/ostinato-forge/jurati/issues/96).

Goal: make the write path credible for security-sensitive teams without
pretending regex checks are enough.

Work:

- Keep the current regex checks as a fast baseline.
- Add pluggable scanners for stronger detection, starting with Gitleaks or
  TruffleHog-compatible adapters.
- Support policy configuration for scanner requirements, severity thresholds,
  and allowed exceptions.
- Emit write-path audit records for attempted publications, rejected content,
  scanner versions, policy decisions, and resulting branch or PR references.
- Keep audit records free of raw rejected content, raw secrets, raw scanner match
  text, and read/query activity. Retention and actor-identity rules must be
  documented before audit records ship; actor identity is allowed only where it
  already exists as deliberate git write provenance.
- Integrate with GitHub secret scanning or push-protection evidence where
  available.
- Keep read-path privacy separate from write-path auditability: deliberate
  publications can be audited; ordinary reads still do not create participation
  records.

Acceptance:

- Secret-like content is rejected by fixture tests beyond simple regex cases.
- A security reviewer can see which scanner and policy blocked a write.
- Write audit records do not include raw secrets.
- Existing content-safety tests still pass without network access.

### Phase 7: Non-Engineer Read Surface

Status: planned.

GitHub issue: [#97](https://github.com/ostinato-forge/jurati/issues/97).

Goal: PMs, designers, compliance reviewers, and managers can read team context
without git literacy.

Work:

- Extend `jurati html` into a polished read-only team browser before building a
  separate web app.
- Add search, type/status filters, lifecycle state, backlinks, supersession
  links, and source provenance.
- Keep search client-side and static. The generated browser must not persist
  query text or send it to a service.
- Keep restricted entries excluded.
- Add "propose update" affordances as issue-template links, PR links, or CLI
  handoffs first, rather than a hidden service or comment database.
- Publish through GitHub Pages or a static artifact first.

Acceptance:

- A non-engineer can find the current decision and see whether it has been
  superseded.
- The generated site remains static and deployable without a service.
- Restricted entries and restricted backlinks are absent.
- Proposed updates still go through normal review.

### Phase 8: Packaging And Fleet Installation

Status: planned.

GitHub issue: [#98](https://github.com/ostinato-forge/jurati/issues/98).

Goal: reduce installation friction for larger teams and locked-down machines.

Work:

- Make `uvx`/`pipx` the documented happy path and keep package metadata clean.
- Publish a Docker image for teams that prefer pinned runtime environments.
- Provide a GitHub Action setup path for CI and repo readiness checks.
- Add OS-specific notes for macOS, Linux, and locked-down corporate machines.
- Keep hosted Jurati as a future option only after local/team-mode adoption is
  proven.

Acceptance:

- A team can choose package, `uvx`, or container installation without changing
  the knowledge repo contract.
- Installed-package smoke covers the default setup path.
- Docker smoke proves `serve --check`, `doctor --check-startup`, and validation.
- Hosted-service planning remains explicitly optional and not required for open
  source adoption.

### Phase 9: IDE And Agent-Client Surfaces

Status: future.

GitHub issue: [#99](https://github.com/ostinato-forge/jurati/issues/99).

Goal: make relevant decisions visible when agents are not the only interface.

Work:

- Design a VS Code panel that shows decisions relevant to the current file or
  repo path.
- Prefer read-only context and curation prompts before adding write UI.
- Reuse the same retrieval, privacy, and policy logic as MCP tools.
- Avoid editor telemetry. File relevance should be local and explicit.

Acceptance:

- The IDE surface can answer "what decisions matter for this file?" without
  tracking editor activity centrally.
- It degrades to read-only mode when write configuration is absent.
- It does not create a second source of truth.

## Issue Spine

Track the work as a main tracker plus focused roadmap issues:

Main tracker:

1. [#89 Build plan: team adoption, curation, and product expansion
   roadmap](https://github.com/ostinato-forge/jurati/issues/89).

Active roadmap candidates:

1. [#90 Dogfood gate: prove the two-user team
   loop](https://github.com/ostinato-forge/jurati/issues/90).
2. [#91 Complete repo-discovered team
   adoption](https://github.com/ostinato-forge/jurati/issues/91).
3. [#92 Complete existing knowledge
   bootstrap](https://github.com/ostinato-forge/jurati/issues/92).
4. [#93 Complete privacy-safe active
   coordination](https://github.com/ostinato-forge/jurati/issues/93).
5. [#94 Build auto-curation and durable knowledge
   decay](https://github.com/ostinato-forge/jurati/issues/94).
6. [#100 Continue MCP server modularity
   cleanup](https://github.com/ostinato-forge/jurati/issues/100).

Gated future bets:

1. [#95 Privacy-preserving impact
   metrics](https://github.com/ostinato-forge/jurati/issues/95).
2. [#96 Enterprise content safety and write
   auditability](https://github.com/ostinato-forge/jurati/issues/96).
3. [#97 Non-engineer static read
   surface](https://github.com/ostinato-forge/jurati/issues/97).
4. [#98 Packaging, Docker, and fleet
   installation](https://github.com/ostinato-forge/jurati/issues/98).
5. [#99 IDE and agent-client
   surfaces](https://github.com/ostinato-forge/jurati/issues/99).

Metrics, enterprise scanner integrations, richer visual surfaces, Docker,
hosted options, and IDE work should not compete with team setup, import, and
curation unless a pilot forces a different order.

## Current Next Step

Run the dogfood gate in
[#90](https://github.com/ostinato-forge/jurati/issues/90), then use the evidence
to refine Phases 1 through 4 before starting Phase 5 or any broader enterprise,
dashboard, hosted, or IDE work.

The next implementation bet should be the smallest useful curation loop in
[#94](https://github.com/ostinato-forge/jurati/issues/94): compare merged PRs,
changed files, labels, and entry metadata, then propose review PRs for expiry,
supersession, or revalidation. Team setup creates participation, existing-doc
import seeds enough real context to make the product useful, and curation keeps
that context from fossilizing.
