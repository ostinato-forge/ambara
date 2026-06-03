# Ambara Complete Build Plan

Status: canonical build plan
Updated: 2026-06-03

## Answer

The existing competitive plan is good, but it is not a complete build plan. It
is a release-shaping document: it explains why Ambara should win, what to
emphasize, and what the first release should prove. This plan is the
build-complete version.

Build Ambara as one product:

- one PyPI distribution: `ambara`
- one import package: `ambara`
- one CLI: `ambara`
- one MCP server: `ambara`
- no package split for the initial release
- no legacy public namespace or compatibility story

The package split may never be needed. If users later ask for reusable
libraries, extraction can be reconsidered from real import pressure. It should
not shape v0.5.0.

## Product Promise

Ambara is reviewable project context for AI coding agents.

The user should be able to install Ambara, onboard a project, restart an agent,
and know that the agent starts from compact reviewed context before touching
code. If the agent relies on a specific source entry, it can read that entry
explicitly. If the user asks it to save context, short-lived handoffs are
recorded safely and durable decisions go through review.

Everything required to make that promise true is in scope.

## Scope Rules

### Build For v0.5.0

- governed Markdown plus YAML context repo
- schema validation, lifecycle, expiry, visibility, sensitivity, and links
- deterministic indexing, ranking, search, and selective reads
- `startup()` as the hero MCP workflow
- plain file adapter for agents without MCP
- explicit capture through `record()`, `propose()`, imports, hooks, and action
- PR-backed governance for durable decisions and workflows
- content safety, secret scanning, privacy gates, and posture checks
- value receipts and optional local aggregate value ledger
- GitHub and Jira coordination signal ingestion
- static HTML browser and local read model
- reproducible demo/proof fixtures
- install, onboarding, troubleshooting, client setup, and release docs
- built artifact verification, GitHub release, and PyPI publication

### Do Not Build For v0.5.0

These are not cuts from the Ambara product promise. They are different products
or stronger claims than Ambara should make at launch.

- package family split
- cloud service
- OS-level automatic workflow capture
- multi-user hosted dashboard
- code graph impact analysis
- immutable ledger, tamper-evident audit, or SOC2-ready evidence claims
- activity feeds, read receipts, presence, or participation tracking

If any of those becomes a real goal, write a separate plan and change the public
claims first.

## Release Bar

Ambara v0.5.0 is ready only when all of this is true from the built artifact,
not merely from an editable source checkout:

- `pip install ambara` installs the wheel in a clean virtual environment.
- `ambara onboard --yes` creates a usable local project setup.
- `ambara doctor --check-startup` explains readiness and failure modes.
- `ambara startup` or the MCP `startup()` tool returns a compact packet with
  availability, verdict, action, entries, read hints, and value receipt.
- `read()` and `read_many()` return full bodies only when explicitly requested.
- `record()` can save short-lived handoff context.
- `propose()` can create reviewable durable context.
- restricted entries are excluded from broad context and search.
- obvious credentials are blocked before any write reaches git.
- value receipts never store query text, response bodies, caller identity, body
  snippets, or durable per-entry read receipts.
- a reproducible demo proves the two-agent handoff story.
- docs describe only clients and flows that were actually smoked.
- release artifacts pass tests, lint, type check, build, install, and smoke.

## Track 0: Repo Truth And Release Hygiene

Goal: make the repo impossible to misunderstand before implementation resumes.

Tasks:

- Start all work from a clean branch based on `origin/main`.
- Reconcile the local divergent pre-squash checkout before doing product work.
- Keep `planning/complete-build-plan.md` as the canonical plan.
- Keep `planning/initial-release-competitive-plan.md` as market rationale.
- Mark `docs/package-split-plan.md` as deferred / maybe never.
- Remove stale references to old product names, old script names, and package
  split commitments.
- Verify `.github/workflows/release.yml` matches the intended PyPI path.
- Verify repo metadata, issue templates, PR template, security policy,
  changelog, and classifiers all say Ambara.

Exit criteria:

- `rg "Jurati|jurati|nodrel|package split|compatibility window"` has no public
  release-blocking hits.
- New contributors see one product, one package, one CLI, and one plan.

Primary files:

- `README.md`
- `CHANGELOG.md`
- `pyproject.toml`
- `SECURITY.md`
- `.github/workflows/*`
- `planning/*`
- `docs/*`

## Track 1: Public Contracts

Goal: freeze the small set of contracts that external users and docs depend on.

Tasks:

- Freeze the startup packet public fields:
  - `v`
  - `availability`
  - `verdict`
  - `action`
  - `entries`
  - `read_hints`
  - `value`
  - `coordination`
  - `curation`
- Document stale, unavailable, disabled, and healthy startup states.
- Freeze entry type vocabulary:
  - `active`
  - `project`
  - `decision`
  - `workflow`
  - `principle`
- Freeze visibility and sensitivity behavior for broad context and reads.
- Freeze write receipt fields for `record()`, `propose()`, and `expire()`.
- Add or tighten golden payload fixtures for startup, compiler/context, value,
  write receipts, restricted filtering, and unavailable context.
- Add a short public contract doc for agents: call `startup()` first, follow
  read hints, read cited entries before relying on bodies, write only when the
  user explicitly asks.

Exit criteria:

- Breaking these packet shapes breaks tests.
- Docs can show real payload excerpts without hand editing.

Primary files:

- `src/ambara/server.py`
- `src/ambara/server_read.py`
- `src/ambara/server_write.py`
- `src/ambara/core/context_compiler.py`
- `src/ambara/core/schema.py`
- `tests/test_startup_v2_rendering.py`
- `tests/core/test_startup_v2_compiler.py`
- `tests/test_mcp_smoke.py`

## Track 2: First-Run Onboarding And Client Setup

Goal: make a fresh user successful in minutes.

Tasks:

- Prove `ambara onboard --yes` in a clean fixture.
- Prove `ambara doctor --check-startup` gives actionable results before and
  after setup.
- Prove `ambara serve --check` fails clearly without required config.
- Prove the Claude Code setup path because the generated startup contract is
  part of the launch story.
- Prove the plain file adapter path for non-MCP agents.
- Add a client-support matrix with statuses:
  - first-class and smoked
  - protocol-compatible but not manually smoked
  - planned
- Remove any "tested with" language for clients that were not manually smoked.
- Add exact uninstall, disable, and troubleshooting steps.
- Add cache and permission troubleshooting for common local failures.

Exit criteria:

- A clean virtual environment plus empty test project can onboard, diagnose,
  and produce startup context without internal knowledge.
- Docs state exactly what is first-class.

Primary files:

- `src/ambara/cli.py`
- `src/ambara/cli_install.py`
- `src/ambara/cli_render.py`
- `bin/ambara-mcp.sh`
- `docs/install-troubleshooting.md`
- `tests/test_cli.py`
- `tests/test_cli_file_adapter.py`
- `tests/test_server_dx.py`

## Track 3: Startup, Retrieval, And Context Quality

Goal: make `startup()` the thing that makes Ambara obviously better than a
generic memory bucket.

Tasks:

- Ensure `startup()` syncs, compiles, ranks, and returns compact context.
- Ensure `context(mode="startup")` and `startup()` are equivalent where they
  should be.
- Ensure stale or unavailable context changes the verdict and action.
- Ensure restricted entries are omitted from startup, context, query, search,
  list, static HTML, and read model indexes.
- Ensure `read_hints` point to resolvable entries and explain why a read is
  useful.
- Keep full bodies deferred by default.
- Keep `read_many()` bounded and failure messages actionable.
- Tune ranking fixtures for project affinity, recency, type weighting, and
  lexical fallback.
- Add a compact "why this was included" field only if it can be deterministic
  and tested.

Exit criteria:

- A fresh agent can follow startup, selectively read entries, and continue work
  without local bulk reading.
- Retrieval quality has golden fixtures and no hidden body leakage.

Primary files:

- `src/ambara/server.py`
- `src/ambara/server_read.py`
- `src/ambara/server_snapshot.py`
- `src/ambara/core/search.py`
- `src/ambara/core/scoring.py`
- `src/ambara/core/index.py`
- `src/ambara/read_model/sqlite.py`
- `tests/test_context_compiler_equivalence.py`
- `tests/test_context_token_efficiency.py`
- `tests/test_retrieval_quality.py`
- `tests/core/test_index_search.py`
- `tests/read_model/test_sqlite.py`

## Track 4: Governance, Writes, And Review

Goal: make "explicit capture, reviewed durability" real.

Tasks:

- Prove `record()` for active handoffs with TTL and active refs.
- Prove `record()` for low-ceremony project updates.
- Prove `propose()` for durable decisions and workflows through review PRs.
- Prove `expire()` for active refs and durable entries.
- Prove write advisories for duplicates, stale entries, and likely corrections.
- Prove branch-only fallback when PR creation is unavailable.
- Prove GitHub auth candidate selection and failure messages.
- Prove cleanup of temporary branches and locks after failed writes.
- Ensure agents are told never to expose raw entry IDs in normal user replies.
- Ensure write docs explain active vs durable context in plain language.

Exit criteria:

- Durable knowledge changes are reviewable by default.
- Handoffs remain short-lived.
- Write failures leave the repo understandable.

Primary files:

- `src/ambara/server.py`
- `src/ambara/server_write.py`
- `src/ambara/core/changes.py`
- `src/ambara/git/*`
- `tests/test_server_write.py`
- `tests/git/*`
- `tests/core/test_changes.py`

## Track 5: Privacy, Security, And Posture

Goal: make privacy and safety product gates, not marketing copy.

Tasks:

- Verify no query logging, read receipts, presence, activity feed, or
  participation tracking exists.
- Verify value and feedback storage stays local and aggregate.
- Verify restricted entries are excluded from every broad-read surface.
- Verify content policy blocks obvious credentials and flags risky content.
- Verify PII/personnel warnings are surfaced before durable writes.
- Verify path derivation rejects traversal and unsafe filenames.
- Verify `ambara posture-check` detects tracked local secret files, missing
  ignore patterns, and agent-start guardrail failures.
- Verify `ambara posture-check --fix` only performs safe project-local fixes.
- Keep `SECURITY.md` honest about what is and is not protected.
- Keep audit/compliance diagnostics conservative.

Exit criteria:

- Privacy claims are regression-tested.
- Secret-like content cannot reach git through Ambara write paths.
- Posture failures block agent-safe-start claims.

Primary files:

- `src/ambara/core/privacy.py`
- `src/ambara/core/content_policy.py`
- `src/ambara/core/secrets.py`
- `src/ambara/core/posture.py`
- `src/ambara/posture.py`
- `src/ambara/server_content_policy.py`
- `tests/test_privacy.py`
- `tests/test_privacy_coordination.py`
- `tests/test_content_safety.py`
- `tests/core/test_posture.py`
- `tests/core/test_secrets.py`

## Track 6: Value Receipts And Economics

Goal: show restraint and avoided rediscovery without pretending to know total
provider billing.

Tasks:

- Ensure startup/context packets include compact value receipts.
- Ensure full-body deferral and suppression counts are represented.
- Ensure `ambara value` summarizes local aggregate app-payload estimates.
- Ensure `ambara value --explain` says estimates are Ambara app-payload only.
- Ensure read and read_many accounting remains privacy-preserving.
- Ensure feedback can suppress noisy entries without creating shared read
  receipts.
- Add docs that separate app payload cost from client session, cache, and model
  provider billing.
- Include value output in the public demo.

Exit criteria:

- A user sees why Ambara reduces waste.
- No value feature weakens the privacy boundary.

Primary files:

- `src/ambara/core/context_accounting.py`
- `src/ambara/server_value.py`
- `src/ambara/server_read.py`
- `src/ambara/cli.py`
- `tests/core/test_context_accounting.py`
- `tests/test_context_token_efficiency.py`

## Track 7: Providers And Project Signals

Goal: make GitHub and Jira useful without making them mandatory.

Tasks:

- Prove fixture provider behavior for deterministic tests.
- Prove GitHub PR signal parsing, label mapping, privacy sanitization, and
  cache behavior.
- Prove Jira issue parsing, effect mapping, pagination/error behavior, and
  cache behavior.
- Document provider environment variables and disabled states.
- Ensure provider errors do not prevent core startup unless the configured
  policy requires it.
- Ensure signal text is sanitized before surfacing in context.
- Include one provider-backed example in the demo if it can run without live
  credentials; otherwise use fixture provider only for public proof.

Exit criteria:

- Ambara works with no provider configured.
- When providers are configured, signals improve startup context without
  breaking privacy.

Primary files:

- `src/ambara/providers/*`
- `src/ambara/server_coordination.py`
- `src/ambara/server_curation.py`
- `src/ambara/core/pr_signals.py`
- `tests/providers/*`
- `tests/test_server_coordination.py`
- `tests/test_privacy_coordination.py`

## Track 8: Import, Capture, And GitHub Action

Goal: make explicit context capture useful beyond one-off MCP writes.

Tasks:

- Prove `ambara import-docs --dry-run` for ADR, RFC, docs, and Obsidian modes.
- Prove `ambara import-context --dry-run` for context packs.
- Prove rejected imports explain why they were rejected.
- Prove non-dry-run imports create review branches.
- Prove `install-hook` and capture pipeline create pending local drafts only;
  they must not silently promote durable memory.
- Prove GitHub Action capture behavior with fixture inputs.
- Document exactly when hooks/actions are explicit, pending, reviewable, or
  disabled.
- Ensure all capture paths reuse content policy and schema validation.

Exit criteria:

- Teams can seed Ambara from existing docs.
- Capture never becomes invisible surveillance.

Primary files:

- `src/ambara/import_context.py`
- `src/ambara/git/import_context.py`
- `src/ambara/capture/*`
- `src/ambara/action/*`
- `action/action.yml`
- `tests/test_import_context.py`
- `tests/capture/*`
- `tests/action/*`

## Track 9: Browser, Read Model, And Inspection

Goal: let users inspect what agents can see without learning MCP.

Tasks:

- Polish `ambara html` output enough for browsing entries, types, status,
  tags, project filters, and lifecycle state.
- Ensure restricted entries are skipped and the skipped count is visible.
- Ensure parse errors are visible and fail the command.
- Prove generated HTML has no broken internal links in fixtures.
- Prove read-model rebuild and query behavior for local search.
- Document the browser as inspection, not a hosted dashboard.

Exit criteria:

- A skeptical user can inspect their context repo locally.
- The browser does not leak restricted content.

Primary files:

- `src/ambara/static_html.py`
- `src/ambara/read_model/sqlite.py`
- `src/ambara/cli.py`
- `tests/test_static_html.py`
- `tests/read_model/test_sqlite.py`

## Track 10: Demo And Proof Suite

Goal: make the product legible in one reproducible story.

Tasks:

- Add a demo fixture or command that creates:
  - one reviewed decision
  - one workflow
  - one project status entry
  - one active handoff
  - one stale entry
  - one restricted entry
  - one duplicate/stale proposal warning case
  - one fixture provider signal
- Add a documented proof script that runs:
  - install from wheel
  - onboard
  - doctor
  - startup
  - selective read
  - record active handoff
  - propose durable decision
  - value summary
  - static HTML generation
  - privacy smoke
- Store expected excerpts for startup, value, privacy, and HTML generation.
- Prefer a small `ambara demo` command if it simplifies the proof story.

Exit criteria:

- A developer can run the demo locally and understand Ambara in under ten
  minutes.
- The demo proves the wedge: reviewed context, explicit capture, selective
  reads, privacy, and value restraint.

Primary files:

- `src/ambara/cli.py`
- `tests/test_mcp_smoke.py`
- `tests/test_cli.py`
- `tests/test_static_html.py`
- `docs/install-troubleshooting.md`
- `README.md`

## Track 11: Docs, Positioning, And Launch Surface

Goal: make the launch honest, sharp, and usable.

Tasks:

- Rewrite README around the final story:
  - reviewable project context for AI coding agents
  - `startup()` first
  - explicit capture
  - PR-backed durable context
  - privacy and value as product gates
- Add "Why not built-in agent memory?" with a precise comparison.
- Add "What Ambara does not track" and "What Ambara does not claim."
- Add "Client support" with verified status.
- Add "Run the demo" with exact commands.
- Add "Release proof" with exact verification commands.
- Update changelog with only verified capabilities.
- Update slides or launch HTML to match final language.
- Draft GitHub release notes.
- Draft short launch copy for the first public announcement.

Exit criteria:

- Public docs do not overstate maturity, client support, security, audit,
  traction, or ecosystem adoption.
- A new user knows exactly how to start and why Ambara is different.

Primary files:

- `README.md`
- `CHANGELOG.md`
- `docs/install-troubleshooting.md`
- `product-and-tech-slides.html`
- `.github/ISSUE_TEMPLATE/*`

## Track 12: Packaging, CI, And Release

Goal: ship something people can install.

Tasks:

- Verify supported Python versions and classifiers.
- Verify package data includes scripts, templates, static assets, and action
  assets needed by installed users.
- Verify clean `uv lock --check`.
- Build wheel and source distribution.
- Install from built wheel into a clean virtual environment.
- Smoke installed commands:
  - `ambara --version`
  - `ambara --help`
  - `ambara explain`
  - `ambara doctor`
  - `ambara serve --check`
  - `ambara posture-check --json`
- Run full local test, lint, and type-check suite.
- Confirm CI, CodeQL, hygiene, and release workflows are green.
- Configure PyPI trusted publisher or choose the explicit manual publishing
  path before tagging.
- Publish to TestPyPI only if it meaningfully catches packaging issues.
- Tag `v0.5.0`.
- Publish PyPI.
- Create GitHub release with verified release notes.

Exit criteria:

- The released artifact behaves like the verified artifact.
- The tag, GitHub release, and PyPI package all point to the same source state.

Primary files:

- `pyproject.toml`
- `uv.lock`
- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`
- `CHANGELOG.md`

## Track 13: Post-Release Feedback Loop

Goal: learn from real users without adding telemetry.

Tasks:

- Keep issue templates focused on setup failure, context quality, client setup,
  privacy concerns, and provider integrations.
- Add a short "how to report bad context" doc.
- Add a "known limitations" section that is honest and specific.
- Triage first issues into:
  - setup friction
  - context quality
  - provider integration
  - docs confusion
  - feature request
  - not Ambara's product boundary
- Do not add telemetry to answer adoption questions.
- Use reproducible user reports and local fixtures as the feedback mechanism.

Exit criteria:

- The project can improve after release without weakening its privacy stance.

Primary files:

- `.github/ISSUE_TEMPLATE/*`
- `README.md`
- `docs/install-troubleshooting.md`

## Sprint Plan

### Sprint 0: Plan And Truth Reset

- Land this plan.
- Retire package split as roadmap.
- Start future work from a clean `origin/main` branch.
- Fix any stale old-name release docs.

Definition of done:

- The repo has one canonical build plan and no stale release-blocking package
  split commitment.

### Sprint 1: First-Run And Startup Proof

- Fresh install fixture.
- Onboard and doctor proof.
- Startup packet golden fixtures.
- File adapter smoke.
- Claude Code setup smoke.

Definition of done:

- A fresh project can produce correct startup context from the built artifact.

### Sprint 2: Demo, Value, And Privacy Proof

- Reproducible two-agent demo.
- Value receipt and value command proof.
- Privacy and restricted-entry smoke.
- Static HTML inspection proof.

Definition of done:

- The public demo proves Ambara's differentiators locally.

### Sprint 3: Writes, Providers, Import, Capture, And Action

- Record/propose/expire proof.
- Write advisories proof.
- GitHub/Jira fixture-provider proof.
- Import docs/context proof.
- Capture hook and GitHub Action proof.

Definition of done:

- Every README/changelog feature has either a test, a smoke, or is removed from
  public docs.

### Sprint 4: Docs And Launch Polish

- README final pass.
- Install/troubleshooting final pass.
- Client support matrix.
- Changelog and release notes.
- Launch copy and slides aligned with verified claims.

Definition of done:

- A new user can install, understand, run the demo, and know the limitations.

### Sprint 5: Release

- Full test/lint/type/build/install smoke.
- CI green.
- PyPI release path confirmed.
- Tag.
- Publish.
- GitHub release.

Definition of done:

- Ambara v0.5.0 is installable from PyPI and the release notes match the
  verified artifact.

## Build Queue

Build in this order:

1. Planning truth and old-name cleanup.
2. Startup packet contract and first-run proof.
3. Demo fixture/proof command.
4. Privacy/value gates.
5. Write and review workflow proof.
6. Provider/import/capture/action proof.
7. Static HTML/read-model inspection polish.
8. Docs and launch copy.
9. Package/release pipeline.
10. Publish.

## Open Decisions

These should be decided before Sprint 5, not before coding starts:

- PyPI publishing method: trusted publisher or manual token.
- Whether `ambara demo` becomes a real CLI command or remains a documented
  fixture script.
- Which client claims are first-class for v0.5.0 after manual smoke.
- Whether TestPyPI adds value for this release.
- Whether to keep the product-and-tech slides as launch surface or replace them
  with a simpler demo page.

## Confidence

Current confidence with the complete plan: 8/10 to start building.

Confidence rises to 9/10 when Sprint 1 and Sprint 2 are green from the built
artifact. At that point the remaining work is mostly proof expansion, docs, and
release mechanics.
