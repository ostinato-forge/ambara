# Constraint Trust And Correctness Plan

Status: proposal and release-gate amendment. [Jurati Build Plan](build-plan.md)
remains the execution authority. This document owns the rationale, contracts, and
test philosophy for constraint trust and correctness. It does not create a broad
new phase ahead of the real-team loop; it defines the targeted correctness work
that must happen before compiler mode becomes the public default.

## Purpose

The [Context Compiler Pivot](context-compiler-pivot.md) solved the downstream
half of the product well: it turns a corpus into a typed, deterministic planning
packet with orthogonal availability and coordination axes, fail-closed
unavailable semantics, and no LLM on the hot path.

Five load-bearing gaps remain:

- **Authority is underspecified.** A constraint can stop work, but the current
  packet only tells the agent what the constraint says, not how much authority it
  has earned.
- **Extraction is uncalibrated.** Turning a reviewed entry, active ref, curation
  advisory, or labeled signal into `constraint{kind, effect}` carries the real
  judgment. Its false positives halt correct work; its false negatives miss real
  blockers.
- **Equivalence is not correctness.** Planning equivalence proves the compact
  packet preserves the same decision as full context. It does not prove that
  full context was right, scoped, fresh enough, or quiet enough.
- **Lifecycle control is too weak.** Jurati is easy to add to a project, but not
  yet easy enough to pause, mute, or retire when the developer changes work. A
  finished project should not keep surfacing as active guidance, and a broken or
  unwanted Jurati setup should have an obvious off switch.
- **Audit/compliance language is ahead of implementation.** The code is
  reviewable and git-backed, but it is not yet an immutable or tamper-evident
  audit ledger. Commits are not signed or verified by Jurati, expiry rewrites
  entry files in place, L0 active refs can be deleted, branch protection is an
  external host assumption, and `recorded_by` / `source` metadata are
  informational rather than authenticated identity.

This plan adds constraint authority metadata, deterministic extraction
calibration, authored outcome evidence, authoring-time defenses, lifecycle
controls, and a compliance-claim gate while preserving the privacy boundary and
git-reviewed source ledger.

## Product Claim

A constraint should carry not only what to do, but how much authority it has to
stop the agent. Jurati should be able to say:

- "pause because a reviewed team decision directs it"
- "verify before acting because one unconfirmed signal suggests it"
- "proceed with caution because a derived advisory may be relevant"

It should also be able to show, from reviewed evidence, how often its verdicts
were useful, noisy, or wrong.

Separately, Jurati should be precise about audit language. The day-one claim is
"reviewable team context backed by git," not "immutable, tamper-evident ledger."
SOC2/audit positioning must wait until Jurati can prove signed/authenticated
writes, append-only evidence, protected history assumptions, and identity
binding instead of relying on ordinary mutable git operations and host policy.

## Relationship To The Build Plan

The build plan's current gate remains the real-team loop: prove Jurati works on
real tasks with real client behavior before widening the product. This document
adds a stricter gate for the compiler default:

- **Immediate targeted fixes:** Workstreams A and E are small correctness patches
  that can land before or during real-team testing.
- **Default-mode release gate:** Workstreams B and C must pass before compiler
  mode becomes the public default.
- **Evidence-driven deferrals:** Workstream F only happens if real-team testing
  proves startup friction is a material problem; the first preference is making
  startup cheap and quiet, not weakening the startup contract.
- **Lifecycle is not polish:** Workstream H should land before or alongside the
  real-team loop. A team cannot evaluate Jurati honestly if there is no obvious
  way to disable it, mute stale scopes, or retire completed work.
- **Compliance claims lag proof:** Workstream I is a positioning and
  implementation gate. It does not block real-team testing, but it does block
  any SOC2, immutable-ledger, tamper-evident, or audit-ledger claim.

If sequencing conflicts, follow [build-plan.md](build-plan.md).

## Planner/Reviewer Hardening Decisions

This pass closes the main holes before implementation:

- **Packet contract before schema expansion.** Constraint authority starts as a
  packet-level compiler/startup contract. Do not add durable frontmatter fields
  until a workstream proves they are needed for authored constraints.
- **Personal scope is local; team retirement is reviewed.** Muting AU0035L
  because one developer moved projects is a local/client or project-local
  preference. Retiring AU0035L because the work ended is shared, reviewable
  knowledge-repo state.
- **Disabled is not unavailable.** "Jurati is intentionally off here" is a valid
  state, not a broken startup baseline. Agents should proceed local-only when a
  project is explicitly disabled, while still stopping on unexpected stale or
  unavailable context.
- **Lifecycle cleanup is not git erasure.** Normal cleanup expires, mutes,
  retires, or supersedes context. Destructive history rewrite is only for
  explicit emergency purge workflows.
- **Do not overload `jurati flush`.** The CLI already uses `flush` for pending
  capture queues. Lifecycle commands should use clearer names such as
  `disable`, `enable`, `mute-scope`, `unmute-scope`, and `retire-scope`.
- **Do not sell compliance posture before the evidence exists.** Until the
  audit-ledger work lands, Jurati can say entries are reviewable in git. It
  cannot say the ledger is immutable or tamper-evident.

## Non-Goals

This plan does not require and must not introduce:

- an LLM on the `context()` hot path
- telemetry, read receipts, participation tracking, or activity inference
- behavioral derivation of correctness from observed user or agent activity
- raw query logging or entry-level read metrics
- a hosted service or centralized private content
- replacing git-reviewed Markdown as the source ledger
- claiming immutable ledger, tamper-evident ledger, SOC2-ready audit evidence,
  or authenticated authorship before the implementation proves those properties
- silent destructive deletion or git-history rewriting as the default way to
  stop hearing about old work

The privacy boundary in
[Security, Privacy, And Content Safety Gate](security-privacy-content-safety.md)
governs every workstream below.

---

## Workstream A - Constraint Authority Model

**Problem.** The constraint schema has `kind`, `effect`, `summary`, source/read
references, and no authority model. A machine-derived `pause`, a labeled PR
signal, an active ref, and a reviewed decision can all collapse into the same
agent-facing effect.

Do not solve this with one overloaded `provenance` string. Source type, review
state, corroboration, and agent-facing authority are related but distinct.

**Work.**

- Add closed metadata to the `Constraint` type:
  - `source_type`: `authored_entry`, `external_signal`, `derived_advisory`, or
    `active_ref`.
  - `review_state`: `reviewed`, `unreviewed`, or `derived`.
  - `corroboration`: `none`, `single_source`, `multiple_sources`, or
    `human_confirmed`.
  - `authority`: derived in `core/`, not authored directly.
- Add a pure `derive_constraint_authority(...)` function in `core/` that maps
  `(effect, source_type, review_state, corroboration)` to one of:
  - `directive`: may hard-stop work.
  - `corroborated_advisory`: may require read/verify/revise before acting.
  - `advisory`: may only produce caution.
- Preserve backward compatibility defensively: constraints without the new fields
  parse as unreviewed advisory data until rebuilt from trusted source artifacts.
- Keep the first implementation packet-level. If authored-entry constraints need
  durable authority metadata later, add that as an explicit schema migration with
  validation and import behavior.
- Make verdict and planning-action derivation consume effective authority rather
  than raw `effect` alone. A single unreviewed or derived signal cannot produce a
  hard `blocked` verdict unless it is corroborated or human-confirmed.
- Update startup rendering so the agent sees the distinction in normal planning
  language, for example "reviewed directive" versus "unreviewed advisory".

**Acceptance.**

- Every emitted constraint carries closed `source_type`, `review_state`,
  `corroboration`, and derived `authority` fields.
- The authority map is pure, exhaustively tested, and lives in `core/`.
- Raw `pause` from an unreviewed active ref, derived advisory, or single external
  signal cannot produce `planning_action: pause`.
- Compact and compiler planning-equivalence fixtures include the authority axis.
- Old packets or fixtures that lack authority fields fail closed as advisories,
  not directives.

## Workstream B - Extraction Calibration

**Problem.** Extraction is where the product's judgment lives, and it is
currently asserted more than measured. The plan must test the pure extraction
boundaries that exist in the codebase, not a generic "context quality" idea.

**Work.**

- Build a stratified corpus for the deterministic extractor functions:
  - PR and external signal classification in `core/pr_signals.py`.
  - Coordination and curation payload to `Constraint` conversion in
    `core/context_compiler.py`.
  - Entry-derived constraints once authored-entry extraction is added.
- Each case has `(artifact, repo, goal, paths) -> expected constraints` or an
  explicit empty constraint set.
- Required strata:
  - path-overlap open PR
  - merged PR that should lead to reuse/revise rather than pause
  - stale-but-relevant reviewed decision
  - expired active handoff
  - active unreviewed item that must not hard-block
  - contradictory authored constraints
  - irrelevant same-repo and different-repo signals that must yield nothing
- Report per-kind precision and recall plus two named release metrics:
  - **false-pause rate:** constraints that halted or revised work without enough
    authority.
  - **missed-blocker rate:** missing a constraint that should have blocked or
    forced verification.
- Keep extraction deterministic and in `core/`; the corpus tests rules, not a
  model.
- Treat the first corpus as a regression gate, not a fake statistical study. A
  release claim needs minimum case counts per source type and explicit notes
  about what the corpus does not cover.

**Acceptance.**

- The corpus has positive and negative cases for every source type.
- The harness reports per-kind precision/recall, false-pause rate, and
  missed-blocker rate.
- Regression thresholds are explicit in tests or release checks.
- Missed-blocker rate is a release gate before compiler mode becomes default.
- Irrelevant artifacts produce zero actionable constraints in the corpus.

## Workstream C - Reviewed Outcome Ledger

**Problem.** Planning equivalence cannot catch a verdict that is wrong in both
the full and compact packets. Correctness needs evidence from use, but evidence
must not become telemetry.

**Work.**

- Add an explicit, reviewed outcome record. It captures:
  - the packet schema/version and verdict category
  - a packet digest plus the relevant constraint IDs or source refs
  - what the human or agent decided next, in authored summary form
  - a reviewed hindsight judgment:
    `justified_pause`, `false_pause`, `missed_blocker`, `helpful_caution`, or
    `noise`
  - optional notes and follow-up issue/PR refs
- Store outcomes as git-reviewed knowledge artifacts or a closely related
  reviewed ledger format. They are authored samples, not automatic event logs.
- Do not store raw prompts, full packet payloads, source bodies, query text, or
  read activity in outcome records.
- Do not require humans to annotate every task. Outcome records are deliberate
  samples for calibration and postmortems, not a new background chore.
- Treat denominator language carefully. A summary may say "in reviewed outcome
  samples" or "among recorded outcome reviews"; it must not imply Jurati observed
  every agent action unless a human explicitly recorded those outcomes.
- Summarize outcomes into calibration signals sliced by `kind`, `source_type`,
  `review_state`, and `authority`.
- Treat `missed_blocker` as a high-severity outcome with a required follow-up
  note or issue link.

**Acceptance.**

- An outcome schema exists and is validated.
- Outcomes are explicit, reviewable, and never inferred from reads, activity,
  editor state, presence, or participation.
- Outcome records store compact references and digests, not raw task transcripts
  or full context payloads.
- Summaries distinguish reviewed samples from global rates.
- Outcome evidence, not only planning equivalence, gates making compiler mode the
  public default.
- The ledger stays entirely inside the privacy boundary.

## Workstream D - Authoring-Time Correctness Defenses

**Problem.** Freshness catches stale content, not content that was wrong when
authored. The deterministic compiler will faithfully turn a wrong reviewed
constraint into authority unless authoring has its own safeguards.

**Work.**

- Add explicit scope to high-impact constraints before contradiction logic relies
  on them: project/repo, paths or components, source system, and intended
  duration or review window.
- Extend contradiction/dedup logic to scoped constraints. A new authored
  directive that conflicts with an existing directive in the same scope must be
  resolved before it can drive a hard verdict.
- Add a corroboration requirement for unreviewed or derived hard stops: a hard
  block requires either multiple corroborating sources or explicit human
  confirmation.
- Allow high-impact authored constraints to carry optional `review_after` or
  `requires_corroboration` metadata beyond the default freshness window.

**Acceptance.**

- High-impact constraints have enough scope metadata for deterministic conflict
  checks.
- Conflicting reviewed directives in the same scope are surfaced for resolution.
- A single unreviewed or derived source cannot hard-block without corroboration.
- Tests cover both false conflicts and missed conflicts.

---

## Trust-Surface And DX Fixes

These are smaller than the authority/correctness work, but they decide whether
the trust model holds in practice.

### E - MCP And CLI Startup Parity

The current product has MCP `sync()`, `context()`, and `startup()`, plus a
`jurati startup` CLI path. The issue is not merely command names; it is whether
CLI startup carries the same semantics, freshness behavior, coordination
signals, curation advisories, and authority fields as MCP startup.

**Work.**

- Define one startup packet contract shared by MCP `startup()`, MCP
  `context(mode="startup")`, and `jurati startup`.
- Ensure CLI startup uses the same read model or a documented safe subset. If
  signals or curation are unavailable in CLI mode, the packet must say so rather
  than returning a misleading clear baseline.
- Update generated startup instructions so MCP-only and CLI/file-adapter
  deployments have a contract that succeeds verbatim in their environment.

**Acceptance.**

- MCP and CLI startup packets share the same schema and authority semantics.
- Missing CLI-only inputs fail closed or are explicitly marked unavailable.
- The first two startup steps in generated agent instructions are executable in
  the deployment mode that installed them.

### F - Startup Friction, Only If Evidence Requires It

The startup contract is intentionally strict because local-only reasoning is the
failure Jurati exists to prevent. Do not weaken it preemptively.

**Work.**

- First make startup cheaper, quieter, and more reliable through caching,
  compact packets, and better unavailable/stale messages.
- During the real-team loop, record whether strict startup blocks trivial
  read-only work often enough to matter.
- Only if evidence justifies it, add a proportional mode:
  - trivial read-only work may use a lightweight readiness check
  - any transition to file reads, git inspection, planning, or editing must
    re-assert a valid startup baseline
  - stale or unavailable context remains fail-closed

**Acceptance.**

- No proportional mode ships without dogfood evidence showing real friction.
- Editing and multi-step planning still require a fresh or explicitly accepted
  team-context baseline.
- Tests prove escalation from lightweight mode to editing re-checks startup.

### G - Active-Ref Trust Labeling

Active refs bypass PR review. They are valuable as short-lived broadcast state,
but they must not look like reviewed team decisions.

**Work.**

- Mark active-ref-sourced constraints as `source_type: active_ref` and
  `review_state: unreviewed`.
- Default active-ref constraints to `authority: advisory` unless human-confirmed
  or corroborated.
- Render active-ref constraints as temporary and unreviewed in startup packets.

**Acceptance.**

- Active-ref-sourced items are visibly unreviewed in MCP and CLI startup
  packets.
- Active-ref constraints cannot hard-block without corroboration.
- Expired active refs cannot contribute authority.

### H - Lifecycle Controls: Off, Mute, And Retire

Jurati needs a graceful way to leave the path when it is not useful. There are
three different user intents, and the product should not collapse them:

- **Off:** stop Jurati from participating in this project or client setup.
- **Mute:** keep the knowledge repo intact, but stop surfacing a project,
  project key, repo, or signal source in normal startup context.
- **Retire/archive:** mark a completed project or context slice as no longer
  current so agents stop treating it as active guidance.

The AU0035L example is the product test: if a developer moves to another
project, Jurati should stop bringing AU0035L up in ordinary startup packets
unless the user explicitly asks for historical context.

**Work.**

- Add an explicit off switch:
  - Project-local disable should be one command, not hand-editing MCP JSON,
    `CLAUDE.md`, env vars, and permissions.
  - Global disable should be available for the current MCP client/user setup.
  - Re-enable should be equally clear and should preserve enough prior config to
    avoid a fresh onboarding flow when possible.
  - Disable must work without contacting the knowledge repo; it operates on
    local project/client config.
  - A disabled project should return or install a clear disabled state, not a
    stale/unavailable startup failure.
- Add mute/scope controls that affect retrieval without deleting source:
  - mute by `project`, repo slug, Jira project key, signal source, or tag
  - startup/context/search/query exclude muted scopes by default
  - explicit historical queries can opt in to muted scopes
  - muted scopes are visible in `status()`/diagnostics without noisy startup
    chatter
  - when possible, provider fetches skip muted signal scopes before reading
    external systems, not only after rendering cached results
- Add a reviewed retire/archive workflow for completed work:
  - bulk-expire active entries for a scope
  - mark durable project entries as retired or superseded
  - optionally add a short final project summary or archive pointer
  - stop treating retired project context as current planning guidance
  - use existing statuses where possible: product language may say "retired,"
    but implementation should prefer `expired` or `superseded` unless a new
    schema status proves necessary
- Keep emergency purge separate. If raw secrets or legally sensitive content
  must be removed from git history, that is a separate explicit destructive
  workflow with confirmation and documentation, not normal lifecycle cleanup.
- Update startup contract language so agents can say, in normal language, "This
  project context has been retired" or "Jurati is disabled for this project"
  without exposing repo plumbing.

**Acceptance.**

- A developer can disable Jurati for a project with one command and verify the
  disabled state with `status()` or `doctor`.
- Disabled state is distinguishable from stale/unavailable context and does not
  block local-only work.
- A developer can mute a project key such as `AU0035L` so it no longer appears
  in startup packets, default query results, or coordination signals.
- A completed project can be retired through a reviewable branch/PR that expires
  active entries and marks durable project context as no longer current.
- Muting and retiring are reversible or reviewable; neither rewrites git history
  by default.
- Startup/context behavior distinguishes disabled, muted, retired, and
  unavailable states.

### I - Audit Ledger And Compliance Claim Gate

Jurati should not overclaim audit readiness. Git review is useful, but it is not
the same as a tamper-evident compliance ledger. The current implementation has
real gaps:

- `materialize_write()` and `materialize_expire()` create ordinary unsigned
  commits.
- Expiry changes existing entry files in place by setting `status: expired`.
- L0 active context is stored on active refs that can be deleted.
- L1+ event files exist, but they are not append-only, hash-chained, signed, or
  complete for L0.
- `recorded_by` is a client slug and `source` is capture metadata; neither is
  authenticated identity.
- Branch protection and signed-commit requirements are host settings Jurati can
  assume or inspect, but does not configure or enforce today.

**Work.**

- Add an explicit compliance-claim matrix:
  - allowed today: reviewable git-backed context, PR-mediated durable changes,
    privacy-safe operation, content-safety gates
  - disallowed today: immutable ledger, tamper-evident ledger, SOC2-ready audit
    trail, authenticated authorship
  - allowed only after proof: signed/verifiable audit evidence and protected
    append-only history
- Add signed-commit support and verification:
  - configurable signing mode for Jurati-created commits
  - `doctor` checks for signing capability and host verification
  - `sync()` / validation can report unsigned or unverified source history when
    audit mode is enabled
- Replace "event trail" with an append-only audit event model before using it
  for compliance:
  - event IDs include previous-event hash or tree hash where appropriate
  - durable entries emit create, update/supersede, expire, and merge/activation
    evidence
  - L0 active refs either remain explicitly non-audit context or get a separate
    append-only active-event trail
  - expiry and retirement preserve an event record of the prior and new state
    without presenting the rewritten entry file as the only evidence
- Add host protection verification:
  - `doctor --audit` inspects branch protection/rulesets when the provider is
    GitHub and credentials allow it
  - startup/status can say "audit mode unavailable" when protected history is
    not verifiable
  - setup docs distinguish "Jurati configured this" from "your host must enforce
    this"
- Bind identity intentionally:
  - keep `recorded_by` and `source` as informational metadata unless an
    authenticated provider identity has been verified
  - add explicit fields or event metadata for verified actor identity only when
    it is cryptographically or provider-authenticated
  - never infer identity from a client-provided string in audit mode
- Update README, security docs, release docs, and slides to use only claims
  supported by the current code.

**Acceptance.**

- No public or release-gate docs call Jurati an immutable or tamper-evident
  ledger until the implementation proves it.
- `doctor` can distinguish ordinary git-backed reviewability from audit mode.
- Audit mode fails closed when commits are unsigned, host protection is missing
  or unverifiable, or actor identity is self-asserted.
- Event evidence is append-only and complete for the lifecycle surface it claims
  to cover.
- Tests cover unsigned commits, rewritten expiry, deleted active refs,
  self-asserted metadata, and missing branch protection as audit-mode blockers.

## Sequencing

1. Land the Workstream H0 escape hatch first: `disable`, `enable`, diagnostics,
   and disabled-state startup behavior. The real-team loop needs a clean way to
   turn Jurati off before it can safely test deeper behavior.
2. Land Workstream A as the first compiler-correctness patch. It changes the safety
   semantics of constraints and unblocks all later evidence.
3. Land Workstream E in parallel or immediately after A, because parity prevents
   the same trust model from splitting across transports.
4. Build Workstream B's calibration corpus before making compiler mode the
   public default.
5. Add Workstream C once there are real or dogfood outcomes worth reviewing.
6. Add Workstream D alongside B/C where scoped conflicts or corroboration become
   necessary.
7. Land the rest of Workstream H before or alongside the real-team loop, because
   testing should include leaving, muting, and retiring context, not only
   onboarding.
8. Land Workstream I before any SOC2/audit-ledger positioning. It can begin as
   documentation and diagnostics, but the stronger claims require signed,
   append-only, protected, identity-bound evidence.
9. Consider Workstream F only after the real-team loop shows strict startup is a
   repeated product problem.
10. Treat Workstream G as part of A if active refs are enabled in any compiler
   dogfood.

## First Build Slice

Start with lifecycle escape hatches, because they are user-visible, bounded, and
de-risk every later test.

Implementation status as of this sprint:

- **H0 shipped:** project-local `disable` / `enable`, disabled startup behavior,
  `doctor` / `status()` diagnostics, and disabled-state tests.
- **H1 shipped:** local muted-scope policy, `mute-scope` / `unmute-scope`,
  default filtering for startup/context/query/search/coordination/curation, and
  explicit `include_muted` read opt-ins where historical lookup is appropriate.
- **H2 shipped:** review-branch `retire-scope`, lifecycle report generation,
  status-based default retrieval quieting for expired/superseded entries, and
  tests proving retired scope entries stop being normal context without git
  history rewriting.
- **I0 shipped:** `doctor --audit` distinguishes ordinary git-backed
  reviewability from blocked immutable/tamper-evident/SOC2 audit-ledger claims.

**Slice H0 - Disable/Enable And Diagnostics**

- Add local project/client disabled state.
- Add `jurati disable` and `jurati enable` commands.
- Ensure disabled state does not require a knowledge repo fetch.
- Make `doctor` and `status()` report disabled as intentional, not broken.
- Update generated startup contracts so agents proceed local-only when Jurati is
  explicitly disabled.
- Add tests proving disabled startup is distinct from stale/unavailable startup.

**Slice H1 - Local Scope Mute**

- Add a local scope policy model for muted projects/repos/signal sources/tags.
- Add `jurati mute-scope` and `jurati unmute-scope`.
- Filter muted scopes in `context()`, `startup()`, `query()`, `search()`, and
  signal-provider fetch setup when possible.
- Add explicit historical opt-in for muted scopes.

**Slice H2 - Reviewed Retire Scope**

- Add a reviewable `retire-scope` plan that expires active entries and marks
  durable project context expired or superseded.
- Keep emergency purge out of this path.
- Add curation/status output that makes retired context quiet by default but
  discoverable when historical context is requested.

**Slice I0 - Audit Claim Diagnostics**

- Add a `doctor --audit` path that prints the allowed current claim and the
  blocked immutable/tamper-evident/SOC2 claims.
- Report unsigned commits, non-append-only events, deleted active refs,
  self-asserted identity, and unverifiable host protection as audit blockers.
- Keep ordinary `doctor` runtime readiness separate from audit-ledger readiness
  so normal team-context use is not mislabeled as broken.
- Make strict audit diagnostics fail until the audit evidence model exists.

## Success Criteria

The phase succeeds when:

- constraints carry source, review, corroboration, and authority metadata
- authority, verdict, and planning-action derivation are pure and exhaustively
  tested in `core/`
- unreviewed, derived, and single-signal constraints cannot hard-stop work
  without corroboration or human confirmation
- extraction precision/recall is measured against a stratified corpus, with
  missed-blocker rate as a compiler-default release gate
- verdict correctness is backed by reviewed outcome samples, not only planning
  equivalence against full context
- conflicting scoped directives are caught before they reach an agent
- MCP and CLI startup share one trustworthy packet contract
- developers can disable Jurati, mute irrelevant scopes, and retire completed
  project context without hand-editing config or rewriting git history
- compliance and SOC2-facing language is backed by actual signed,
  append-only/protected, identity-bound evidence, or is explicitly not claimed
- the privacy boundary remains stronger than a generic memory or telemetry
  product
