# Context Compiler Pivot

## Purpose

Jurati should not be a cheaper pile of context. It should be the layer that
turns reviewed team state into an agent-ready operating constraint.

The manifest-first work in PR #118 proves the first step: `context()` can stop
shipping full bodies by default while preserving broad coverage. That is useful,
but it is not the full product move. The larger pivot is to make Jurati a
context compiler:

- source artifacts remain reviewable and auditable
- derived indexes and caches do the retrieval work before the model sees data
- `context()` returns a compact planning packet, not a corpus
- `read()` and `read_many()` become explicit source-text expansion paths
- stale or unavailable derived state produces an explicit warning verdict

The model should see constraints, not corpora.

## Product Claim

Jurati compiles explicit team artifacts into the smallest safe planning surface
an AI coding agent needs before acting.

This is stronger than "shared memory" and narrower than "team knowledge base."
Jurati is not trying to make agents better at searching notes. It is trying to
make most searching unnecessary by producing the relevant constraints, blockers,
freshness state, and read-through handles up front.

## Relation To Token Efficiency

[Context Token Efficiency Plan](context-token-efficiency-plan.md) remains the
implementation plan for progressive token disclosure. This pivot document is
the product and architecture frame above it.

[Jurati Build Plan](build-plan.md) is the execution authority. When sequencing
differs, follow the build plan. This document owns the product rationale,
architecture contracts, and test philosophy for the compiler pivot.

Token efficiency is not the success metric by itself. The success metric is:

> The compiled context packet leads to the same planning decision as full
> context, with materially fewer tokens.

A tiny context packet that changes the agent's plan is a product failure. A
larger packet that preserves the right planning constraint is acceptable until
the compiler can compress it safely.

## Current State

PR #118 shipped the first useful slice:

- `context()` defaults to manifest entries rather than full entry bodies.
- `query()`, `search()`, and `list_entries()` have compact default read modes.
- `read_many()` exists as an explicit batch source-text expansion path.
- `context()` includes coverage accounting for returned entries and omitted
  details.
- manifest mode compacts coordination and curation payloads.

The review of that PR surfaced three hardening items that are now treated as
compiler-foundation work, not incidental polish. The first implementation slice
adds these guardrails:

- Frontmatter `summary` must be bounded. Authored summaries are source text too;
  they cannot bypass the compact-context budget.
- Compact curation must preserve the agent action. It may remove repeated prose,
  but it must not remove "do not rely," "verify before relying," or equivalent
  planning constraints.
- `read_many()` needs a cap or continuation behavior so one follow-up call
  cannot accidentally rehydrate the whole corpus.

The current branch adds the compiler foundation:

- typed freshness, constraint, verdict, and planning-action algebra in `core/`
- configurable freshness thresholds in `JuratiConfig`
- structural planning-equivalence tests for full versus compact context
- `context(mode="compiler")` as an explicit dogfood path for `compiler-v1`
- a derived `ContextSnapshot` boundary with visible-only entries, prebuilt BM25,
  lifecycle hygiene, cached coordination signals, and curation advisories
- explicit snapshot coverage for entries considered, configured signals
  considered, curation advisories considered, hidden restricted entries, build
  timestamp, and index generation
- `sync()` rebuilds the snapshot after loading the source ledger and refreshing
  configured signals when possible
- write-side index mutations rebuild the snapshot immediately, so compiler mode
  does not rely on stale in-memory read models after `record()`, `propose()`, or
  active `expire()`
- compiler mode reads the snapshot and renders constraints without provider
  refresh or full source bodies on the hot path
- a planning-equivalence fixture suite compares full-context payloads against
  compiler packets for clear proceed, verify-before-relying, revise, pause,
  stale-with-known-blocker, and context-unavailable cases
- the local MCP smoke now dogfoods `sync()` followed by
  `context(mode="compiler")` against a git-backed knowledge repo plus a
  fixture-backed blocking PR signal

This is still an explicit dogfood path, not yet the default startup contract.
The next boundary is a background refresh/read-model lifecycle that can keep
snapshots fresh without depending only on manual `sync()`.

## Architecture

The compiler keeps the token-efficiency principle and makes it broader:
preserve coverage, compress detail. Startup should preserve the full team
context surface while moving verbatim source text behind explicit read-through
tools.

Jurati should separate five layers.

| Layer | Role |
|-------|------|
| Source ledger | Git-reviewed Markdown, active refs, labeled signals, and context packs. |
| Ingestion plane | Fetches source artifacts through `sync()` or a refresh worker. |
| Derived intelligence plane | Rebuildable retrieval, graph, signal, and curation indexes. |
| Context compiler | Turns repo, goal, paths, source state, and freshness into a planning packet. |
| MCP facade | Exposes compact context, explicit read-through, validation, and write tools. |

The hot `context()` path should become mostly a local read from prepared derived
state. Provider refresh, source parsing, signal classification, curation scans,
and read-model rebuilds should happen during `sync()` or a clearly bounded
refresh step whenever possible.

The main implementation seam is the `ContextSnapshot`. The five-layer model
does not require five new modules. It requires one derived, rebuildable
snapshot boundary between sync-time work and context-time rendering. The first
snapshot slice now exists; the remaining architectural work is freshness
lifecycle, default-mode migration, and richer precompiled relevance records.

Sync-time responsibilities now include the first versions of:

- provider refresh
- curation scans
- visible-entry read model preparation
- BM25 index preparation
- snapshot coverage accounting

Sync-time responsibilities should continue moving toward:

- signal classification beyond request-local filtering
- entry manifest preparation
- freshness calculation as an attached snapshot fact

Context-time responsibilities should remain:

- applying `repo`, `goal`, and `paths` filters
- ordering already-derived records for the current task
- rendering the requested packet mode
- returning explicit freshness or availability verdicts

## Target Context Packet

The default startup response should evolve from "manifest of entries" toward a
compiled plan packet:

```json
{
  "context_schema": "compiler-v1",
  "verdict": "caution",
  "summary": "Auth work has one active handoff and one blocking PR signal.",
  "constraints": [
    {
      "kind": "coordination",
      "effect": "pause",
      "summary": "Wait for the auth API contract PR before changing token format.",
      "source_ref": "signal:github:org/api:pull:42"
    },
    {
      "kind": "curation",
      "effect": "verify_before_relying",
      "summary": "Token rotation decision is past review_after.",
      "entry_ref": "entry:decision-token-format"
    }
  ],
  "relevant_entries": [
    {
      "id": "handoff-auth-refactor",
      "title": "Auth refactor handoff",
      "type": "active",
      "summary": "Backend token rotation work is in progress.",
      "read_hint": "read(id='handoff-auth-refactor') for full body"
    }
  ],
  "coverage": {
    "entries_considered": 18,
    "signals_considered": 4,
    "entries_returned": 3,
    "bodies_omitted": 18,
    "signal_excerpts_omitted": 4
  },
  "freshness": {
    "status": "fresh",
    "last_success": "2026-05-27T14:04:07+00:00"
  }
}
```

The key fields are `verdict`, `constraints`, `coverage`, and `freshness`.
Entries are still present, but they are supporting read-through handles rather
than the main product surface.

## Verdicts

The compiler should make startup state explicit without collapsing different
kinds of risk into one axis.

Jurati has two status axes:

- Availability: `fresh`, `acceptable`, `stale`, or `unavailable`. This answers
  whether the context baseline can be trusted.
- Coordination: `clear`, `caution`, or `blocked`. This answers what known team
  context says about proceeding.

The public packet can expose a single `verdict` for simple agent handling, but
the derivation should preserve both axes internally.

Verdicts:

- `clear`: no known coordination or freshness blocker.
- `caution`: work can proceed, but the packet contains constraints or
  advisories.
- `blocked`: a coordination signal says the agent should not proceed with the
  requested work.
- `stale`: Jurati has usable cached context, but freshness is outside policy.
  Include any known constraints.
- `context_unavailable`: Jurati cannot provide a safe team-context baseline.

`stale` and `context_unavailable` must not look like successful empty context.
The agent should not proceed from local-only assumptions unless the developer
explicitly chooses to override the missing team context.

Minimum derivation rules:

```text
availability:
  if last_success is None or latest sync failed with no usable baseline:
    context_unavailable
  else if age >= hard_stale_threshold:
    stale
  else if age >= freshness_warning_threshold:
    acceptable
  else:
    fresh

coordination:
  if any constraint.effect == pause:
    blocked
  else if any constraint exists:
    caution
  else:
    clear

public verdict:
  if availability == context_unavailable:
    context_unavailable
  else if availability == stale:
    stale
  else:
    coordination
```

When `verdict` is `stale`, the packet must still include the known coordination
axis and constraints. A stale snapshot that contains a known blocker is more
useful than a stale snapshot that hides it.

Freshness thresholds must be configurable through `JuratiConfig`, not hardcoded
inside `core/`. Initial defaults should be conservative enough for PR and issue
signals, which can change faster than reviewed knowledge entries.

## Constraint And Decision Algebra

Constraints should be closed, typed values rather than arbitrary strings.

Initial constraint kinds:

- `coordination`
- `curation`
- `freshness`

Initial constraint effects:

- `pause`
- `revise`
- `verify_before_relying`
- `notice`

Each constraint should include:

- `kind`
- `effect`
- `summary`
- `source_ref` or `entry_ref`
- optional `read_hint`

The agent-facing decision must also be deterministic. Planning equivalence is
not "the LLM happened to make the same choice." It is structural equivalence:
the compact packet preserves the same availability axis, coordination axis,
blocking constraints, caution constraints, entry coverage, and read-through
handles as the full-context fixture.

Minimum planning actions:

| Packet state | Planning action |
|--------------|-----------------|
| `context_unavailable` | `stop_context_unavailable` |
| `stale` | `stop_or_request_refresh` unless explicitly overridden |
| coordination `blocked` | `pause` |
| `verify_before_relying` constraint | `read_or_verify_before_acting` |
| `revise` constraint | `revise_plan_before_acting` |
| constraints present without blockers | `proceed_with_caution` |
| no constraints | `proceed` |

This mapping should become a pure function in `core/` before compiler mode is
made default.

## Implementation Slices

### Slice 0: Patch The PR #118 Gaps

Goal: close the newly identified holes before building more compiler behavior.

Work:

- Add a max length for `Frontmatter.summary` and truncate defensively in
  manifest rendering.
- Preserve compact curation action fields such as `effect`,
  `planning_constraint`, or `next_step_ref`.
- Add a `read_many()` max ID cap with an explicit continuation/error response.
- Add regression tests for all three behaviors.

Acceptance:

- A large authored summary cannot push manifest context over the compact budget
  by itself.
- Default curation tells the agent what to do, not only that an advisory exists.
- Bulk read-through cannot accidentally undo startup token savings.

### Slice 1: Derived Context Snapshot

Goal: make `sync()` prepare the context data that `context()` consumes.

Work:

- Add a rebuildable `ContextSnapshot` or equivalent derived structure.
- Add typed `Constraint`, `FreshnessState`, and verdict/decision derivation
  helpers in `core/`.
- Populate it during `sync()` from the knowledge index, signal cache, curation
  scan, freshness metadata, and coverage counts.
- Store enough data to answer `context(repo, goal, paths)` without provider
  refresh or broad source formatting in the hot path.
- Keep the snapshot derived and rebuildable from source artifacts.

Acceptance:

- `context()` can render a manifest packet from prepared state.
- Verdict and planning-action derivation are pure and exhaustively tested.
- Provider fetches do not happen in the default `context()` path when a fresh
  snapshot exists.
- Tests prove snapshot rebuilds after `sync()` and after index mutations caused
  by write tools.
- Snapshot coverage preserves hidden restricted-entry counts even though the
  snapshot index is visible-only.

### Slice 2: Compiler Packet

Goal: return a planning packet, not just compact entries.

Work:

- Add `context_schema: compiler-v1` behind a feature flag or new mode.
- Introduce `verdict`, `constraints`, `freshness`, and richer `coverage`.
- Convert coordination guidance into constraints.
- Convert curation advisories into constraints.
- Keep read-through handles for entries and signals.

Acceptance:

- Blocking signals become `verdict: blocked` or `caution` with explicit
  constraints.
- Revalidation and expired-active advisories carry a clear agent action.
- Empty context and unavailable context are distinguishable.

### Slice 3: Planning Equivalence Tests

Goal: prove compression does not create coordination blindness.

Status: first fixture suite implemented for the major planning outcomes. This
is strong enough to catch obvious planning drift. The local MCP smoke also
exercises compiler mode after `sync()` against a git-backed repo and a blocking
fixture signal. Broader connected-agent dogfood is still needed before compiler
mode becomes the default.

Work:

- Build fixture pairs for full context and compiler packets.
- Define expected structural decisions for common cases:
  - proceed
  - proceed after reading one entry
  - verify before relying
  - pause because another artifact blocks the work
  - stop because context is unavailable
- Compare compact-packet axes, constraints, coverage, and read handles against
  full-context fixtures.
- Keep payload-size checks as regression guardrails, not the primary quality
  metric.

Acceptance:

- The compiler packet preserves structural planning state for the fixture suite.
- Any divergence is treated as a blocker before making compiler mode the public
  default.
- Compiler packets omit bodies while preserving explicit read-through handles
  for entries and any constraints that need source expansion.
- The smoke harness proves the compiler packet can preserve a blocking signal
  while omitting entry body detail and provider excerpts.

### Slice 4: Startup Contract Update

Goal: teach agents the new behavior without exposing Jurati mechanics to
developers.

Work:

- Update generated startup instructions to say: call `sync()`, then `context()`,
  then follow the packet verdict.
- Teach agents to call `read()` or `read_many()` only for entries they rely on
  directly.
- Keep developer-facing summaries about the work, not about Jurati plumbing.

Acceptance:

- Agents summarize constraints in normal language.
- Agents do not bulk-read every manifest entry.
- Connected-agent dogfood shows the same first planning move as full context.

## Privacy Boundary

The compiler must stay inside Jurati's existing privacy model:

- no raw query logging
- no read receipts
- no participation tracking
- no editor activity tracking
- no inferred absence or presence
- no unlabeled PR/comment/chat mining

Compiler decisions must be derived from explicit source artifacts: reviewed
entries, active refs when enabled by repo policy, labeled PR/Jira signals,
imported context packs, and repo-owned lifecycle metadata.

## Non-Goals

This pivot does not require:

- a hosted service
- centralized private team content
- user behavior analytics
- a dashboard of who read or installed anything
- runtime LLM summarization of source entries
- replacing git-reviewed Markdown as the source ledger

Those would change the trust model and should remain gated by separate privacy
design and dogfood evidence.

## Success Criteria

The pivot succeeds when:

- agents start from compiled team constraints instead of local-only assumptions
- default startup context is compact without dropping coverage silently
- source bodies and raw signal evidence are explicit read-through paths
- stale or unavailable context is visible as a verdict
- compact packets preserve the same planning decisions as full context
- the hot `context()` path is mostly a local derived-state read
- the privacy boundary remains stronger than a generic memory or telemetry
  product
