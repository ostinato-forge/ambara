# Security, Privacy, And Content Safety Gate

Jurati handles internal project context for agents. That makes trust the product,
not an accessory. If Jurati is secure, private, and content-safe, people may let
it sit in the path before agent work starts. If it fails that boundary even
slightly, more features do not matter.

This gate is the release and roadmap filter for all remaining work.

## Product Law

Every feature must preserve three properties:

- **Secure:** Jurati reads and writes only configured sources, keeps durable
  writes reviewable, avoids surprise network/storage behavior, and never asks a
  user to debug raw MCP internals during normal use.
- **Private:** Jurati is a broadcast system, not an observation system. It does
  not persist raw queries, create read receipts, infer presence, mine editor
  activity, scrape chats, or build participation dashboards.
- **Content-safe:** Jurati rejects secrets and unsafe content before
  publication, keeps restricted entries out of broad retrieval and generated
  surfaces, and never stores raw rejected secrets in audit records, logs, or
  user-facing messages.

A confusing or scary agent-terminal response is a trust failure. Entry IDs,
ref paths, branch plumbing, expiry chores, raw MCP JSON, and knowledge-repo
maintenance instructions are acceptable only when the user explicitly asks for
debugging details.

## Release Blockers

Treat any of these as release blockers:

- A broad read path exposes restricted entries, restricted backlinks, or
  restricted source text.
- A write, import, audit, or error path stores raw secrets, raw rejected
  content, private notes, or personal scratch context.
- A default setup enables active context without explicit repo policy.
- Active context accepts restricted content or survives past the configured TTL.
- A provider reads unconfigured repos, unlabeled PRs, chats, editor activity,
  read activity, or absence signals.
- A metric records raw queries, caller identity, entry-level reads, or
  per-person participation.
- A user-facing agent response exposes Jurati internals during normal work.
- A hosted, dashboard, IDE, or fleet-install surface centralizes internal team
  content before a privacy design and field-test evidence exist.

## Required Evidence

For release confidence, the repo must have repeatable evidence for these
invariants:

- Default installs keep active refs disabled.
- Active refs, when enabled by repo policy, are explicit broadcast only, have a
  bounded TTL, reject restricted content, and disappear from broad retrieval
  after expiry.
- `context()`, `query()`, `search()`, static HTML, and read-model queries all
  exclude restricted content.
- Import dry-runs reject secrets, private/scratch paths, unsupported embeds, and
  unsafe context before creating a branch.
- Write safety rejects secret-like content and reports policy decisions without
  echoing the secret.
- Labeled PR and issue providers read only configured projects and explicit
  labels.
- Field tests prove the agent starts with `sync()` and `context()` and does not
  leak implementation details in normal terminal output.

## Roadmap Reorder

Evaluate every remaining roadmap item through the trust gate:

| Item | Trust posture | Ordering decision |
|------|---------------|-------------------|
| #90 Agent behavior gate | Highest priority because it proves real agent behavior | Continue, but score evidence on trust failures first |
| #93 Active coordination | High privacy risk because it is the L0 broadcast path | Build only with opt-in, TTL, restricted-content rejection, expiry evidence, and quiet confirmations |
| #96 Content safety and write auditability | High priority because it protects the publication path | Move ahead of metrics, hosted, dashboard, and IDE work |
| #92 Knowledge bootstrap | Useful only if imports reject unsafe source material | Continue with dry-run rejection evidence and allowlisted sources |
| #94 Curation | Allowed when based only on repo state and explicit metadata | Continue conservatively; no reads, presence, or editor activity |
| #95 Metrics | High privacy risk | Blocked until a standalone privacy design proves aggregate, identity-free, disableable metrics |
| #97 Static read surface | Allowed only as static, local/client-side output | Block hosted or service-backed variants until a privacy design exists |
| #98 Packaging and fleet installation | Allowed when install smoke proves no private data leaves the machine | Defer hosted planning; prefer pinned local/container installs |
| #99 IDE and agent-client surfaces | High privacy risk because file context can become editor telemetry | Block until file relevance is local, explicit, and read-only by default |
| #115 Graded entries | Trust-sensitive because false confidence can be harmful | Pause until grading metadata has a schema, privacy, and content-safety design |

## Design Rules

- Default-deny any new observation surface.
- Prefer local, derived, rebuildable indexes over hosted state.
- Make durable publication reviewable through git.
- Keep write auditability separate from read privacy.
- Store policy outcomes, not raw unsafe content.
- Use explicit allowlists for imports and providers.
- Keep active context short-lived, internal, and repo-policy controlled.
- Treat "the agent made the user nervous" as a failed acceptance test.

If a future feature needs an exception, it needs a written privacy design,
field-test evidence, and focused tests before implementation.
