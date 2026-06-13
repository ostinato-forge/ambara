# ADR 0003: Remember core and source promote (v1)

- Status: accepted
- Date: 2026-06-13

## Context

Ambara could already turn a labeled commit into durable knowledge (commit
capture), but a labeled pull request, issue, or page only surfaced as an
ephemeral source input — it could never become durable team memory. Closing
that "remember loop" added a second caller of the same durable-write decision
(content-policy gate, secret/review escalation, contradiction detection,
reject/redact reasons, honest receipt). Duplicating that logic across commit
capture and source promote would let the two drift on exactly the
security-sensitive path that must not.

## Decision

Ambara freezes a single decision contract in `ambara.core.remember` and builds
both callers on it:

- `RememberCandidate` is the normalized input both adapters construct: `kind`
  (`capture` | `promote`), `entry_id`, `title`, `body`, `entry_type`,
  `requested_level`, `branch_prefix`, optional `source_meta` (git provenance,
  capture path) or `provenance` (source-input provenance, promote path),
  `projects`, `tags`, and `secrets_present`.
- `plan_remember(candidate, *, index_entries, content_policy, now, caller)` is
  pure and deterministic: same inputs produce the same `RememberPlan`. It runs
  the content-policy gate, escalates to L2 on review-required or
  secrets-present, detects contradictions over the passed index, appends the
  provenance footer, and delegates entry construction to `core.changes`. It
  performs no I/O.
- `RememberPlan` carries `action` (`create` | `reject`), the `WriteIntent`,
  the final `level`, `requires_pr`, `reject_reasons`, `redaction_rule_ids`,
  `contradiction_ids`, and an honest `receipt`.
- Promote branch naming is `ambara/promote/<entry-id>` (via the candidate's
  `branch_prefix`). Promote opens a review branch and never opens a pull
  request — a PR already exists where the decision was made; remembering does
  not re-review.
- Source-input provenance is recorded in the entry body as a visible footer
  frozen at `<!-- ambara:provenance:v1 -->`, linking `provider/external_id` to
  the source URL with the capture date. This needs no `schema_version` bump; a
  first-class frontmatter provenance field is a later slice.
- `git.remember.materialize_remember(repo_path, plan, *, main_branch)` performs
  the idempotent branch/commit/push for a create plan. Commit capture keeps its
  own thin materialize for test parity and is refactored onto `plan_remember`
  with byte-for-byte behavior preserved.
- Surfaces: the agent-facing `promote` MCP tool is primary; the
  `ambara sources promote` CLI is the proof/dev mirror. Both resolve an
  artifact by id, call `plan_source_promotion`, default to dry-run, and share
  one receipt shape so they cannot drift.

## Consequences

- The security-sensitive durable-write decision exists once and is exercised by
  both capture and promote; a change to the gate or escalation rules applies to
  both paths at once.
- Promoted knowledge is ambient context: remembered, provenance-linked, and
  distilled — not a second review of the source artifact.
- The frozen `RememberCandidate` / `plan_remember` / `RememberPlan` field names,
  the `ambara/promote/<entry-id>` branch shape, and the
  `<!-- ambara:provenance:v1 -->` footer are stable contracts. A future
  schema-v3 provenance field extends, rather than breaks, this footer.
