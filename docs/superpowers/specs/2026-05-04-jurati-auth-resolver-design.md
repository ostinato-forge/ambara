# Jurati Auth Resolver - Zero-Config PR Creation

**Date:** 2026-05-04
**Status:** Draft (v4 - candidate iterator revision)
**Scope:** `jurati/git/auth.py`, `jurati/git/pr.py`, `jurati/server.py`

---

## Problem

Jurati shells out to `gh pr create` for L1+ writes. The `gh` CLI uses whatever
GitHub account is currently active, which may not have access to the knowledge
repo. In multi-account setups (personal + work, different orgs), this fails only
after a developer tries to record project context or propose a decision. By then
the branch may already be pushed, no PR exists, and the caller sees a raw
subprocess error.

This affects all three PR-creating code paths: `record()` (L1), `propose()`
(L2/L3), and `expire()` (L1+).

Developers should not have to configure anything in the common case. If a
non-prompting local auth source can create the PR, Jurati should find it during
the explicit write. If no PR can be created, the write should still return a
reviewable branch reference instead of failing after the branch push.

## Design Principles

1. **Zero-config in the happy path.** If the developer has `gh` installed and a
   locally authenticated GitHub account can create a PR for the knowledge repo,
   Jurati tries it without requiring `gh auth switch` or repo-specific setup.
2. **Explicit override for orgs.** `JURATI_KNOWLEDGE_TOKEN` gives orgs a way to
   pin auth without relying on ambient `gh` state.
3. **Never prompt.** Jurati must not open an editor, browser, keychain prompt, or
   interactive terminal question from a write tool.
4. **Never narrate auth.** Jurati returns the best write outcome it can produce.
   If it cannot create a PR, it returns a branch reference and review path. It
   does not explain which auth sources were tried or why they failed.
5. **Privacy-first.** No logging of auth probes, no auth state in MCP responses
   or status, no preemptive checking, and no tokens stored on long-lived objects.

---

## 1. Candidate Chain

A new module `jurati/git/auth.py` implements privacy-safe helpers for generating
PR creation candidates. A candidate is not a guarantee that PR creation will
work. It is a non-prompting way to attempt PR creation during an explicit L1+
write.

### Attempt Order

The PR creator tries candidates in order until one creates a real PR. It does
not stop at the first present source. Failed candidates are silent and the same
write continues to the next candidate.

| Priority | Source | Mechanism |
|---|---|---|
| 1 | `JURATI_KNOWLEDGE_TOKEN` env var | Token used directly for GitHub REST API calls |
| 2 | `GH_TOKEN` / `GITHUB_TOKEN` env var | Standard GitHub convention; CI sets this automatically |
| 3 | Each known `gh` account for `github.com` | `gh auth token --hostname github.com --user <user>`, then REST API |
| 4 | Active `gh` CLI account | `gh pr create --repo {owner}/{repo}` with prompts disabled |
| 5 | None - branch-only mode | Branch is pushed, branch name and optional compare URL returned |

This order means a revoked org token cannot block a working `GH_TOKEN`, and a
wrong active `gh` account cannot block another locally authenticated `gh` user.
Jurati never mutates global GitHub CLI state. It does not call `gh auth switch`.

### AuthCandidate

```python
@dataclass(frozen=True)
class AuthCandidate:
    method: Literal["api_token", "gh_cli", "branch_only"]
    source: Literal[
        "env_jurati",
        "env_gh",
        "gh_user_token",
        "gh_cli_pr",
        "none",
    ]
    owner: str | None = None
    repo: str | None = None
    gh_user: str | None = None
```

`method` tells `pr.py` how to attempt PR creation. `source` and `gh_user` tell
the token reader where to fetch a token for this single attempt.

**Tokens are never stored on `AuthCandidate`.** The candidate records where to
find the token. At PR attempt time, `pr.py` reads the token fresh:

- `env_jurati` -> `os.environ.get("JURATI_KNOWLEDGE_TOKEN")`
- `env_gh` -> `os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")`
- `gh_user_token` -> `gh auth token --hostname github.com --user <user>`

This means any cached strategy on `ServerState` never holds a token value.
Tokens exist in local variables within a single `create_pr` call and are not
retained.

### Discovering `gh` Users

`auth.py` may inspect known GitHub CLI accounts with a non-prompting command:

```python
gh auth status --hostname github.com --json hosts
```

The JSON structure is `{"hosts": {"github.com": [{"login": "...", "state":
"success", "active": true, ...}, ...]}}` — a list of account objects under
`hosts.github.com`. Only accounts with `state == "success"` are used. Only the
`login` field is extracted to build per-user token candidates. The raw status
payload is never logged and never returned through MCP. If this command fails or
times out, Jurati treats it as "no enumerable gh users" and continues to the
active-account `gh pr create` candidate.

### Non-Prompting Subprocess Rules

Every `gh` subprocess launched by Jurati must use:

- `stdin=subprocess.DEVNULL`
- `capture_output=True`
- `text=True`
- a bounded timeout
- an environment that includes `GH_PROMPT_DISABLED=1`

`gh auth token` uses a 15 second timeout. `gh auth status` uses a 15 second
timeout. `gh pr create` uses a 30 second timeout.

The output of `gh auth token` is a raw PAT. It must never be passed to any
logging call, even at DEBUG level. This is different from the rest of the git
layer, which usually handles non-secret subprocess output.

### Environment Variable Reading

`JURATI_KNOWLEDGE_TOKEN` is read by the auth candidate/token helpers in
`auth.py`, not by `load_config_from_env()` in `config.py`. This deliberately
diverges from the existing pattern where `config.py` centralizes env var
reading. The reason: tokens should not live on the `JuratiConfig` frozen
dataclass that persists on `ServerState` for the server lifetime. The auth layer
reads them ephemerally during the explicit write.

---

## 2. Remote URL Parsing

A pure function `parse_github_remote(url: str) -> tuple[str, str] | None`
extracts `(owner, repo)` from the configured remote URL.

### Supported Formats

| Format | Example |
|---|---|
| SSH | `git@github.com:owner/repo.git` |
| HTTPS | `https://github.com/owner/repo.git` |
| HTTPS (no .git) | `https://github.com/owner/repo` |
| SSH (`ssh://`) | `ssh://git@github.com/owner/repo.git` |

Returns `None` for non-GitHub URLs (GitLab, Bitbucket, self-hosted).

**Known limitation:** GitHub Enterprise with custom domains (for example,
`git@github.mycompany.com:org/repo.git`) is not supported in v1. The parser only
matches `github.com`. GHE support can be added later by accepting an optional
hostname parameter.

The function lives in `jurati/git/auth.py` because it is part of the auth/GitHub
concern. If a future need arises for `owner/repo` outside auth, such as
constructing browse URLs, the function can move to a shared module then.

### Non-GitHub Remotes

When `parse_github_remote` returns `None`, Jurati skips GitHub PR creation and
uses branch-only mode immediately. The branch-only result has `owner=None`,
`repo=None`, and `url=None`.

---

## 3. PR Creation Strategies

`pr.py` keeps one public `create_pr` interface and dispatches across the
candidate strategies.

### Strategy A - GitHub REST API (`httpx`)

Used for env-token and per-`gh`-user token candidates.

- `POST /repos/{owner}/{repo}/pulls` with `Authorization: Bearer {token}`
- Request body: `{"title": ..., "body": ..., "head": branch, "base": base}`
- Labels applied with a separate
  `POST /repos/{owner}/{repo}/issues/{number}/labels` call after PR creation
- Label failure is best-effort. If the PR is created but labeling fails, the PR
  remains without labels and the write still succeeds.
- Timeout: 30 seconds for each `httpx` call.
- `httpx` must be declared as an explicit dependency in `pyproject.toml`, not
  relied upon transitively through the `mcp` SDK.

### Strategy B - `gh pr create --repo`

Used after token candidates fail.

- Runs `gh pr create` with `--repo {owner}/{repo}` so repository selection does
  not depend on cwd inference.
- Includes `--head {branch}` so GitHub CLI does not prompt about where to push or
  fork. The branch has already been pushed by Jurati.
- Includes `--title`, `--body`, `--base`, and any labels.
- Uses the non-prompting subprocess rules from Section 1.
- Still depends on the active `gh` account, but by this point all enumerable
  non-active users have already been tried through token candidates.

### Strategy C - Branch-Only

Used when no PR candidate succeeds or when the remote is non-GitHub.

- No PR is created.
- The branch was already pushed by the git layer before PR creation is attempted.
- Returns a `PRResult` with `kind="branch"`:
  - If `owner/repo` is known: `url` is
    `https://github.com/{owner}/{repo}/compare/{base}...{branch}?expand=1`
  - If `owner/repo` is unknown: `url` is `None`
- `number` is `None` (not `0`) to avoid sentinel-value ambiguity.

### PRResult

```python
@dataclass(frozen=True)
class PRResult:
    url: str | None
    number: int | None
    branch: str
    kind: Literal["pr", "branch"]
```

`kind="pr"` means a real PR was created. `kind="branch"` means only the branch
was pushed. Callers that need to distinguish can check `kind`; callers that just
want a review URL can use `url`, which may be `None` for non-GitHub branch-only
results.

### Interface

The `create_pr` function signature gains a keyword-only
`candidates: Sequence[AuthCandidate]` parameter:

```python
def create_pr(
    repo_path: str,
    branch: str,
    title: str,
    body: str,
    *,
    labels: list[str],
    base: str,
    candidates: Sequence[AuthCandidate],
) -> tuple[PRResult, AuthCandidate | None]:
    ...
```

The second return element is the candidate that created the PR, or `None` for
branch-only results. This eliminates ambiguity in caching: the caller receives
exactly which candidate succeeded rather than trying to infer it after the fact.

`repo_path` is retained because the `gh_cli` strategy still needs a cwd.

`create_lightweight_pr` and `create_review_pr` are removed. Their only purpose
was to hardcode label lists. With server orchestration passing labels directly
to `create_pr`, the wrappers become dead code.

---

## 4. Caching

The auth layer is lazy. Candidate generation and PR attempts only occur during an
explicit L1+ write.

### Lifecycle

1. **First L1+ write** -> generate candidates and try them in priority order.
2. **A candidate creates a PR** -> `create_pr` returns the winning candidate;
   cache it on `ServerState`.
3. **Subsequent writes** -> try the cached candidate first, then the freshly
   generated full candidate chain if the cached candidate fails.
4. **No candidate creates a PR** -> return branch-only for that call and do not
   cache branch-only as an auth strategy.

### Cache Rules

- **Cache only proof.** A candidate is cached only after it creates a real PR.
- **Never cache token values.** The cached candidate records source metadata, not
  the token.
- **Do not cache branch-only.** If auth appears later, the next write should pick
  it up.
- **Do not permanently suppress higher-priority sources.** A working cached
  candidate may be tried first for speed, but if it fails the current write tries
  a fresh full chain from the top. That allows fixed env tokens to take effect
  without restarting the server.
- **Cache reset:** server restart clears it. Session boundaries are natural reset
  points.
- **No startup probe:** no auth command runs until the first L1+ write.

---

## 5. Server Orchestration

All three PR-creating tools (`record`, `propose`, `expire`) need identical
branch push -> PR attempt -> branch-only fallback -> local cleanup behavior. This
is extracted into one serialized helper.

### Shared Helper

```python
def _finish_pr_write(
    lock: threading.Lock,
    repo_path: str,
    intent: WriteIntent | ExpireIntent,
    *,
    title: str,
    body: str,
    labels: list[str],
    base: str,
    remote_url: str,
    cached_candidate: AuthCandidate | None,
    now: datetime | None = None,
) -> tuple[str, PRResult, AuthCandidate | None]:
    ...
```

This is a synchronous function called inside `anyio.to_thread.run_sync` by each
tool handler, matching the existing codebase pattern for blocking git work. It
does not use `httpx.AsyncClient`. The third return element is the candidate that
created the PR (for caching), or `None` for branch-only results.

Inside that blocking transaction, the existing `write_lock` covers:

1. Creating the local branch from `origin/{base}`
2. Materializing the entry or expiry commit
3. Pushing the branch
4. Generating/traversing auth candidates
5. Attempting PR creation or branch-only fallback (returns winning candidate)
6. Cleaning up the local branch in `finally`

The caller (async tool handler) updates `state.cached_pr_candidate` after the
blocking call returns.

This fixes the current split where `_do_branch_record()` releases the lock before
PR creation and cleanup. The pushed branch, PR outcome, auth cache, and local
branch cleanup become one serialized write lifecycle.

`ServerState` gains:

```python
cached_pr_candidate: AuthCandidate | None = None
```

### Receipt Changes

Both `_write_receipt` and `_expire_receipt` produce accurate text for both PR and
branch-only outcomes:

- `kind="pr"`:
  - `write_mode` remains `"lightweight_pr"` or `"review_pr"`
  - `what_happened` says a PR was created
  - `pr_url` and `pr_number` are included
- `kind="branch"`:
  - `write_mode` is `"branch_only"`
  - `what_happened` says `"Pushed proposed knowledge branch {branch}."`
  - `visibility` says the branch is reviewable but source-of-truth content only
    changes after a PR/merge into the main branch
  - `next_step` says to open or review the branch and merge accepted content
  - `review_url` is included when a compare URL can be constructed
  - `branch` is always included

Receipts never include auth-related information. They do not include
`auth_method`, `auth_user`, `auth_fallback_used`, token source, or failure reason.
Branch-only is a factual write outcome, not an auth diagnostic.

---

## 6. Testing Strategy

### Unit Tests - `tests/git/test_auth.py`

- `parse_github_remote`: all four URL formats, non-GitHub URLs return `None`,
  malformed inputs, GHE URLs return `None` (known limitation)
- Env token candidate generation: priority order and token non-retention
- `gh auth status --json hosts` parsing for multiple users
- Failure/timeout of `gh auth status` produces no user-token candidates
- Non-GitHub remote returns only branch-only
- Every `gh` helper uses `GH_PROMPT_DISABLED=1`, `stdin=DEVNULL`, captured
  output, text mode, and timeout

### Unit Tests - `tests/git/test_pr.py` (extended)

- Existing tests updated to pass candidate lists
- API-based PR creation: mock `httpx` responses, verify endpoint, payload,
  headers, and timeout
- Multiple token candidates: first failing candidate does not block later working
  candidate
- Label application: verify separate API call; label failure does not fail PR
  creation
- `gh pr create`: verifies `--repo`, `--head`, prompt suppression, cwd, labels,
  and timeout
- Branch-only fallback: verify `kind="branch"`, `number is None`, URL
  construction with and without owner/repo
- Error handling: API 4xx/5xx, `httpx` timeout, `httpx` connection error, `gh`
  subprocess failure

### Unit Tests - `tests/test_server.py` (extended)

- `_finish_pr_write`: mocked branch/materialization/push/PR creation sequence
- Lock covers branch push, PR attempt, cache mutation, and cleanup
- Cleanup runs in `finally` after PR success, PR failure, and branch-only fallback
- Cache only updates after `kind="pr"`
- All three tools (`record`, `propose`, `expire`) use the shared helper
- Branch-only receipts are accurate and do not expose auth diagnostics

### Optional Live Test - `tests/git/test_pr_integration.py`

Live token extraction is opt-in only:

- Register an `integration` marker in `pyproject.toml`.
- Skip unless `JURATI_RUN_LIVE_AUTH_TESTS=1`.
- Skip if `gh` is not installed.
- Call `gh auth token --hostname github.com` with prompt suppression.
- Verify only that output is non-empty and has reasonable length (20+
  characters). Do not validate token prefixes; GitHub token formats evolve.
- Never print the token, even on assertion failure.

Default CI and default local `pytest` runs must not extract a real token.

---

## 7. Privacy Invariants

The auth layer must not introduce new observability about the developer's
activity.

### Hard Rules

1. **No logging of auth probes.** The resolver tries candidates and moves on. No
   `logger.info`, no `logger.warning` about auth state. Log readers learn nothing
   about the developer's auth configuration. This explicitly includes
   `gh auth token` output, which is a raw PAT.
2. **No auth state in MCP responses.** Write receipts include PR or branch review
   information. They do not include `auth_method`, `auth_user`,
   `auth_fallback_used`, token source, or failure reason.
3. **No auth state in `status()`.** The status tool reports sync health and entry
   counts. It does not gain an "auth status" or "PR capability" section.
4. **No proactive auth checking.** Jurati does not probe auth until a write is
   actually requested. It does not test whether tokens work at startup or on
   sync.
5. **Tokens never stored beyond a single function call.** Cached candidates
   record method/source/user metadata only. Tokens are read into local variables,
   used for one PR attempt, and discarded.
6. **Invalid tokens are silent.** If an env token is set but revoked, Jurati tries
   the next candidate. It does not report "your token is bad."
7. **No global account mutation.** Jurati never calls `gh auth switch` and never
   changes the developer's active GitHub CLI account.
8. **No prompting.** Any candidate that would require interaction must fail closed
   into the next candidate or branch-only mode.

---

## 8. File Changes Summary

| File | Change |
|---|---|
| `src/jurati/git/auth.py` | **New.** `parse_github_remote()`, `AuthCandidate`, candidate generation, `gh` user discovery, prompt-safe subprocess helpers |
| `src/jurati/git/pr.py` | Rewrite. `create_pr` traverses candidates and dispatches across API, gh CLI, and branch-only strategies. Wrapper functions removed. `PRResult` gains `kind` and nullable fields. |
| `src/jurati/server.py` | New `_finish_pr_write()` async shared helper with one serialized blocking transaction. All three PR call sites (`record`, `propose`, `expire`) use it. `cached_pr_candidate` added to `ServerState`. Receipts updated for branch-only mode. |
| `src/jurati/git/config.py` | No change. `JURATI_KNOWLEDGE_TOKEN` is read by auth helpers, not config. |
| `pyproject.toml` | Add `httpx` as explicit dependency. Register the `integration` pytest marker. |
| `tests/git/test_auth.py` | **New.** URL parsing, candidate generation, gh-user discovery, prompt suppression, token non-retention |
| `tests/git/test_pr.py` | Extended. API strategy, candidate iteration, gh CLI strategy, branch-only, labels, timeouts |
| `tests/test_server.py` | Extended. `_finish_pr_write` orchestration, serialized lifecycle, branch-only receipts, shared use by all tools |
| `tests/git/test_pr_integration.py` | **New optional.** Real `gh auth token` extraction behind `JURATI_RUN_LIVE_AUTH_TESTS=1` |

---

## 9. Known Limitations (v1)

1. **GitHub Enterprise:** Custom-domain GHE instances are not supported. The URL
   parser only matches `github.com`. Non-matching URLs get branch-only mode.
2. **Non-GitHub forges:** GitLab, Bitbucket, Gitea, etc. get branch-only mode
   with no compare URL.
3. **Token scope validation:** Jurati does not proactively check whether a token
   has the scopes needed for PR creation. Insufficient scopes are discovered only
   during the explicit write and silently lead to the next candidate.
4. **`gh auth status` JSON stability:** The implementation should parse only the
   minimum account fields needed for `gh auth token --user`. If the JSON shape is
   unavailable or changes, Jurati falls back to the active-account `gh pr create`
   candidate and then branch-only.
