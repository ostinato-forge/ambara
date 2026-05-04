# Jurati Ambient Coordination Design Spec

**Date:** 2026-05-04
**Status:** Draft
**Author:** Edgar Parenti
**Companion to:** `2026-05-02-jurati-design.md` and `2026-05-03-jurati-dx-design.md`

## Product Goal

Jurati is a human+AI collaboration operating system for distributed engineering
teams. Its job is to keep humans and agents collectively oriented when work is
moving too fast for recurring meetings, static docs, or manual boards to stay
current.

The developer-facing workflow must be almost invisible:

1. The team configures the Jurati MCP server once.
2. A developer labels an important PR with `jurati`.
3. Agents automatically receive the relevant coordination context while
   planning and working.

No regular developer command is required. No dashboard is required. No one has
to ask Jurati what happened. From the developer's perspective, the recurring
gesture is just the PR label.

## Problem

Jurati V1 gives agents a shared knowledge repo and MCP tools for search,
context, record, propose, and validation. The DX extension adds capture from
`jurati:` commit messages. Those features improve shared memory, but they still
do not fully solve the high-speed coordination problem:

- 19 human+agent pairs can work in parallel and ship a minor version in a day.
- Normal ceremonies assume humans pause, summarize, compare notes, and update a
  board or doc.
- Agents start sessions cold unless the MCP context explicitly tells them what
  other teams recently changed.
- The most natural human signal already exists in GitHub: a developer can label
  a PR `jurati` when the team should know about it.

The product leap is to treat that PR label as an explicit coordination broadcast
and turn it into ambient agent guidance.

## Design Principle

Jurati must be background magic for developers, not hidden surveillance.

"Background" means the developer does not type Jurati commands during normal
work. "Not surveillance" means Jurati only uses explicit team-broadcast signals:
PRs carrying the configured `jurati` label in configured repositories.

## Relationship To Existing Specs

This spec extends, but does not replace, the existing contracts.

- **V1 design:** The knowledge repo remains the durable source of truth for
  principles, decisions, workflows, project state, and active entries.
- **DX design:** Commit-message capture remains a write path for knowledge
  entries. PR-label coordination is a read/context signal path, not a replacement
  for `jurati:` capture.
- **Auth resolver:** Provider access must follow the same non-prompting,
  privacy-safe auth principles. Jurati must not open browser auth flows or
  interactive prompts while serving MCP context.
- **Privacy:** All V1 privacy constraints remain in force. This spec adds
  PR-label-specific constraints in the privacy and security boundary below.

Where there is tension, the stricter privacy rule wins.

## Product Contract

### Human Contract

Humans do only this during normal work:

- label a PR with `jurati` when other teams or agents should know about it
- optionally add ordinary PR title/body text that explains why the work matters
- optionally remove the label if the PR should stop being broadcast through
  Jurati

Humans do not need to:

- run `jurati context`
- run `jurati sync`
- open a Jurati dashboard
- copy PR summaries into a separate doc
- attend a recurring sync meeting just to transfer the same information

### Agent Contract

Agents use Jurati through MCP as part of planning:

- call `context(repo?, goal?, paths?)` before making or revising a plan
- treat returned coordination guidance as planning evidence
- cite the labeled PR evidence when it changes the plan
- avoid duplicating work if a labeled PR already covers the same target
- revise or pause when the labeled PR changes ownership, constraints, or
  sequencing

This is still an agent action, not literal server-side mind reading. Jurati can
make the context available, but the MCP client or repo instructions must cause
the agent to ask for context at the right moments.

### MCP Client Contract

Repo onboarding should make the agent call Jurati automatically. Supported
configuration paths:

- MCP server config in the user's client settings
- repo-owned agent instructions, such as `CLAUDE.md`, that tell the agent to
  call Jurati before planning
- optional repo config that supplies the knowledge repo and PR signal sources

The fallback is graceful: if the MCP server is not configured, the agent works as
usual. The developer should not see recurring failures in normal development
flows.

## User Stories

### Avoid Duplicate Work

Tony labels PR `#418` with `jurati` after implementing the auth-token resolver
last week. Today an agent starts a related auth task. The agent calls
`context(repo="api", paths=["src/auth/token.py"])` and receives:

- Tony already merged a labeled PR touching this target.
- Reuse or inspect that work before creating a new resolver.
- If new work is still needed, plan it as an extension, not a duplicate.

### Change The Plan

A developer labels a PR that changes the release workflow. An agent planning a
release automation change receives the workflow PR as context and changes the
implementation sequence.

### Pause Overlapping Work

An agent is editing `src/jurati/server.py`. A human labels a PR on the same file
with `jurati` and leaves a PR body that says the MCP context contract is being
changed. Jurati returns guidance to pause edits to that target and account for
the labeled PR before continuing.

### Continue Parallel Work

Two teams label PRs in the same repo, but the changed areas do not overlap. The
agent receives a low-urgency signal that the work is parallel and continues.

## Signal Model

### PRSignal

A PR signal is a normalized read model for one explicitly labeled pull request.

```python
@dataclass(frozen=True)
class PRSignal:
    signal_id: str
    provider: Literal["github"]
    repo: str
    number: int
    url: str
    title: str
    body_excerpt: str | None
    author: str
    state: Literal["open", "merged", "closed"]
    labels: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None
    changed_paths: tuple[str, ...]
    target_areas: tuple[str, ...]
```

Rules:

- `signal_id` is stable: `{provider}:{repo}:pull:{number}`.
- `repo` is the configured source repository slug, not the local checkout path.
- `body_excerpt` is bounded and sanitized; no unbounded PR bodies enter MCP
  context.
- `changed_paths` contains file paths only, not raw diff hunks.
- `target_areas` is derived from changed paths using deterministic rules.

### CoordinationGuidance

Jurati turns PR signals into agent-facing guidance.

```python
@dataclass(frozen=True)
class CoordinationGuidance:
    effect: Literal["continue", "reuse", "revise", "pause", "handoff", "clarify"]
    urgency: Literal["quiet", "info", "notice", "warning", "critical"]
    summary: str
    instruction: str
    confidence: int
    evidence: tuple[PRSignalEvidence, ...]
```

`effect` is the planning contract:

| Effect | Agent behavior |
|---|---|
| `continue` | Work appears parallel or unrelated. Continue normally. |
| `reuse` | Labeled PR likely already solved part of the task. Inspect/reuse before building. |
| `revise` | Labeled PR changes constraints or sequencing. Update the plan. |
| `pause` | Same-target active work is likely overlapping. Pause edits to that target. |
| `handoff` | Ownership or review has moved to a human or another team. Treat that as the handoff point. |
| `clarify` | Signal matters but is ambiguous. Ask only if no safe plan can be formed from evidence. |

### PRSignalEvidence

Evidence returned to agents must be compact and citeable.

```python
@dataclass(frozen=True)
class PRSignalEvidence:
    repo: str
    number: int
    url: str
    title: str
    author: str
    state: str
    updated_at: datetime
    matched_paths: tuple[str, ...]
    reason: str
```

The evidence explains why the agent changed its plan without exposing hidden
telemetry or unrelated PR content.

## MCP Context Contract

The existing `context` tool becomes the ambient coordination surface.

```python
context(
    repo: str | None = None,
    goal: str | None = None,
    paths: list[str] | None = None,
    include_pr_signals: bool = True,
) -> dict
```

### Response Shape

The current `active` and `recent` keys remain backward-compatible. This spec
adds a `coordination` key.

```json
{
  "active": [],
  "recent": [],
  "coordination": {
    "status": "ok",
    "summary": "2 jurati-labeled PRs may affect this plan.",
    "guidance": [
      {
        "effect": "reuse",
        "urgency": "notice",
        "summary": "Tony merged PR #418 on auth token resolution last week.",
        "instruction": "Inspect and reuse that resolver before building a new one.",
        "confidence": 86,
        "evidence": [
          {
            "repo": "api",
            "number": 418,
            "url": "https://github.com/org/api/pull/418",
            "title": "Resolve token refresh races",
            "author": "tony",
            "state": "merged",
            "updated_at": "2026-04-27T18:40:00Z",
            "matched_paths": ["src/auth/token.py"],
            "reason": "merged jurati-labeled PR touched requested path"
          }
        ]
      }
    ],
    "privacy_boundary": [
      "only configured repos are checked",
      "only PRs carrying the configured jurati label are used",
      "unlabeled PRs, comments, chats, editor activity, and read activity are not mined"
    ]
  }
}
```

### Prompt Context

MCP clients that consume text better than structured JSON may use this derived
summary:

```text
Jurati coordination: reuse prior work before editing src/auth/token.py. Tony
merged org/api#418 last week with the jurati label and it touched the same
target. Evidence: https://github.com/org/api/pull/418.
```

The prompt text is derived from the structured response. It is not a separate
source of truth.

## Classification Rules

Classification is deterministic in v1. No LLM is required inside the server.

Inputs:

- requested `repo`
- requested `goal`
- requested `paths`
- labeled PR title/body excerpt
- PR state and recency
- changed file paths
- configured repo graph

Rules:

1. **Same path, merged recently:** `reuse`
   - A merged labeled PR touched a requested path or target area within the
     recency window.
   - Instruction: inspect/reuse before building.
2. **Same path, open:** `pause`
   - An open labeled PR touches a requested path or target area.
   - Instruction: pause edits to that target and account for the PR.
3. **Workflow/decision language:** `revise`
   - Title/body excerpt or labels indicate workflow, decision, migration,
     deprecation, architecture, release, security, or ownership.
   - Instruction: update the plan constraints.
4. **Assigned ownership or review language:** `handoff`
   - Title/body excerpt includes explicit handoff, owner, review, blocked, or
     waiting language.
   - Instruction: treat the PR as the ownership/review point.
5. **Different area, same repo:** `continue`
   - PR is relevant to the repo but not the requested target.
   - Instruction: continue, but keep the signal in background context.
6. **Relevant but ambiguous:** `clarify`
   - Signal matches the repo or goal but no safe effect can be chosen.
   - Instruction: ask only if the ambiguity blocks a safe plan.

Confidence is a bounded integer from 0 to 100. Same-path evidence outranks
keyword-only evidence. Open PRs outrank old merged PRs for pause/handoff.

## Signal Source Configuration

Jurati needs a configured set of source repositories to check for labeled PRs.
This must be explicit. The server must not crawl an organization looking for
repos.

Example config:

```yaml
pr_signals:
  provider: github
  label: jurati
  recency_days: 30
  repos:
    - org/api
    - org/web
    - org/platform
  include_body_excerpt: true
  include_changed_paths: true
  include_comments: false
```

Rules:

- `repos` is required for PR signal ingestion.
- `label` defaults to `jurati`.
- `recency_days` defaults to 30.
- `include_body_excerpt` defaults to true with a strict server-side character
  limit.
- `include_changed_paths` defaults to true.
- `include_comments` defaults to false and is not implemented in v1.
- Canonical config lives in the knowledge repo `.jurati/config.yaml` so every
  agent connected to the same knowledge repo sees the same source list.
- Source-repo setup files may point the MCP server at the knowledge repo, but
  they must not silently add new PR signal sources without explicit config.

## Provider Adapter

### GitHub V1

The GitHub adapter reads only configured repositories and only PRs with the
configured label.

Allowed provider queries:

- list PRs in a configured repo with label `jurati` and updated within the
  recency window
- fetch bounded metadata for those PRs
- fetch changed file paths for those PRs when `include_changed_paths` is true

Disallowed provider queries:

- list unlabeled PRs for inference
- search the whole organization for activity
- fetch review comments or issue comments in v1
- fetch raw diff hunks in v1
- write labels, comments, reviews, or PR updates from the read path

### Label Removal

Removing the `jurati` label removes the PR from future coordination context
after the next provider refresh. If a cached signal still has the label but the
provider later reports that the label was removed, Jurati drops the cached
signal. Label removal does not erase previous MCP responses, chat transcripts,
or provider history outside Jurati's control.

### Caching

Jurati may keep a local cache of normalized `PRSignal` objects to avoid hitting
the provider on every context call.

Cache rules:

- cache only labeled PR metadata from configured repos
- expire cache entries by `recency_days` and provider `updated_at`
- never cache unlabeled PR metadata
- never cache query text, user identity, read selections, or agent decisions
- cache refresh failures must not break the existing knowledge context path

## Privacy And Security Boundary

PR-label coordination is an explicit broadcast channel.

Jurati may process:

- metadata for PRs carrying the configured `jurati` label
- title and bounded body excerpt for labeled PRs
- author, timestamps, URL, state, and labels from labeled PRs
- changed file paths for labeled PRs when enabled

Jurati must not process for coordination:

- unlabeled PRs
- PR comments or review comments in v1
- raw diffs in v1
- chats, meetings, editor activity, terminal activity, read receipts, or agent
  telemetry
- absence signals, such as who did not label a PR or did not read context

Jurati must not persist or report:

- which developer or agent requested context
- which PR signal changed a particular agent's plan
- which returned signals were ignored
- organization-wide participation metrics
- rankings of who shared the most or least context

Security rules:

- Provider tokens are read ephemerally and never stored on long-lived server
  state.
- Provider calls must be non-prompting and time-bounded.
- PR title/body text is data, never code.
- Body excerpts are size-bounded before entering MCP responses.
- Fork PRs are included only if the labeled PR exists in a configured base repo
  and the provider token can already read it. No fork checkout or code execution
  occurs.
- If provider access fails, Jurati returns knowledge-repo context plus a
  degraded coordination status. It must not expose token details.

## Component Boundaries

The implementation must preserve Jurati's deterministic core boundary.

| Component | Boundary |
|---|---|
| `core/pr_signals.py` | Pure normalization, target derivation, classification, guidance ranking |
| `providers/github_prs.py` | GitHub API reads for configured labeled PRs |
| `git/config.py` | Explicit PR signal source config loading and validation |
| `server.py` | MCP orchestration, cache refresh, `context()` response assembly |
| local cache module | Stores only normalized labeled PR signals from configured repos |

`core/pr_signals.py` receives `PRSignal` objects and explicit request context as
inputs. It does not read files, call GitHub, inspect git remotes, read
environment variables, or look at wall-clock time except through explicit
arguments.

## Fit With Knowledge Entries

PR signals are not automatically durable knowledge entries.

The labeled PR remains the source of truth for the coordination signal. Jurati
may surface it through `context()` without writing anything to the knowledge
repo.

A signal should become a durable knowledge entry only when one of these happens:

- a developer uses `jurati:` commit capture
- an agent explicitly proposes a decision/workflow entry based on the PR
- a human asks the agent to record the lesson
- a curation job suggests promotion and a human approves it

This keeps PR-label coordination lightweight and prevents every useful PR label
from becoming knowledge-repo noise.

## Product UX

The visible product outcome is better agent behavior.

Good behavior:

- "I found Tony's labeled PR from last week and will build on it."
- "This overlaps an open labeled PR, so I am pausing edits to that file."
- "The release workflow changed in a labeled PR, so I am adjusting the plan."
- "The labeled PR is related but parallel, so I can continue."

Bad behavior:

- Asking the developer to run Jurati commands during normal work.
- Showing a notification stream the developer must triage.
- Treating all PR labels as mandatory blockers.
- Treating unlabeled work as irrelevant or absent.
- Claiming certainty without evidence URLs.

## Testing Strategy

### Core Tests

- normalize `PRSignal` with stable IDs
- derive target areas from changed paths deterministically
- classify same-path merged PR as `reuse`
- classify same-path open PR as `pause`
- classify workflow/decision signals as `revise`
- classify unrelated labeled PR as `continue`
- classify ambiguous relevant signal as `clarify`
- confidence is stable for identical inputs
- prompt context is derived from structured guidance

### Privacy Tests

- unlabeled PR metadata is ignored and not cached
- context calls do not persist caller identity or query text
- read path does not write labels, comments, reviews, or PR updates
- raw diff hunks are never requested in v1
- body excerpts are bounded
- provider errors do not expose token values or auth probes

### Server Tests

- `context()` preserves existing `active` and `recent` keys
- `context()` adds `coordination` when PR signals are configured
- `context(include_pr_signals=False)` skips provider/cache reads
- provider failure returns degraded coordination status, not total failure
- no write-path function is called from PR signal context reads

### Provider Tests

- GitHub adapter queries only configured repos
- GitHub adapter applies the configured label filter
- recency filter is applied before returning signals
- changed paths are fetched only when enabled
- comments and raw diffs are not fetched in v1

### Product Golden Tests

Maintain a small golden set of planning scenarios:

- duplicate work avoided because a merged labeled PR covered the target
- plan revised because a labeled PR changed workflow constraints
- overlapping work paused because an open labeled PR touches the same path
- parallel work continues because labeled PRs touch unrelated paths

Every real false positive or missed signal should become a golden test.

## Acceptance Criteria

- A developer can label a PR `jurati` and do nothing else.
- A configured agent receives that PR as MCP context on a later planning call.
- The context includes a concrete planning effect, instruction, confidence, and
  evidence URL.
- Unlabeled PRs do not affect coordination output.
- No developer command, dashboard, or notification is required in the normal
  loop.
- Existing knowledge-repo `active` and `recent` context still works when PR
  signal ingestion is disabled or failing.
- The implementation keeps `core/` deterministic and side-effect free.
- Provider access lives outside `core/` and follows non-prompting auth rules.
- Privacy regression tests prove no read receipts, query logs, unlabeled PR
  mining, comments, raw diffs, or participation metrics are introduced.

## Non-Goals

- No web UI.
- No notification feed.
- No automatic comments on PRs.
- No automatic label creation or removal.
- No org-wide repo crawling.
- No LLM-based classification inside the Jurati server in v1.
- No PR comment/review-comment ingestion in v1.
- No raw diff ingestion in v1.
- No participation analytics.
- No claim that Jurati can affect agents that never call its MCP tools.

## Open Questions

1. Should PR signal source config live first in `.jurati/config.yaml` in the
   knowledge repo, or should source repos also be allowed to provide a bootstrap
   pointer that the MCP server trusts?
2. Should `context()` accept `paths` in v1, or should it infer target paths only
   from repo and goal text until the agent can pass richer planning state?
3. Should merged labeled PRs have a separate default recency window from open
   labeled PRs?
4. Should a labeled PR be promotable to a durable project entry through a
   one-click curation path later, or should promotion always happen through
   existing `record`/`propose` flows?
5. What is the default `body_excerpt` character limit for MCP responses?
