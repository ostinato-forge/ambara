# Context Token Efficiency Plan

## Purpose

Jurati's startup contract is intentionally strict: agents should call `sync()`
and `context()` before local repo exploration. That contract prevents the
coordination failures Jurati exists to catch.

The problem is not that `context()` returns too much team awareness. The problem
is that it returns too much verbatim material up front. This plan reduces token
usage by changing the representation of context, not by hiding team context.

The target model is manifest-first context:

- `context()` gives the agent a complete compact map of relevant team context.
- Full entry bodies, long evidence excerpts, repeated policy text, and raw
  lifecycle details move behind explicit read-through calls.
- Under token pressure, Jurati compresses item detail before it omits item
  coverage.
- When anything is summarized, compacted, or omitted because of a hard budget,
  the response says so explicitly.

## Non-Goals

Do not save tokens by making Jurati less aware of team state.

This plan does not pursue:

- returning only the top few entries when more team context is in scope
- hiding active work, decisions, workflows, project state, curation, or
  coordination signals just because they are lower ranked
- making labeled PR or Jira coordination opt-in in a way that makes normal
  startup blind to blockers
- relying on raw local git state as a substitute for Jurati context
- logging queries, reads, presence, or participation to personalize context

Restricted entries still remain outside broad retrieval, search, context,
ranking, static HTML, and derived read models.

## Design Principle

Preserve coverage. Compress detail.

Jurati should distinguish three layers:

| Layer | Startup behavior |
|-------|------------------|
| Team context coverage | Preserve. Return a compact manifest of what exists. |
| Semantic planning detail | Preserve enough to act: title, type, project, status, summary, freshness, effect, and relevance reason. |
| Verbatim source content | Lazy-load through `read()` or an explicit full-detail mode. |

The startup response should answer, "What team context exists that could affect
this work?" It should not prepay the full token cost of every body and evidence
excerpt.

## Current Cost Drivers

The current read path spends tokens in predictable places:

- entry formatting includes full `body` text for broad context responses
- goal ranking changes ordering but still returns full entry payloads
- repo-matched entries can be appended after ranking with full bodies
- coordination guidance can include full evidence blocks and signal body
  excerpts
- curation advisories include repeated instructions and detailed evidence
- stable policy and privacy text is repeated in ordinary startup payloads
- `query()` and `list_entries()` use broad entry formatting rather than compact
  manifest formatting

The highest-value change is to make broad retrieval compact by default while
keeping `read()` as the authoritative full-body path.

## Target Contract

### `context()` Default

Default startup context should return a full manifest with compact records:

```json
{
  "context_schema": "manifest-v1",
  "mode": "manifest",
  "active": [
    {
      "id": "auth-refactor-handoff",
      "title": "Auth refactor handoff",
      "type": "active",
      "status": "active",
      "projects": ["api-service"],
      "tags": ["auth"],
      "updated_at": "2026-05-27T12:00:00+00:00",
      "summary": "Backend token rotation work is in progress; frontend waits on the API contract.",
      "relevance": {
        "score": 3.42,
        "reasons": ["project-match", "path-match"]
      },
      "read_hint": "read(id='auth-refactor-handoff') for full body"
    }
  ],
  "recent": [],
  "coordination": {
    "has_blocking_signals": true,
    "signals": [
      {
        "effect": "pause",
        "urgency": "high",
        "summary": "Auth API work should land before token format changes.",
        "source": "github-pr",
        "evidence_count": 1,
        "read_hint": "context(mode='full') for full evidence"
      }
    ]
  },
  "coverage": {
    "active_returned": 1,
    "recent_returned": 0,
    "coordination_signals_returned": 1,
    "entry_bodies_omitted": 1,
    "signal_excerpts_omitted": 1,
    "hidden_restricted_entries": 0
  }
}
```

### Detail Modes

`context()` uses a single `mode` parameter that controls the entire response
shape — entries, signals, and curation together:

| Mode | Purpose | Behavior |
|------|---------|----------|
| `manifest` | Default startup | compact summaries, no bodies, compact signals/curation |
| `standard` | Startup plus excerpts | short body excerpts, compact signals/curation |
| `full` | Debugging and compatibility | current full-entry behavior, full signal evidence |

`query()`, `search()`, and `list_entries()` use `body_mode` to control entry
detail independently, since they have no coordination or curation sections:

- `none` (default): no bodies, compact manifests
- `excerpt`: short excerpt with read-through hint
- `full`: full body, only when explicitly requested

Note: `search()` already returns a compact format (id, title, type, relevance,
reasons, 200-char snippet) so it needs the least work. `query()` is currently
the worst offender — its exact-match path wraps `_format_entry()` (full body)
plus match metadata.

`read()` and `read_many()` remain the explicit full-body tools.

### Summary Source

Each manifest entry needs a concise planning summary. The canonical location
is an optional `summary` field in entry frontmatter — author-controlled,
reviewable, and versionable.

Derivation order:

1. Use the frontmatter `summary` field when present.
2. Fall back to the first non-empty, non-heading text block in the body,
   truncated to ~200 characters. Skip markdown headings (`#`), blank lines,
   and code fences when scanning for the first usable paragraph.
3. If no usable summary exists, return title, type, projects, tags, and
   `summary_missing: true` with a read hint.

This avoids runtime LLM summarization and keeps the source of truth
reviewable. Over time, `validate` and `doctor` can surface entries that lack
summaries to nudge authors toward writing them.

## Compression Rules

Compression should be deterministic and explainable.

1. Return all in-scope active entries as compact manifests unless they are
   expired, restricted, or outside the requested access mode.
2. Return all in-scope recent durable entries as compact manifests within the
   configured recency and status rules.
3. Rank entries to order attention, not to silently remove coverage.
4. If a hard token or character budget is exceeded, reduce per-item detail in
   tiers before dropping items:
   - Tier 1: title, type, status, projects, summary, relevance reason.
   - Tier 2: title, type, status, projects, short summary.
   - Tier 3: title, type, projects, updated time, read hint.
   - Tier 4: category counts plus an explicit continuation hint.
5. Blocking coordination stays higher detail than non-blocking coordination.
6. Lifecycle and privacy instructions should use stable short references rather
   than repeated paragraphs.
7. Any omitted details must be counted in `coverage`.

The only acceptable silent exclusions are existing safety exclusions:
restricted content, blocked content-policy entries, expired entries when
`include_expired=false`, and entries outside the requested access mode.

## Coordination Signals

Startup should keep coordination coverage while reducing raw evidence cost.

Default signal rendering should include:

- effect: `continue`, `reuse`, `revise`, `pause`, `handoff`, or `clarify`
- urgency
- short summary
- source kind
- configured source repo or project
- evidence count
- matched path count or small safe path sample
- whether full evidence is available

Default signal rendering should not include:

- full signal body excerpts
- repeated untrusted-text warnings
- full changed-path lists when they are long
- repeated privacy-boundary text

Compact signal summaries include enough context for planning decisions. Full
evidence remains available through `context(mode="full")`. A dedicated
signal-read tool is not needed — the planning/debugging split maps cleanly onto
`manifest`/`full` mode.

## Curation Advisories

Curation should stay visible during normal startup, but should use compact
facts by default.

Default curation rendering should include:

- total advisory count
- advisory counts by kind
- compact advisory manifests for every in-scope advisory where feasible
- affected entry id and title
- suggested action
- short reason
- read-through hint for the affected entry or full advisory evidence

Default curation rendering should avoid repeating the same long agent
instruction per advisory. Put stable instructions behind `policy_ref` or a
single top-level sentence.

## Query And List Behavior

The same manifest-first model should apply beyond `context()`.

- `query()` should return compact matched entries by default
  (`body_mode="none"`). When `query()` falls back to `search()` on no exact
  match, the compact default applies through the fallback — search results
  use the same `body_mode` that was requested.
- `search()` should keep short snippets but make them optional via
  `body_mode`.
- `list_entries()` should never return full bodies by default.
- `read()` remains the explicit full-body tool.
- `read_many(ids=[...])` supports efficient batch read-through after manifest
  inspection (see Phase 2).

This makes the startup contract cheap without teaching agents a special one-off
behavior.

## Token Budget Instrumentation

Payload-budget tests guard the compact default. The ~4k approximate token
target is a regression guardrail, not a runtime enforcement mechanism — small
entry sets should not pad to the budget; large entry sets should trigger
compression tiers before hitting the cap.

Budget tests should fail when a future change accidentally reintroduces full
body payloads into startup, and when compact mode silently drops entry
coverage relative to full mode. See Phase 1 for specifics.

## Execution Order

### Phase 1: Measure And Lock The Guardrail

Status: planned.

Goal: prove the current cost profile and prevent regressions.

Work:

- Add a test fixture with active entries, recent decisions, workflows,
  coordination signals, curation advisories, restricted entries, and long
  bodies.
- Add a deterministic payload-size helper: `ceil(len(json_payload) / 4)` as
  approximate token cost.
- Add payload-size tests for current `context()` fixtures: measure full mode
  baseline.
- Record baseline compact versus full expected fields.
- Add coverage assertions so compact mode cannot pass by dropping entries.
- Add tests that restricted and blocked content remain excluded.

Acceptance:

- Tests can compare full and compact context coverage.
- Tests fail if compact startup includes full entry bodies.
- Tests fail if compact startup silently drops in-scope active, recent,
  coordination, or curation records.

### Phase 2: Add Manifest Entry Formatting

Status: planned.

Goal: create a compact read-side entry format without changing `read()`.

This phase implements `manifest` and `full` modes. `standard` mode (body
excerpts) is deferred until manifest mode is validated in Phase 6 — it adds
complexity for a middle ground that may not be needed.

Work:

- Add optional `summary: str | None = None` field to `Frontmatter` schema in
  `core/schema.py`. Backward-compatible: existing entries parse with
  `summary=None` and fall through to body-derived summary.
- Add `mode: str = "manifest"` parameter to `context()` tool handler.
- Add `body_mode: str = "none"` parameter to `query()`, `search()`, and
  `list_entries()` tool handlers.
- Add `_format_entry_manifest(...)` alongside the existing full formatter in
  `server_read.py`.
- Add summary derivation: frontmatter `summary` → first body paragraph →
  `summary_missing: true`.
- Add `read_hint` to manifest entries consistently.
- Add relevance metadata when ranking is available.
- Wire compact formatting into `context()`, `query()`, `search()`, and
  `list_entries()`.
- Add `read_many(ids=[...])` tool for efficient batch read-through after
  manifest inspection. Build entry graph once, not per-entry.

Acceptance:

- `context()` defaults to manifest entries with no `body`.
- `context(mode="full")` returns current full-entry behavior.
- `read(id=...)` still returns the full body and links.
- `read_many(ids=[...])` returns full bodies in a single round-trip.
- `read_many()` respects restricted-entry exclusion (same as `read()`).
- Existing privacy and restricted-content tests still pass.

### Phase 3: Preserve Coverage With Explicit Accounting

Status: planned.

Goal: make compactness auditable.

Work:

- Add top-level `coverage` metadata to `context()`.
- Count returned entries by category.
- Count omitted bodies, omitted signal excerpts, and omitted curation evidence.
- Count safety exclusions separately where safe to expose.
- Add `mode`, `context_schema`, and optional `budget` metadata.

Acceptance:

- Agents can tell when they received all manifests but not all source text.
- Agents can tell when a hard budget forced continuation.
- No broad response implies completeness of bodies or evidence when those were
  intentionally withheld.

### Phase 4: Compact Coordination And Curation

Status: planned.

Goal: keep blockers and lifecycle warnings visible without shipping raw
evidence by default.

Work:

- Add signal summary mode as the default.
- Keep blocking and high-urgency signals prominent.
- Move long evidence, excerpts, and repeated instructions behind full mode.
- Add compact curation manifests and shared top-level guidance.
- Keep configured-source and privacy boundaries as short stable references.

Acceptance:

- Startup still surfaces blockers and advisories.
- Full evidence remains reachable.
- Default signal and curation payloads are bounded, sanitized, and compact.

### Phase 5: Update Startup Instructions

Status: planned.

Goal: teach agents the cheaper contract without weakening the startup
requirement.

Backward compatibility: manifest entries are strictly a subset of full
entries. Agents running the old CLAUDE.md contract will receive manifests
instead of full bodies and continue to function — they get less data but
correct data. This means Phase 2 can ship before Phase 5 without breaking
existing agents. Phase 5 improves agent behavior (teaching `read()` follow-up)
rather than fixing breakage.

Work:

- Update generated `CLAUDE.md` text to call manifest startup context.
- Tell agents to call `read(id=...)` or `read_many(ids=[...])` only for
  entries they rely on directly.
- Model the "scan manifests, read what matters" behavior explicitly in the
  startup instructions.
- Keep the hard precondition: no local exploration before `sync()` and
  `context()`.
- Keep developer-facing summaries work-focused and free of Jurati internals.

Acceptance:

- `jurati install-claude-md` produces the manifest-first startup contract.
- `doctor --check-startup` still validates the read path.
- Existing startup-order dogfood evidence remains applicable.

### Phase 6: Dogfood Against Real Planning Tasks

Status: planned. Hard gate — manifest mode should not ship as the public
default until this phase passes.

Goal: prove token savings do not create coordination blindness.

Failure definition: the agent made a planning decision that would have changed
if it had read the full body of an entry it received as a manifest. This is
the key metric. Token savings that degrade planning quality are not savings.

Work:

- Run the existing single-repo and multi-repo dogfood harnesses in compact
  mode.
- Compare agent planning output against full mode on identical entry sets and
  planning tasks.
- Confirm the same blockers, decisions, workflows, and active handoffs are
  noticed.
- Record any cases where the agent should have called `read()` and did not.
- Diff planning decisions between modes, not just blocker detection.

Acceptance:

- Compact mode catches the same coordination constraints as full mode.
- Agents use `read()` or `read_many()` for entries they rely on, rather than
  reading everything up front.
- No planning decision diverges between manifest and full mode.
- Token usage falls substantially without reducing team-context coverage.

## Resolved Design Questions

- **`summary` location**: frontmatter, as an optional field. Author-controlled,
  reviewable, versionable. Entries without summaries fall through to body
  truncation and expose `summary_missing: true`.
- **Signal evidence retrieval**: `context(mode="full")` returns full signal
  evidence. No dedicated `read_signal()` tool — compact signals include enough
  planning context (effect, urgency, summary, source, evidence count). Full
  evidence is a debugging need, not a planning need.
- **Startup budget**: ~4k approximate tokens as a test regression guardrail,
  not a runtime enforcement mechanism.
- **Schema versioning**: yes. Responses include `context_schema: "manifest-v1"`
  so clients can detect the format. Future format changes are not silent
  breakage.

## Open Design Questions

- What character budget should `standard` mode (body excerpts) use — 200, 400,
  or adaptive based on entry count? Deferred until `standard` mode is
  implemented post-Phase 6.
- Should `read_many()` support a max-results cap to prevent accidental bulk
  reads, or trust the caller?

## Success Criteria

The work is successful when:

- agents still begin from the full team situation, not local-only assumptions
- startup context no longer includes full entry bodies by default
- blockers, active handoffs, decisions, workflows, project state, and curation
  advisories remain visible in compact form
- the response explicitly says what was compacted or withheld
- `read()` and `read_many()` are the normal source-text read-through paths
- tests prove compact mode preserves coverage relative to full mode
- dogfood runs show the same planning guidance with materially lower payload
  size
