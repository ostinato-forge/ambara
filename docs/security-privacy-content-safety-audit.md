# Security, Privacy, And Content Safety Audit

Audit date: 2026-05-26.

Jurati's trust boundary is the product boundary. This audit scores the current
implementation against [Security, Privacy, And Content Safety Gate](security-privacy-content-safety.md)
and names the next tightening work.

## Summary

Current status: **not release-blocked on architecture, but still hardening
required before first release**.

The strongest controls already exist in the core read and write paths:
restricted entries are excluded from broad retrieval, active context is off by
default, durable writes use reviewable git paths, and normal reads do not create
receipts or participation signals. The highest remaining risk is consistency:
every path that can introduce, derive, or display internal context must pass the
same security, privacy, and content-safety checks.

## Current Controls

| Surface | Current control | Audit result |
|---------|-----------------|--------------|
| Broad retrieval | `context()`, `query()`, `search()`, static HTML, and read-model tests exclude restricted content | Strong, keep in adversarial smoke |
| Direct read | `read(id=...)` hides restricted entries and restricted backlinks | Strong |
| Active context | Package default is disabled; repo policy and TTL flow into MCP config; TTL cap enforced | Good, needs gate-level evidence for opt-in and expiry |
| Durable writes | `record()` and `propose()` route lasting entries through branch/PR review | Strong |
| Write content policy | Secret-like content blocks, PII/personnel/confidential content requires review, warning rules label risky phrasing | Good baseline, scanner integration remains future hardening |
| Imports | Context packs, Markdown, and note-export imports dry-run before writing and reject secrets, private paths, restricted entries, unsupported embeds, bad links, and unsafe paths | Improved by this slice: imports now also reject default content-policy block/review matches before creating branches |
| Provider reads | GitHub and Jira signal providers use configured repos/projects and labels; GitHub token errors are sanitized | Good, needs periodic adversarial fixture coverage as providers expand |
| Curation | Uses repo state, explicit metadata, and labeled signals; privacy boundary states no reads, presence, editor activity, or participation data | Good, keep matching conservative |
| User-facing write receipts | Responses include safe `developer_confirmation` and agent guidance against exposing internals | Good, but raw tool payload still contains debug fields for agents |

## Tightening Needed

### P0: Keep Unsafe Imports Out Of Git

Before this audit, import planning used the older secret scanner but not the
same content policy used by normal writes. That meant PII, personnel language,
or confidentiality terms could reach a review branch during an import instead
of being rejected during dry-run.

Action taken in this slice:

- Context-pack, Markdown, and note-export imports now evaluate source content with
  the default write content policy.
- `block` and `require_review` matches reject the import item before branch
  creation.
- Reject reasons include rule IDs only, not raw matched content.
- The adversarial smoke now owns this regression.

### P0: Prove Active Context As Explicit Broadcast

Active refs are the highest privacy-risk feature because they are designed to
share fresh handoff context quickly.

Action taken in follow-up slice:

- `scripts/pre-release-active-context-privacy-smoke.sh` now proves active
  context is disabled by default, requires repo-owned policy, uses bounded TTL,
  rejects content requiring review, and disappears from broad context after
  expiry or restriction.
- Keep developer-facing confirmations quiet: no entry IDs, ref paths, branch
  names, expiry mechanics, or knowledge-repo chores.

### P0: Treat Agent-Terminal Scare As A Test Failure

The write receipts already give agents safe confirmation text, but tool payloads
still include debug fields such as IDs, branches, PR numbers, and refs. Those
are useful to the agent, but harmful if repeated to the user.

Required next build:

- Expand connected-agent dogfood scoring to fail on scary terminal output, not
  just tool order.
- Add fixture prompts that ask normal user questions and assert the expected
  answer shape contains no Jurati internals.

### P1: Strengthen Scanner Coverage

The current content policy is deterministic and offline, which is good for a
baseline. It is still regex-based and should not be sold as enterprise-grade
data loss prevention.

Required follow-up:

- Add a pluggable scanner adapter behind explicit policy, starting with a local
  Gitleaks or TruffleHog-compatible path.
- Store policy outcomes and scanner versions, not raw rejected content.
- Keep this on the write/import path only; do not add read tracking.

### P1: Hold Metrics, IDE, Hosted, And Dashboards

Metrics, IDE surfaces, hosted services, and dashboards are trust-risk
multipliers. None should outrank the P0 work above.

Required rule:

- Do not build #95, hosted variants of #97/#98, or #99 until they have a
  standalone privacy design and tests proving no raw queries, caller identity,
  read receipts, editor telemetry, or per-person participation records.

## Next Build Update

The connected-agent active-context privacy evidence landed on 2026-05-29 and is
recorded in [Team Loop Test Gate Runs](dogfood-gate-runs.md). The run enabled
active refs only through repo-owned project policy, verified a seeded active
handoff appeared in startup context, required Claude Code to call `startup`
before `record`, and scored the visible reply for terminal trust.

The first attempt caught a real instruction bug: the agent pre-announced the
startup/tool workflow. That now fails the gate. The compact Claude template was
updated so startup and write tools run silently and the first visible reply is
the final work-focused answer.

The import content-policy tightening from this audit is already included in the
current slice because it closes a concrete path where internal data could enter
the knowledge repo before review.
