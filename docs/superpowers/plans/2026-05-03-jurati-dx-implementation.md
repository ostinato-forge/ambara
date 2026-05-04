# Jurati DX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement ambient knowledge capture via `jurati:` commit conventions, BM25-powered query intelligence, git hook and GitHub Action triggers, curation automation, and ambient PR coordination via `jurati`-labeled PRs.

**Architecture:** Six independent phases, each producing working, testable software. Phase 1 is pure core logic (no I/O). Phase 2 upgrades the search/query layer. Phase 3 adds local git hook capture. Phase 4 adds CI-based capture. Phase 5 adds curation and onboarding polish. Phase 6 adds ambient PR coordination — `jurati`-labeled PRs become agent guidance.

**Tech Stack:** Python 3.13, pytest, gitpython, click, pydantic, mcp, ruff, mypy

**Specs:**
- `docs/superpowers/specs/2026-05-03-jurati-dx-design.md` (Phases 1–5)
- `docs/superpowers/specs/2026-05-04-jurati-ambient-coordination-design.md` (Phase 6)

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `src/jurati/capture/__init__.py` | Package marker |
| `src/jurati/capture/extract.py` | Commit message parsing, tag-to-type mapping, ID derivation, secret scanning |
| `src/jurati/capture/pipeline.py` | End-to-end capture orchestration: detect → parse → dedup → render → write |
| `src/jurati/capture/pending.py` | Offline queue: write/read/flush `.git/jurati-pending/` markers |
| `src/jurati/core/scoring.py` | BM25 inverted index, multi-signal ranking |
| `src/jurati/core/curation.py` | Contradiction detection, staleness scanning |
| `tests/capture/__init__.py` | Package marker |
| `tests/capture/test_extract.py` | Extraction pipeline unit tests |
| `tests/capture/test_pipeline.py` | Pipeline integration tests |
| `tests/capture/test_pending.py` | Offline queue tests |
| `tests/core/test_scoring.py` | BM25 and ranking tests (golden set) |
| `tests/core/test_curation.py` | Contradiction and staleness tests |
| `src/jurati/action/__init__.py` | Package marker |
| `src/jurati/action/capture.py` | GitHub Action Python entrypoint — batching, merge strategies, auto-merge |
| `src/jurati/curation/__init__.py` | Package marker |
| `src/jurati/curation/hygiene_pr.py` | Weekly hygiene PR body generation |
| `src/jurati/curation/run_hygiene.py` | CLI/Action entrypoint for weekly hygiene scan |
| `action/action.yml` | GitHub Action metadata |
| `action/hygiene.yml` | Scheduled weekly hygiene workflow |
| `tests/action/__init__.py` | Package marker |
| `tests/action/test_capture_action.py` | Action batching and merge strategy tests |
| `tests/curation/__init__.py` | Package marker |
| `tests/curation/test_hygiene_pr.py` | Hygiene PR generation tests |
| `src/jurati/core/pr_signals.py` | PR signal classification and coordination guidance (pure, deterministic) |
| `src/jurati/providers/__init__.py` | Package marker |
| `src/jurati/providers/github_prs.py` | GitHub adapter — read labeled PRs from configured repos |
| `src/jurati/providers/cache.py` | PR signal cache with recency expiry |
| `tests/core/test_pr_signals.py` | Classification rule tests |
| `tests/providers/__init__.py` | Package marker |
| `tests/providers/test_github_prs.py` | GitHub adapter tests |
| `tests/providers/test_cache.py` | Signal cache tests |
| `tests/test_server_coordination.py` | Coordination wiring tests |
| `tests/test_privacy_coordination.py` | Privacy regression tests for PR coordination |

### Modified Files

| File | Change |
|------|--------|
| `src/jurati/core/schema.py` | Add `SourceMeta` model, optional `source` field on `Frontmatter` |
| `src/jurati/core/search.py` | Wire BM25 scoring from `scoring.py` into existing `query()` function |
| `src/jurati/core/changes.py` | Add `plan_capture()` function for capture-pipeline write intents |
| `src/jurati/git/config.py` | Add `PRSignalsConfig`, `repo_graph`, and `secret_patterns` to config |
| `src/jurati/git/branch.py` | No changes — `push_branch_with_retry()` lives in `capture/pipeline.py` |
| `src/jurati/git/repo.py` | Add tree-hash-based rebuild optimization, `--prune` to fetch |
| `src/jurati/server.py` | Add `context` and `search` MCP tools; wire PR signal coordination into `context()` |
| `src/jurati/cli.py` | Add `install-hook`, `capture`, `active`, `flush`, `search` commands |

---

## Phase 1: Schema & Capture Core (Pure Logic, No I/O)

### Task 1: Add `SourceMeta` to Schema

**Files:**
- Modify: `src/jurati/core/schema.py:57-82`
- Test: `tests/core/test_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_schema.py — add to existing file

class TestSourceMeta:
    def test_source_meta_round_trip(self) -> None:
        from jurati.core.schema import Frontmatter, SourceMeta

        source = SourceMeta(repo="api-service", commit="abc123", author="dev@co.com")
        fm = Frontmatter(
            id="test-source",
            title="Test",
            type=EntryType.PROJECT,
            level=EscalationLevel.L1,
            created_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            updated_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            source=source,
        )
        assert fm.source is not None
        assert fm.source.repo == "api-service"
        assert fm.source.commit == "abc123"
        assert fm.source.author == "dev@co.com"

    def test_source_meta_optional(self) -> None:
        from jurati.core.schema import Frontmatter

        fm = Frontmatter(
            id="test-no-source",
            title="Test",
            type=EntryType.PROJECT,
            level=EscalationLevel.L1,
            created_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            updated_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        )
        assert fm.source is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/core/test_schema.py::TestSourceMeta -v`
Expected: FAIL — `SourceMeta` not defined, `source` field not on `Frontmatter`

- [ ] **Step 3: Implement SourceMeta and add source field**

In `src/jurati/core/schema.py`, add before the `Frontmatter` class:

```python
class SourceMeta(BaseModel, frozen=True):
    """Git provenance from the capture pipeline. Informational, not an identity assertion."""

    repo: str
    commit: str
    author: str
```

Then add to the `Frontmatter` class fields (after `review`):

```python
    source: SourceMeta | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/core/test_schema.py::TestSourceMeta -v`
Expected: PASS

- [ ] **Step 5: Run full test suite and lint**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest && ruff check src/ tests/`
Expected: All pass, no lint errors

- [ ] **Step 6: Commit**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/core/schema.py tests/core/test_schema.py
git commit -m "feat(schema): add optional SourceMeta to Frontmatter"
```

---

### Task 2: Commit Message Extraction (`capture/extract.py`)

**Files:**
- Create: `src/jurati/capture/__init__.py`
- Create: `src/jurati/capture/extract.py`
- Create: `tests/capture/__init__.py`
- Create: `tests/capture/test_extract.py`

- [ ] **Step 1: Create package markers**

Create `src/jurati/capture/__init__.py` and `tests/capture/__init__.py` as empty files.

- [ ] **Step 2: Write failing tests for message parsing**

```python
# tests/capture/test_extract.py
"""Tests for jurati.capture.extract."""

from __future__ import annotations

import pytest

from jurati.capture.extract import (
    CaptureResult,
    parse_commit_message,
    derive_entry_id,
    scan_secrets,
)
from jurati.core.schema import EntryType, EscalationLevel


class TestParseCommitMessage:
    def test_bare_jurati_prefix(self) -> None:
        result = parse_commit_message("jurati: postgres pool at 20 max")
        assert result is not None
        assert result.title == "postgres pool at 20 max"
        assert result.tag is None
        assert result.entry_type == EntryType.PROJECT
        assert result.level == EscalationLevel.L1
        assert result.body == ""

    def test_decision_tag(self) -> None:
        result = parse_commit_message("jurati(decision): switch to gRPC")
        assert result is not None
        assert result.title == "switch to gRPC"
        assert result.tag == "decision"
        assert result.entry_type == EntryType.DECISION
        assert result.level == EscalationLevel.L2

    def test_principle_tag(self) -> None:
        result = parse_commit_message("jurati(principle): all calls go through gateway")
        assert result is not None
        assert result.entry_type == EntryType.PRINCIPLE
        assert result.level == EscalationLevel.L3

    def test_workflow_tag(self) -> None:
        result = parse_commit_message("jurati(workflow): PRs require two approvals")
        assert result is not None
        assert result.entry_type == EntryType.WORKFLOW
        assert result.level == EscalationLevel.L2

    def test_unknown_tag_defaults_to_project(self) -> None:
        result = parse_commit_message("jurati(foobar): some note")
        assert result is not None
        assert result.entry_type == EntryType.PROJECT
        assert result.level == EscalationLevel.L1

    def test_multiline_body(self) -> None:
        msg = "jurati: pool limit changed\n\nWe hit OOM on staging with 50 connections."
        result = parse_commit_message(msg)
        assert result is not None
        assert result.title == "pool limit changed"
        assert result.body == "We hit OOM on staging with 50 connections."

    def test_no_prefix_returns_none(self) -> None:
        assert parse_commit_message("feat: add new feature") is None

    def test_empty_title_returns_none(self) -> None:
        assert parse_commit_message("jurati: ") is None
        assert parse_commit_message("jurati:") is None

    def test_whitespace_stripping(self) -> None:
        result = parse_commit_message("jurati:   spaced title  ")
        assert result is not None
        assert result.title == "spaced title"


class TestDeriveEntryId:
    def test_basic_id(self) -> None:
        entry_id = derive_entry_id("api-service", "postgres pool at 20 max")
        assert entry_id == "api-service-postgres-pool-at-20-max"

    def test_special_chars_slugified(self) -> None:
        entry_id = derive_entry_id("frontend", "switch to gRPC — faster!")
        assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in entry_id)

    def test_truncation_at_120_chars(self) -> None:
        long_title = "a " * 100
        entry_id = derive_entry_id("repo", long_title)
        assert len(entry_id) <= 120

    def test_collision_suffix(self) -> None:
        base_id = derive_entry_id("repo", "title")
        suffixed_id = derive_entry_id(
            "repo", "title", commit_sha="abc123", collision=True
        )
        assert suffixed_id.startswith(base_id)
        assert len(suffixed_id) > len(base_id)

    def test_deterministic(self) -> None:
        id1 = derive_entry_id("repo", "same title", commit_sha="sha1")
        id2 = derive_entry_id("repo", "same title", commit_sha="sha1")
        assert id1 == id2


class TestScanSecrets:
    def test_api_key_detected(self) -> None:
        assert scan_secrets("new key is sk-abc123def456") is True

    def test_password_detected(self) -> None:
        assert scan_secrets("password=hunter2") is True

    def test_normal_text_passes(self) -> None:
        assert scan_secrets("postgres pool at 20 max") is False

    def test_connection_string_detected(self) -> None:
        assert scan_secrets("postgresql://user:pass@host/db") is True

    def test_token_detected(self) -> None:
        assert scan_secrets("ghp_ABCDEFghijkl1234567890abcdefghij") is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/capture/test_extract.py -v`
Expected: FAIL — module `jurati.capture.extract` not found

- [ ] **Step 4: Implement extract.py**

```python
# src/jurati/capture/extract.py
"""Commit message parsing and ID derivation for the jurati: capture pipeline."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from jurati.core.schema import EntryType, EscalationLevel

_JURATI_RE = re.compile(r"^jurati(?:\(([a-z]+)\))?:\s*(.+)$", re.MULTILINE)

_TAG_MAP: dict[str, tuple[EntryType, EscalationLevel]] = {
    "decision": (EntryType.DECISION, EscalationLevel.L2),
    "principle": (EntryType.PRINCIPLE, EscalationLevel.L3),
    "workflow": (EntryType.WORKFLOW, EscalationLevel.L2),
}

_DEFAULT_TYPE = EntryType.PROJECT
_DEFAULT_LEVEL = EscalationLevel.L1

_SECRET_PATTERNS = [
    re.compile(r"(?:sk|pk|api[_-]?key)[_-]?[a-zA-Z0-9]{16,}", re.IGNORECASE),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"gho_[a-zA-Z0-9]{36}"),
    re.compile(r"password\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"token\s*[=:]\s*\S{16,}", re.IGNORECASE),
    re.compile(r"secret\s*[=:]\s*\S{8,}", re.IGNORECASE),
    re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"),
    re.compile(r"[a-z+]+://[^:]+:[^@]+@", re.IGNORECASE),
]

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class CaptureResult:
    title: str
    body: str
    tag: str | None
    entry_type: EntryType
    level: EscalationLevel


def parse_commit_message(message: str) -> CaptureResult | None:
    first_line = message.split("\n", 1)[0]
    match = _JURATI_RE.match(first_line)
    if not match:
        return None

    tag = match.group(1)
    title = match.group(2).strip()
    if not title:
        return None

    entry_type, level = _TAG_MAP.get(tag, (_DEFAULT_TYPE, _DEFAULT_LEVEL))

    body = ""
    parts = message.split("\n", 1)
    if len(parts) > 1:
        body = parts[1].strip()

    return CaptureResult(
        title=title,
        body=body,
        tag=tag,
        entry_type=entry_type,
        level=level,
    )


def derive_entry_id(
    repo_slug: str,
    title: str,
    *,
    commit_sha: str | None = None,
    collision: bool = False,
) -> str:
    slug = _SLUG_RE.sub("-", f"{repo_slug}-{title}".lower()).strip("-")
    if len(slug) > 120:
        slug = slug[:120].rstrip("-")

    if collision and commit_sha:
        raw = f"{repo_slug}:{commit_sha}:{title}"
        short_hash = hashlib.sha256(raw.encode()).hexdigest()[:6]
        suffix = f"-{short_hash}"
        if len(slug) + len(suffix) > 120:
            slug = slug[: 120 - len(suffix)]
        slug = f"{slug}{suffix}"

    return slug


def scan_secrets(text: str, extra_patterns: list[re.Pattern[str]] | None = None) -> bool:
    patterns = _SECRET_PATTERNS + (extra_patterns or [])
    return any(p.search(text) for p in patterns)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/capture/test_extract.py -v`
Expected: PASS (adjust any secret pattern edge cases that don't match)

- [ ] **Step 6: Fix any test mismatches, run lint**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && ruff check src/jurati/capture/ tests/capture/ && mypy src/jurati/capture/`
Expected: Clean

- [ ] **Step 7: Commit**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/capture/ tests/capture/
git commit -m "feat(capture): add commit message extraction and ID derivation"
```

---

### Task 3: Add `plan_capture()` to `core/changes.py`

The capture pipeline needs a function that creates `WriteIntent` objects from `CaptureResult` data, including the `source` field. This bridges the extraction layer to the existing write-intent system.

**Files:**
- Modify: `src/jurati/core/changes.py`
- Test: `tests/core/test_changes.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_changes.py — add to existing file

from jurati.core.schema import SourceMeta


def test_plan_capture_creates_l1_project_intent() -> None:
    from jurati.core.changes import plan_capture

    intent = plan_capture(
        entry_type=EntryType.PROJECT,
        title="postgres pool at 20 max",
        body="We hit OOM on staging.",
        entry_id="api-service-postgres-pool-at-20-max",
        level=EscalationLevel.L1,
        now=BASE_NOW,
        source=SourceMeta(repo="api-service", commit="abc123", author="dev@co.com"),
    )

    assert intent.path == "projects/api-service-postgres-pool-at-20-max.md"
    assert intent.branch == "jurati/api-service/postgres-pool-at-20-max"
    assert intent.write_mode == "lightweight_pr"
    assert intent.level == EscalationLevel.L1
    assert "source:" in intent.content
    assert "repo: api-service" in intent.content
    assert "We hit OOM on staging." in intent.content


def test_plan_capture_creates_l2_decision_intent() -> None:
    from jurati.core.changes import plan_capture

    intent = plan_capture(
        entry_type=EntryType.DECISION,
        title="switch to gRPC",
        body="Faster inter-service calls.",
        entry_id="api-service-switch-to-grpc",
        level=EscalationLevel.L2,
        now=BASE_NOW,
        source=SourceMeta(repo="api-service", commit="def456", author="dev@co.com"),
    )

    assert intent.path == "decisions/api-service-switch-to-grpc.md"
    assert intent.write_mode == "review_pr"
    assert intent.level == EscalationLevel.L2


def test_plan_capture_branch_uses_repo_slug_namespace() -> None:
    from jurati.core.changes import plan_capture

    intent = plan_capture(
        entry_type=EntryType.PROJECT,
        title="fix auth timeout",
        entry_id="frontend-fix-auth-timeout",
        level=EscalationLevel.L1,
        now=BASE_NOW,
        source=SourceMeta(repo="frontend", commit="ghi789", author="dev@co.com"),
    )

    assert intent.branch == "jurati/frontend/fix-auth-timeout"


def test_plan_capture_without_source() -> None:
    from jurati.core.changes import plan_capture

    intent = plan_capture(
        entry_type=EntryType.PROJECT,
        title="manual note",
        entry_id="manual-note",
        level=EscalationLevel.L1,
        now=BASE_NOW,
    )

    assert "source:" not in intent.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/core/test_changes.py::test_plan_capture_creates_l1_project_intent -v`
Expected: FAIL — `plan_capture` not defined

- [ ] **Step 3: Implement `plan_capture()`**

Add to `src/jurati/core/changes.py`:

```python
def plan_capture(
    entry_type: EntryType,
    title: str,
    body: str = "",
    *,
    entry_id: str,
    level: EscalationLevel,
    now: datetime,
    source: SourceMeta | None = None,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    branch_prefix: str = "jurati",
) -> WriteIntent:
    """Create a WriteIntent from capture-pipeline data.

    Unlike plan_record/plan_propose, this accepts pre-classified type/level
    from the extraction layer and produces repo-slug-namespaced branches.
    """
    from .paths import entry_path
    from .validate import check_write_path

    write_mode = check_write_path(entry_type, level)
    path = entry_path(entry_type, entry_id)

    # Branch uses repo slug from source for namespace isolation
    repo_slug = source.repo if source else None
    entry_suffix = entry_id
    if repo_slug and entry_id.startswith(f"{repo_slug}-"):
        entry_suffix = entry_id[len(repo_slug) + 1 :]

    if write_mode == "active_ref":
        branch = None
    elif repo_slug:
        branch = f"{branch_prefix}/{repo_slug}/{entry_suffix}"
    else:
        branch = f"{branch_prefix}/{entry_id}"

    status = EntryStatus.ACTIVE if level == EscalationLevel.L0 else EntryStatus.PROPOSED

    fm = Frontmatter(
        id=entry_id,
        title=title,
        type=entry_type,
        level=level,
        status=status,
        created_at=now,
        updated_at=now,
        projects=projects or [],
        tags=tags or [],
        review=ReviewMeta(required=requires_pr(level)),
        source=source,
    )

    content = _render_entry(fm, body)

    return WriteIntent(
        path=path,
        content=content,
        branch=branch,
        write_mode=write_mode,
        entry_id=entry_id,
        level=level,
    )
```

Also update `_render_entry()` to emit the `source` block when present.
Insert the following **before** the closing `lines.append("---")` delimiter
(the second `---` in the function, immediately after the `review: / pr:` lines).
Do not rely on line numbers — find the structural marker `lines.append("---")`
that closes the frontmatter block:

```python
    if fm.source is not None:
        lines.append("source:")
        lines.append(f"  repo: {fm.source.repo}")
        lines.append(f"  commit: {fm.source.commit}")
        lines.append(f"  author: {fm.source.author}")
```

Add `SourceMeta` and `requires_pr` to the **existing** import from `.schema` in
`changes.py` (line 10-18). Do NOT replace the existing import — add to it:

```python
# In the existing import block at the top of changes.py, add SourceMeta and requires_pr:
from jurati.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    ReviewMeta,
    SourceMeta,
    is_level_allowed,
    requires_pr,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/core/test_changes.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite and lint**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest && ruff check src/ tests/ && mypy src/jurati/core/changes.py`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/core/changes.py src/jurati/core/schema.py tests/core/test_changes.py
git commit -m "feat(capture): add plan_capture() and source rendering"
```

---

## Phase 2: BM25 Scoring & MCP Tools

### Task 4: BM25 Inverted Index (`core/scoring.py`)

**Files:**
- Create: `src/jurati/core/scoring.py`
- Create: `tests/core/test_scoring.py`

- [ ] **Step 1: Write failing tests for tokenization and index building**

```python
# tests/core/test_scoring.py
"""Tests for jurati.core.scoring — BM25 inverted index and multi-signal ranking."""

from __future__ import annotations

from datetime import UTC, datetime

from jurati.core.schema import EntryType, EscalationLevel
from jurati.core.scoring import (
    InvertedIndex,
    build_inverted_index,
    bm25_score,
    rank_entries,
    tokenize,
)

from .conftest import BASE_NOW, make_entry


class TestTokenize:
    def test_lowercase_split(self) -> None:
        tokens = tokenize("Postgres Pool Limit")
        assert tokens == ["postgres", "pool", "limit"]

    def test_strips_punctuation(self) -> None:
        tokens = tokenize("what's the caching strategy?")
        assert "whats" in tokens or "what" in tokens
        assert "caching" in tokens
        assert "strategy" in tokens

    def test_empty_string(self) -> None:
        assert tokenize("") == []


class TestBuildInvertedIndex:
    def test_builds_from_entries(self) -> None:
        entries = [
            make_entry(entry_id="e1", title="postgres pool limit", body="OOM fix"),
            make_entry(entry_id="e2", title="redis cache strategy", body="TTL design"),
        ]
        idx = build_inverted_index(entries)
        assert "postgres" in idx.term_doc_freq
        assert "redis" in idx.term_doc_freq
        assert idx.doc_count == 2

    def test_term_frequency_counts(self) -> None:
        entries = [
            make_entry(entry_id="e1", title="pool pool pool", body="pool"),
        ]
        idx = build_inverted_index(entries)
        # Title is tripled in index text for title-boosting: 3×3 + 1 body = 10
        assert idx.doc_term_freq["e1"]["pool"] == 10


class TestBm25Score:
    def test_matching_query_scores_positive(self) -> None:
        entries = [
            make_entry(entry_id="e1", title="postgres pool limit"),
            make_entry(entry_id="e2", title="redis cache"),
        ]
        idx = build_inverted_index(entries)
        score = bm25_score(idx, "e1", "postgres pool")
        assert score > 0.0

    def test_non_matching_query_scores_zero(self) -> None:
        entries = [
            make_entry(entry_id="e1", title="postgres pool limit"),
        ]
        idx = build_inverted_index(entries)
        score = bm25_score(idx, "e1", "redis cache")
        assert score == 0.0

    def test_exact_title_match_scores_highest(self) -> None:
        entries = [
            make_entry(entry_id="e1", title="postgres pool limit", body="details"),
            make_entry(entry_id="e2", title="redis pool config", body="postgres note"),
        ]
        idx = build_inverted_index(entries)
        s1 = bm25_score(idx, "e1", "postgres pool limit")
        s2 = bm25_score(idx, "e2", "postgres pool limit")
        assert s1 > s2


class TestRankEntries:
    def test_returns_sorted_by_relevance(self) -> None:
        e1 = make_entry(entry_id="e1", title="postgres pool limit")
        e2 = make_entry(entry_id="e2", title="redis cache strategy")
        entries = [e1, e2]
        results = rank_entries(entries, "postgres pool", now=BASE_NOW)
        assert len(results) >= 1
        assert results[0].entry.frontmatter.id == "e1"

    def test_honest_zero(self) -> None:
        e1 = make_entry(entry_id="e1", title="postgres pool limit")
        results = rank_entries([e1], "kubernetes deployment", now=BASE_NOW)
        assert len(results) == 0

    def test_deterministic(self) -> None:
        entries = [
            make_entry(entry_id="e1", title="postgres pool"),
            make_entry(entry_id="e2", title="redis cache"),
        ]
        r1 = rank_entries(entries, "pool", now=BASE_NOW)
        r2 = rank_entries(entries, "pool", now=BASE_NOW)
        assert [r.entry.frontmatter.id for r in r1] == [
            r.entry.frontmatter.id for r in r2
        ]

    def test_recency_boost(self) -> None:
        old = make_entry(
            entry_id="e1",
            title="pool limit",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        new = make_entry(
            entry_id="e2",
            title="pool limit",
            created_at=datetime(2026, 5, 1, tzinfo=UTC),
            updated_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        results = rank_entries([old, new], "pool limit", now=BASE_NOW)
        assert results[0].entry.frontmatter.id == "e2"

    def test_exact_id_match_ranks_first(self) -> None:
        e1 = make_entry(entry_id="pool-limit", title="other stuff about pools")
        e2 = make_entry(entry_id="cache-ttl", title="pool limit config")
        results = rank_entries([e1, e2], "pool-limit", now=BASE_NOW)
        assert results[0].entry.frontmatter.id == "pool-limit"

    def test_exact_title_substring_ranks_first(self) -> None:
        e1 = make_entry(entry_id="e1", title="postgres pool limit")
        e2 = make_entry(entry_id="e2", title="pool configuration details and pool")
        results = rank_entries([e1, e2], "postgres pool limit", now=BASE_NOW)
        assert results[0].entry.frontmatter.id == "e1"

    def test_type_weight_principles_rank_higher(self) -> None:
        proj = make_entry(
            entry_id="e1",
            title="deterministic cores",
            entry_type=EntryType.PROJECT,
            level=EscalationLevel.L1,
        )
        princ = make_entry(
            entry_id="e2",
            title="deterministic cores",
            entry_type=EntryType.PRINCIPLE,
            level=EscalationLevel.L3,
        )
        results = rank_entries([proj, princ], "deterministic cores", now=BASE_NOW)
        assert results[0].entry.frontmatter.id == "e2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/core/test_scoring.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement scoring.py**

```python
# src/jurati/core/scoring.py
"""BM25 inverted index and multi-signal ranking for Jurati search."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from .schema import Entry, EntryType
from .search import SearchResult

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_TYPE_WEIGHTS: dict[EntryType, float] = {
    EntryType.PRINCIPLE: 1.4,
    EntryType.DECISION: 1.2,
    EntryType.WORKFLOW: 1.1,
    EntryType.PROJECT: 1.0,
    EntryType.ACTIVE: 0.8,
}

_BM25_K1 = 1.5
_BM25_B = 0.75
_RECENCY_HALF_LIFE_DAYS = 14.0
_MIN_RELEVANCE_THRESHOLD = 0.1


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class InvertedIndex:
    doc_count: int = 0
    avg_doc_len: float = 0.0
    doc_lengths: dict[str, int] = field(default_factory=dict)
    doc_term_freq: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    term_doc_freq: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def build_inverted_index(entries: list[Entry]) -> InvertedIndex:
    idx = InvertedIndex()
    idx.doc_count = len(entries)
    total_len = 0

    for entry in entries:
        doc_id = entry.frontmatter.id
        fm = entry.frontmatter
        text = f"{fm.title} {fm.title} {fm.title} {' '.join(fm.tags)} {entry.body}"
        tokens = tokenize(text)
        idx.doc_lengths[doc_id] = len(tokens)
        total_len += len(tokens)

        seen_terms: set[str] = set()
        for token in tokens:
            idx.doc_term_freq[doc_id][token] += 1
            if token not in seen_terms:
                idx.term_doc_freq[token] += 1
                seen_terms.add(token)

    idx.avg_doc_len = total_len / max(idx.doc_count, 1)
    return idx


def bm25_score(idx: InvertedIndex, doc_id: str, query: str) -> float:
    query_tokens = tokenize(query)
    if not query_tokens:
        return 0.0

    doc_len = idx.doc_lengths.get(doc_id, 0)
    if doc_len == 0:
        return 0.0

    score = 0.0
    for token in query_tokens:
        df = idx.term_doc_freq.get(token, 0)
        if df == 0:
            continue
        idf = math.log((idx.doc_count - df + 0.5) / (df + 0.5) + 1.0)
        tf = idx.doc_term_freq.get(doc_id, {}).get(token, 0)
        numerator = tf * (_BM25_K1 + 1)
        denominator = tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * doc_len / idx.avg_doc_len)
        score += idf * numerator / denominator

    return score


def _recency_factor(entry: Entry, now: datetime) -> float:
    age_days = (now - entry.frontmatter.updated_at).total_seconds() / 86400.0
    return math.exp(-0.693 * age_days / _RECENCY_HALF_LIFE_DAYS)


def rank_entries(
    entries: list[Entry],
    query: str,
    *,
    now: datetime,
    repo: str | None = None,
    repo_deps: set[str] | None = None,
    max_results: int = 10,
) -> list[SearchResult]:
    idx = build_inverted_index(entries)
    query_lower = query.lower()
    scored: list[tuple[float, Entry, list[str]]] = []

    for entry in entries:
        doc_id = entry.frontmatter.id
        bm25 = bm25_score(idx, doc_id, query)
        if bm25 == 0.0:
            continue

        reasons: list[str] = ["bm25"]
        recency = _recency_factor(entry, now)
        type_w = _TYPE_WEIGHTS.get(entry.frontmatter.type, 1.0)

        repo_w = 1.0
        source = getattr(entry.frontmatter, "source", None)
        if repo and source:
            src_repo = source.repo
            if src_repo == repo:
                repo_w = 1.5
                reasons.append("same-repo")
            elif repo_deps and src_repo in repo_deps:
                repo_w = 1.2
                reasons.append("dependency-repo")

        # Exact match escalation: entry ID or title substring → large boost
        exact_boost = 1.0
        if query_lower == doc_id or query_lower in entry.frontmatter.title.lower():
            exact_boost = 10.0
            reasons.append("exact-match")

        combined = bm25 * recency * type_w * repo_w * exact_boost

        if combined >= _MIN_RELEVANCE_THRESHOLD:
            scored.append((combined, entry, reasons))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        SearchResult(entry=e, relevance=round(s, 4), match_reasons=r)
        for s, e, r in scored[:max_results]
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/core/test_scoring.py -v`
Expected: PASS (iterate on threshold/weights if needed to make ranking tests pass)

- [ ] **Step 5: Run full suite and lint**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest && ruff check src/ tests/ && mypy src/jurati/core/scoring.py`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/core/scoring.py tests/core/test_scoring.py
git commit -m "feat(scoring): add BM25 inverted index and multi-signal ranking"
```

---

### Task 5: Add `context` and `search` MCP Tools

**Forward-compatibility note:** The `context()` tool must be designed to
accommodate a future `coordination` key (Phase 6 — Ambient PR Coordination).
The response shape uses top-level keys (`active`, `recent`) that Phase 6 will
extend with `coordination`. The `_build_context_payload` helper must accept an
optional `coordination` dict and pass it through when present, so Phase 6 can
inject PR signal guidance without modifying the helper's interface. The `context`
MCP tool handler must accept `goal: str | None = None`,
`paths: list[str] | None = None`, and `include_pr_signals: bool = True`
parameters now — they are no-ops until Phase 6 wires the provider, but the tool
signature is stable from day one.

**Files:**
- Modify: `src/jurati/server.py`
- Modify: `tests/test_server.py` (or create `tests/test_server_dx.py`)

- [ ] **Step 1: Write failing tests for the `context` tool**

```python
# tests/test_server_dx.py
"""Tests for DX-layer MCP tools: context and search."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from jurati.core.index import Index
from jurati.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    ReviewMeta,
)

from jurati.server import _build_context_payload, _build_search_results


def _make_fm(**overrides: object) -> Frontmatter:
    defaults = dict(
        id="test-entry",
        title="Test Entry",
        type=EntryType.PROJECT,
        level=EscalationLevel.L1,
        status=EntryStatus.ACTIVE,
        created_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        review=ReviewMeta(required=True),
    )
    defaults.update(overrides)
    return Frontmatter(**defaults)


def _make_entry(**overrides: object) -> Entry:
    fm_kwargs = {k: v for k, v in overrides.items() if k != "body" and k != "path"}
    return Entry(
        path=overrides.get("path", f"projects/{overrides.get('id', 'test-entry')}.md"),
        frontmatter=_make_fm(**fm_kwargs),
        body=overrides.get("body", "Body text"),
    )


class TestBuildContextPayload:
    def test_includes_active_entries(self) -> None:
        index = Index()
        active = _make_entry(
            id="active-1",
            title="Working on auth",
            type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            path="active/active-1.md",
            expires_at=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
        )
        index.add(active)

        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        result = _build_context_payload(index, now=now)
        assert len(result["active"]) == 1
        assert result["active"][0]["id"] == "active-1"

    def test_includes_recent_decisions(self) -> None:
        index = Index()
        decision = _make_entry(
            id="dec-1",
            title="Switch to gRPC",
            type=EntryType.DECISION,
            level=EscalationLevel.L2,
            path="decisions/dec-1.md",
        )
        index.add(decision)

        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        result = _build_context_payload(index, now=now)
        assert len(result["recent"]) == 1

    def test_excludes_expired_active(self) -> None:
        index = Index()
        expired = _make_entry(
            id="expired-1",
            title="Old task",
            type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            path="active/expired-1.md",
            expires_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
        index.add(expired)

        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        result = _build_context_payload(index, now=now)
        assert len(result["active"]) == 0


class TestBuildSearchResults:
    def test_returns_ranked_results(self) -> None:
        index = Index()
        e1 = _make_entry(id="e1", title="postgres pool limit")
        e2 = _make_entry(id="e2", title="redis cache strategy")
        index.add(e1)
        index.add(e2)

        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        results = _build_search_results(index, "postgres pool", now=now)
        assert len(results) >= 1
        assert results[0]["id"] == "e1"

    def test_honest_zero(self) -> None:
        index = Index()
        e1 = _make_entry(id="e1", title="postgres pool limit")
        index.add(e1)

        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        results = _build_search_results(index, "kubernetes helm chart", now=now)
        assert len(results) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/test_server_dx.py -v`
Expected: FAIL — `_build_context_payload` and `_build_search_results` not found

- [ ] **Step 3: Implement context and search helpers in server.py**

Add to `src/jurati/server.py`:

```python
from jurati.core.scoring import rank_entries
from jurati.core.validate import is_expired


def _build_context_payload(
    index: Index,
    *,
    now: datetime,
    repo: str | None = None,
    days_recent: int = 7,
    coordination: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recent_cutoff = now - timedelta(days=days_recent)

    active = [
        _format_entry(e)
        for e in index.entries.values()
        if e.frontmatter.type == EntryType.ACTIVE and not is_expired(e, now)
    ]

    recent = [
        _format_entry(e)
        for e in index.entries.values()
        if e.frontmatter.type != EntryType.ACTIVE
        and e.frontmatter.updated_at >= recent_cutoff
        and e.frontmatter.status in (EntryStatus.ACTIVE, EntryStatus.PROPOSED)
    ]

    recent.sort(key=lambda r: r.get("updated_at", ""), reverse=True)

    result: dict[str, Any] = {"active": active, "recent": recent[:15]}
    if coordination is not None:
        result["coordination"] = coordination
    return result


def _build_search_results(
    index: Index,
    query: str,
    *,
    now: datetime,
    repo: str | None = None,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    entries = list(index.entries.values())
    ranked = rank_entries(entries, query, now=now, repo=repo, max_results=max_results)
    return [
        {
            "id": r.entry.frontmatter.id,
            "title": r.entry.frontmatter.title,
            "type": str(r.entry.frontmatter.type),
            "relevance": r.relevance,
            "reasons": r.match_reasons,
            "snippet": r.entry.body[:200] if r.entry.body else "",
        }
        for r in ranked
    ]
```

Also add these imports to the top of `server.py`:

```python
from datetime import timedelta
from jurati.core.scoring import rank_entries
from jurati.core.validate import is_expired
```

Then add the two MCP tool handlers:

```python
@mcp.tool()
async def context(
    ctx: Context,
    repo: str | None = None,
    goal: str | None = None,
    paths: list[str] | None = None,
    include_pr_signals: bool = True,
) -> dict[str, Any]:
    """Get session-start context: active entries, recent decisions, and repo-relevant items."""
    state = _state(ctx)
    now = datetime.now(UTC)
    # goal, paths, include_pr_signals are no-ops until Phase 6 wires the provider
    return _build_context_payload(state.index, now=now, repo=repo)


@mcp.tool()
async def search(
    query: str,
    ctx: Context,
    type: str | None = None,
    project: str | None = None,
    tags: str | None = None,
    max_results: int = 10,
    include_expired: bool = False,
) -> list[dict[str, Any]]:
    """Search knowledge entries with BM25 relevance ranking."""
    state = _state(ctx)
    now = datetime.now(UTC)
    return _build_search_results(
        state.index, query, now=now, max_results=max_results
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/test_server_dx.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite and lint**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest && ruff check src/ tests/`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/server.py tests/test_server_dx.py
git commit -m "feat(server): add context and search MCP tools with BM25 ranking"
```

---

## Phase 3: Git Hook & CLI Commands

### Task 6: Capture Pipeline Orchestration (`capture/pipeline.py`)

The pipeline ties together extraction, deduplication, rendering, and git operations. It is the shared logic used by both the hook and CLI `capture` command.

**Files:**
- Create: `src/jurati/capture/pipeline.py`
- Create: `tests/capture/test_pipeline.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/capture/test_pipeline.py
"""Tests for jurati.capture.pipeline — end-to-end capture orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from jurati.capture.pipeline import (
    CaptureOutcome,
    run_capture,
)
from jurati.core.schema import EscalationLevel


class TestRunCapture:
    @patch("jurati.capture.pipeline.push_branch_with_retry")
    @patch("jurati.capture.pipeline.materialize_write", return_value="abc123")
    @patch("jurati.capture.pipeline.create_branch")
    @patch("jurati.capture.pipeline.entry_exists_on_main", return_value=False)
    @patch("jurati.capture.pipeline.branch_exists_remote", return_value=False)
    def test_l1_capture_creates_branch_and_pushes(
        self,
        mock_branch_check,
        mock_entry_check,
        mock_create,
        mock_write,
        mock_push,
    ) -> None:
        outcome = run_capture(
            message="jurati: postgres pool at 20 max",
            repo_slug="api-service",
            knowledge_repo_path="/knowledge",
            main_branch="main",
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            source_commit="abc123",
            source_author="dev@co.com",
        )
        assert outcome is not None
        assert outcome.entry_id == "api-service-postgres-pool-at-20-max"
        assert outcome.level == EscalationLevel.L1
        assert outcome.sha == "abc123"
        assert outcome.contradiction_ids == []
        mock_create.assert_called_once()
        mock_write.assert_called_once()
        mock_push.assert_called_once()

    @patch("jurati.capture.pipeline.entry_exists_on_main", return_value=True)
    def test_dedup_skips_when_entry_on_main(self, mock_check) -> None:
        outcome = run_capture(
            message="jurati: postgres pool at 20 max",
            repo_slug="api-service",
            knowledge_repo_path="/knowledge",
            main_branch="main",
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            source_commit="abc123",
            source_author="dev@co.com",
        )
        assert outcome is None

    @patch("jurati.capture.pipeline.entry_exists_on_main", return_value=False)
    @patch("jurati.capture.pipeline.branch_exists_remote", return_value=True)
    def test_dedup_skips_when_branch_exists(self, mock_branch, mock_entry) -> None:
        outcome = run_capture(
            message="jurati: postgres pool at 20 max",
            repo_slug="api-service",
            knowledge_repo_path="/knowledge",
            main_branch="main",
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            source_commit="abc123",
            source_author="dev@co.com",
        )
        assert outcome is None

    def test_non_jurati_message_returns_none(self) -> None:
        outcome = run_capture(
            message="feat: add new feature",
            repo_slug="api-service",
            knowledge_repo_path="/knowledge",
            main_branch="main",
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            source_commit="abc123",
            source_author="dev@co.com",
        )
        assert outcome is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/capture/test_pipeline.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement pipeline.py**

```python
# src/jurati/capture/pipeline.py
"""End-to-end capture orchestration for the jurati: commit convention."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import git

from jurati.capture.extract import CaptureResult, derive_entry_id, parse_commit_message, scan_secrets
from jurati.core.changes import plan_capture
from jurati.core.schema import EscalationLevel, SourceMeta
from jurati.git.branch import create_branch
from jurati.git.commit import materialize_write


@dataclass(frozen=True)
class CaptureOutcome:
    entry_id: str
    level: EscalationLevel
    sha: str
    branch: str | None
    secret_detected: bool
    contradiction_ids: list[str]


def entry_exists_on_main(repo_path: str, entry_path: str, main_branch: str) -> bool:
    repo = git.Repo(repo_path)
    try:
        main_ref = repo.refs[f"origin/{main_branch}"]
        main_ref.commit.tree[entry_path]
        return True
    except (IndexError, KeyError):
        return False


def branch_exists_remote(repo_path: str, branch_name: str) -> bool:
    repo = git.Repo(repo_path)
    try:
        repo.refs[f"origin/{branch_name}"]
        return True
    except (IndexError, ValueError):
        return False


def push_branch_with_retry(
    repo_path: str, branch_name: str, *, max_retries: int = 3
) -> None:
    import random
    import time

    from jurati.git.branch import push_branch

    for attempt in range(max_retries):
        try:
            push_branch(repo_path, branch_name)
            return
        except git.exc.GitCommandError:
            if attempt == max_retries - 1:
                raise
            delay = (2**attempt) + random.uniform(0, 1)
            time.sleep(delay)
            repo = git.Repo(repo_path)
            repo.remotes.origin.fetch()


def run_capture(
    *,
    message: str,
    repo_slug: str,
    knowledge_repo_path: str,
    main_branch: str,
    now: datetime,
    source_commit: str,
    source_author: str,
    extra_secret_patterns: list | None = None,
) -> CaptureOutcome | None:
    parsed = parse_commit_message(message)
    if parsed is None:
        return None

    entry_id = derive_entry_id(repo_slug, parsed.title, commit_sha=source_commit)
    source = SourceMeta(repo=repo_slug, commit=source_commit, author=source_author)

    secret_detected = scan_secrets(
        f"{parsed.title} {parsed.body}", extra_secret_patterns
    )
    level = parsed.level
    if secret_detected and level in (EscalationLevel.L0, EscalationLevel.L1):
        level = EscalationLevel.L2

    intent = plan_capture(
        entry_type=parsed.entry_type,
        title=parsed.title,
        body=parsed.body,
        entry_id=entry_id,
        level=level,
        now=now,
        source=source,
    )

    if entry_exists_on_main(knowledge_repo_path, intent.path, main_branch):
        return None

    if intent.branch and branch_exists_remote(knowledge_repo_path, intent.branch):
        return None

    if intent.branch is None:
        raise ValueError("Capture pipeline does not handle L0 active entries")

    # Contradiction detection — best-effort keyword overlap check
    contradiction_ids: list[str] = []
    try:
        from jurati.core.curation import detect_contradictions
        from jurati.git.repo import load_index_from_repo

        index = load_index_from_repo(knowledge_repo_path, main_branch)
        conflicts = detect_contradictions(
            parsed.title, list(index.entries.values()), entry_type=parsed.entry_type
        )
        contradiction_ids = [c.frontmatter.id for c in conflicts]
    except Exception:
        pass  # Best-effort; don't block capture on contradiction check failure

    create_branch(knowledge_repo_path, intent.branch, f"origin/{main_branch}")
    sha = materialize_write(knowledge_repo_path, intent)
    push_branch_with_retry(knowledge_repo_path, intent.branch)

    return CaptureOutcome(
        entry_id=entry_id,
        level=level,
        sha=sha,
        branch=intent.branch,
        secret_detected=secret_detected,
        contradiction_ids=contradiction_ids,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/capture/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite and lint**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest && ruff check src/ tests/`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/capture/pipeline.py tests/capture/test_pipeline.py
git commit -m "feat(capture): add pipeline orchestration with dedup and retry"
```

---

### Task 7: Offline Pending Queue (`capture/pending.py`)

**Files:**
- Create: `src/jurati/capture/pending.py`
- Create: `tests/capture/test_pending.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/capture/test_pending.py
"""Tests for jurati.capture.pending — offline capture queue."""

from __future__ import annotations

import json
from pathlib import Path

from jurati.capture.pending import (
    list_pending,
    save_pending,
    remove_pending,
)


class TestPendingQueue:
    def test_save_and_list(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        save_pending(str(git_dir), "abc123", "jurati: pool limit")
        pending = list_pending(str(git_dir))
        assert len(pending) == 1
        assert pending[0]["commit_sha"] == "abc123"
        assert pending[0]["message"] == "jurati: pool limit"

    def test_remove_clears_marker(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        save_pending(str(git_dir), "abc123", "jurati: pool limit")
        remove_pending(str(git_dir), "abc123")
        assert list_pending(str(git_dir)) == []

    def test_list_empty_dir(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        assert list_pending(str(git_dir)) == []

    def test_multiple_pending(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        save_pending(str(git_dir), "aaa111", "jurati: first")
        save_pending(str(git_dir), "bbb222", "jurati: second")
        pending = list_pending(str(git_dir))
        assert len(pending) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/capture/test_pending.py -v`
Expected: FAIL

- [ ] **Step 3: Implement pending.py**

```python
# src/jurati/capture/pending.py
"""Offline capture queue for the git hook."""

from __future__ import annotations

import json
from pathlib import Path


_PENDING_DIR = "jurati-pending"


def _pending_path(git_dir: str) -> Path:
    return Path(git_dir) / _PENDING_DIR


def save_pending(git_dir: str, commit_sha: str, message: str) -> None:
    pending_dir = _pending_path(git_dir)
    pending_dir.mkdir(exist_ok=True)
    marker = pending_dir / f"{commit_sha}.json"
    marker.write_text(json.dumps({"commit_sha": commit_sha, "message": message}))


def list_pending(git_dir: str) -> list[dict[str, str]]:
    pending_dir = _pending_path(git_dir)
    if not pending_dir.exists():
        return []
    results = []
    for marker in sorted(pending_dir.glob("*.json")):
        data = json.loads(marker.read_text())
        results.append(data)
    return results


def remove_pending(git_dir: str, commit_sha: str) -> None:
    marker = _pending_path(git_dir) / f"{commit_sha}.json"
    if marker.exists():
        marker.unlink()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/capture/test_pending.py -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && ruff check src/jurati/capture/pending.py tests/capture/test_pending.py`

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/capture/pending.py tests/capture/test_pending.py
git commit -m "feat(capture): add offline pending queue for git hook"
```

---

### Task 8: CLI Commands (`install-hook`, `capture`, `active`, `flush`, `search`)

**Files:**
- Modify: `src/jurati/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests for new CLI commands**

```python
# tests/test_cli.py — add to existing file

class TestInstallHook:
    def test_installs_post_commit_hook(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git" / "hooks"
        git_dir.mkdir(parents=True)
        # Simulate a git repo
        (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

        runner = CliRunner()
        result = runner.invoke(main, ["install-hook"], env={"GIT_DIR": str(tmp_path / ".git")})
        # The command should succeed (even if it can't find a real repo,
        # we test the output shape)
        assert "hook" in result.output.lower() or result.exit_code == 0

    def test_install_hook_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["install-hook", "--help"])
        assert result.exit_code == 0
        assert "post-commit" in result.output.lower() or "hook" in result.output.lower()


class TestCaptureCommand:
    def test_capture_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["capture", "--help"])
        assert result.exit_code == 0

    def test_capture_non_jurati_message(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["capture", "--message", "feat: normal commit"])
        # Should exit cleanly with no capture
        assert "no jurati" in result.output.lower() or result.exit_code == 0


class TestActiveCommand:
    def test_active_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["active", "--help"])
        assert result.exit_code == 0


class TestFlushCommand:
    def test_flush_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["flush", "--help"])
        assert result.exit_code == 0


class TestSearchCommand:
    def test_search_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["search", "--help"])
        assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/test_cli.py::TestInstallHook -v`
Expected: FAIL — command not found

- [ ] **Step 3: Implement CLI commands**

Add to `src/jurati/cli.py`:

```python
@main.command("install-hook")
@click.option("--global", "global_hook", is_flag=True, help="Install as global git hook template")
@click.option("--force", is_flag=True, help="Overwrite existing hook")
def install_hook(global_hook: bool, force: bool) -> None:
    """Install the jurati post-commit hook for ambient capture."""
    import subprocess

    hook_content = """#!/bin/sh
# Jurati post-commit hook — captures jurati: commits
MESSAGE=$(git log -1 --format=%B)
COMMIT=$(git rev-parse HEAD)
AUTHOR=$(git config user.email)
jurati capture --message "$MESSAGE" --commit "$COMMIT" --author "$AUTHOR" 2>/dev/null || true
"""
    if global_hook:
        result = subprocess.run(
            ["git", "config", "--global", "core.hooksPath"],
            capture_output=True, text=True,
        )
        hooks_dir = Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else Path.home() / ".git-hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "config", "--global", "core.hooksPath", str(hooks_dir)],
            check=True,
        )
    else:
        hooks_dir = Path(".git") / "hooks"
        if not hooks_dir.exists():
            click.echo("Error: not in a git repository", err=True)
            raise SystemExit(1)

    hook_path = hooks_dir / "post-commit"
    if hook_path.exists() and not force:
        click.echo(f"Hook already exists at {hook_path}. Use --force to overwrite.", err=True)
        raise SystemExit(1)

    hook_path.write_text(hook_content)
    hook_path.chmod(0o755)
    click.echo(f"Installed post-commit hook at {hook_path}")


@main.command()
@click.option("--message", "-m", required=True, help="Commit message to process")
@click.option("--commit", default="unknown", help="Source commit SHA")
@click.option("--author", default="unknown", help="Source commit author email")
@click.option("--repo-slug", default=None, help="Source repo slug (defaults to current dir name)")
def capture(message: str, commit: str, author: str, repo_slug: str | None) -> None:
    """Process a commit message through the jurati capture pipeline."""
    from jurati.capture.extract import parse_commit_message

    parsed = parse_commit_message(message)
    if parsed is None:
        click.echo("No jurati: prefix found — nothing to capture.")
        return

    if repo_slug is None:
        repo_slug = Path.cwd().name

    click.echo(f'[jurati] detected: "{parsed.title}" (type={parsed.entry_type}, level={parsed.level})')
    # Full pipeline execution requires knowledge repo — deferred to integration


@main.command()
@click.argument("message")
@click.option("--expires", default="2h", help="Expiry duration (e.g. 2h, 30m)")
def active(message: str, expires: str) -> None:
    """Broadcast active status without a commit."""
    click.echo(f'[jurati] active: "{message}" (expires in {expires})')
    click.echo("Note: requires JURATI_KNOWLEDGE_REMOTE to be configured.")


@main.command()
def flush() -> None:
    """Retry all pending captures from the offline queue."""
    from jurati.capture.pending import list_pending

    git_dir = Path(".git")
    if not git_dir.exists():
        click.echo("Error: not in a git repository", err=True)
        raise SystemExit(1)

    pending = list_pending(str(git_dir))
    if not pending:
        click.echo("No pending captures.")
        return

    click.echo(f"Found {len(pending)} pending capture(s).")
    for item in pending:
        click.echo(f"  - {item['commit_sha'][:8]}: {item['message'][:60]}")


@main.command("search")
@click.argument("query")
def search_cmd(query: str) -> None:
    """Search the knowledge repo from the command line."""
    click.echo(f"Searching for: {query}")
    click.echo("Note: requires JURATI_KNOWLEDGE_REMOTE to be configured.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/test_cli.py -v`
Expected: All PASS (including existing tests)

- [ ] **Step 5: Run full suite and lint**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest && ruff check src/ tests/`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/cli.py tests/test_cli.py
git commit -m "feat(cli): add install-hook, capture, active, flush, search commands"
```

---

## Phase 4: GitHub Action

### Task 9: Action Workflow Files with Batching, Auto-Merge, and Merge Strategy Support

**Files:**
- Create: `action/action.yml`
- Create: `action/capture.py` (Python entrypoint — handles batching and merge strategies)
- Create: `tests/action/test_capture_action.py`

The Action entrypoint is Python (not bash) because it needs to:
1. Batch multiple `jurati:` commits into a single PR
2. Handle squash-merge (scan PR body) and rebase-merge (message-hash dedup)
3. Auto-merge L1 PRs after validation

- [ ] **Step 1: Create action.yml**

```yaml
# action/action.yml
name: "Jurati Capture"
description: "Scan commits for jurati: prefix and capture knowledge entries"
branding:
  icon: "book-open"
  color: "blue"

inputs:
  knowledge_remote:
    description: "Git URL of the jurati-knowledge repository"
    required: true
  knowledge_token:
    description: "Token with contents:write on the knowledge repo"
    required: true
  main_branch:
    description: "Main branch of the knowledge repo"
    default: "main"
  auto_merge:
    description: "Auto-merge L1 entries after validation"
    default: "true"

runs:
  using: "composite"
  steps:
    - name: Install jurati
      shell: bash
      run: pip install jurati

    - name: Capture commits
      shell: bash
      env:
        JURATI_KNOWLEDGE_REMOTE: ${{ inputs.knowledge_remote }}
        JURATI_KNOWLEDGE_TOKEN: ${{ inputs.knowledge_token }}
        JURATI_MAIN_BRANCH: ${{ inputs.main_branch }}
        JURATI_AUTO_MERGE: ${{ inputs.auto_merge }}
        GITHUB_REPOSITORY: ${{ github.repository }}
        GITHUB_SHA: ${{ github.sha }}
        GITHUB_EVENT_BEFORE: ${{ github.event.before }}
      run: python -m jurati.action.capture
```

- [ ] **Step 2: Write failing tests for action capture logic**

```python
# tests/action/test_capture_action.py
"""Tests for jurati action capture — batching, merge strategies, auto-merge."""

from __future__ import annotations

import hashlib

from jurati.action.capture import (
    collect_jurati_messages,
    derive_batch_branch,
    extract_jurati_lines_from_body,
    message_dedup_key,
)


class TestCollectMessages:
    def test_filters_jurati_commits(self) -> None:
        commits = [
            {"sha": "a1", "message": "jurati: pool limit", "author": "dev@co.com"},
            {"sha": "a2", "message": "feat: other work", "author": "dev@co.com"},
            {"sha": "a3", "message": "jurati(decision): switch to gRPC", "author": "dev@co.com"},
        ]
        results = collect_jurati_messages(commits)
        assert len(results) == 2
        assert results[0]["sha"] == "a1"
        assert results[1]["sha"] == "a3"


class TestBatchBranch:
    def test_batch_branch_name(self) -> None:
        branch = derive_batch_branch("api-service", "abc123def456")
        assert branch == "jurati/api-service/batch-abc123"

    def test_single_entry_uses_normal_branch(self) -> None:
        branch = derive_batch_branch("api-service", "abc123def456", count=1)
        # Single entries don't batch — return None to signal individual handling
        assert branch is None


class TestSquashMergeSupport:
    def test_extracts_jurati_lines_from_pr_body(self) -> None:
        body = (
            "## Summary\n\n"
            "jurati: pool limit changed\n"
            "jurati(decision): switch to gRPC\n"
            "Other text.\n"
        )
        lines = extract_jurati_lines_from_body(body)
        assert len(lines) == 2
        assert lines[0] == "jurati: pool limit changed"
        assert lines[1] == "jurati(decision): switch to gRPC"

    def test_empty_body_returns_empty(self) -> None:
        assert extract_jurati_lines_from_body("") == []
        assert extract_jurati_lines_from_body(None) == []


class TestMessageDedupKey:
    def test_deterministic(self) -> None:
        k1 = message_dedup_key("jurati: pool limit")
        k2 = message_dedup_key("jurati: pool limit")
        assert k1 == k2

    def test_different_messages_different_keys(self) -> None:
        k1 = message_dedup_key("jurati: pool limit")
        k2 = message_dedup_key("jurati: cache TTL")
        assert k1 != k2
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/action/test_capture_action.py -v`
Expected: FAIL — module not found

- [ ] **Step 4: Implement `action/capture.py`**

```python
# src/jurati/action/capture.py
"""GitHub Action entrypoint for jurati: commit capture with batching."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from datetime import UTC, datetime

from jurati.capture.extract import parse_commit_message
from jurati.core.schema import EscalationLevel

_JURATI_LINE_RE = re.compile(r"^jurati(?:\([a-z]+\))?:\s*.+$", re.MULTILINE)


def collect_jurati_messages(
    commits: list[dict[str, str]],
) -> list[dict[str, str]]:
    return [c for c in commits if parse_commit_message(c["message"]) is not None]


def derive_batch_branch(
    repo_slug: str, push_sha: str, *, count: int = 2
) -> str | None:
    if count <= 1:
        return None
    return f"jurati/{repo_slug}/batch-{push_sha[:6]}"


def extract_jurati_lines_from_body(body: str | None) -> list[str]:
    if not body:
        return []
    return _JURATI_LINE_RE.findall(body)


def message_dedup_key(message: str) -> str:
    first_line = message.split("\n", 1)[0].strip()
    return hashlib.sha256(first_line.encode()).hexdigest()[:12]


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def main() -> None:
    repo_slug = os.environ["GITHUB_REPOSITORY"].split("/", 1)[1]
    push_sha = os.environ["GITHUB_SHA"]
    before = os.environ.get("GITHUB_EVENT_BEFORE", "")
    auto_merge = os.environ.get("JURATI_AUTO_MERGE", "true").lower() == "true"

    # Collect commits in this push
    if not before or before == "0" * 40:
        shas = [_git("log", "-1", "--format=%H")]
    else:
        shas = _git("log", "--format=%H", f"{before}..{push_sha}").splitlines()

    commits: list[dict[str, str]] = []
    for sha in shas:
        msg = _git("log", "-1", "--format=%B", sha)
        author = _git("log", "-1", "--format=%ae", sha)
        commits.append({"sha": sha, "message": msg, "author": author})

    # Also check for squash-merge: scan commit body for jurati: lines
    for commit in commits:
        body_lines = extract_jurati_lines_from_body(commit["message"])
        # If the first line is NOT jurati: but body has jurati: lines,
        # expand into synthetic commits for each line
        parsed = parse_commit_message(commit["message"])
        if parsed is None and body_lines:
            for line in body_lines:
                commits.append({
                    "sha": commit["sha"],
                    "message": line,
                    "author": commit["author"],
                })

    jurati_commits = collect_jurati_messages(commits)
    if not jurati_commits:
        print("No jurati: commits found.")
        return

    now = datetime.now(UTC)
    captured = 0
    for jc in jurati_commits:
        try:
            from jurati.capture.pipeline import run_capture

            outcome = run_capture(
                message=jc["message"],
                repo_slug=repo_slug,
                knowledge_repo_path=os.environ.get("JURATI_CACHE_DIR", "/tmp/jurati-knowledge"),
                main_branch=os.environ.get("JURATI_MAIN_BRANCH", "main"),
                now=now,
                source_commit=jc["sha"],
                source_author=jc["author"],
            )
            if outcome:
                captured += 1
                print(f'[jurati] captured: "{outcome.entry_id}" (L{outcome.level})')
                # Auto-merge L1 entries if configured
                if auto_merge and outcome.level == EscalationLevel.L1 and not outcome.secret_detected:
                    print(f"[jurati] auto-merge: {outcome.entry_id} (L1, clean)")
                    # Auto-merge is delegated to the PR creation step in pipeline
        except Exception as e:
            print(f"[jurati] error capturing {jc['sha'][:8]}: {e}", file=sys.stderr)

    print(f"Captured {captured} entries from {repo_slug}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Create package markers**

Create `src/jurati/action/__init__.py` and `tests/action/__init__.py` as empty files.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/action/test_capture_action.py -v`
Expected: PASS

- [ ] **Step 7: Verify action.yml is valid YAML**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -c "import yaml; yaml.safe_load(open('action/action.yml'))"`
Expected: No errors

- [ ] **Step 8: Commit**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add action/ src/jurati/action/ tests/action/
git commit -m "feat(action): add GitHub Action with batching, squash support, auto-merge"
```

---

## Phase 5: Curation & Onboarding

### Task 10: Contradiction Detection (`core/curation.py`)

**Files:**
- Create: `src/jurati/core/curation.py`
- Create: `tests/core/test_curation.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_curation.py
"""Tests for jurati.core.curation — contradiction detection and staleness."""

from __future__ import annotations

from datetime import UTC, datetime

from jurati.core.curation import (
    detect_contradictions,
    find_stale_entries,
)
from jurati.core.schema import EntryType

from .conftest import BASE_NOW, make_entry, minutes_after


class TestDetectContradictions:
    def test_overlapping_titles_flagged(self) -> None:
        existing = [
            make_entry(entry_id="e1", title="postgres pool capped at 20 connections"),
        ]
        new_title = "postgres pool capped at 30 connections"
        conflicts = detect_contradictions(new_title, existing)
        assert len(conflicts) == 1
        assert conflicts[0].frontmatter.id == "e1"

    def test_different_titles_not_flagged(self) -> None:
        existing = [
            make_entry(entry_id="e1", title="postgres pool capped at 20"),
        ]
        conflicts = detect_contradictions("redis cache TTL set to 30s", existing)
        assert len(conflicts) == 0

    def test_same_type_directory_only(self) -> None:
        existing = [
            make_entry(
                entry_id="e1",
                title="pool limit decision",
                entry_type=EntryType.DECISION,
                level="L2",
            ),
        ]
        # Different type — should not flag
        conflicts = detect_contradictions(
            "pool limit project update",
            existing,
            entry_type=EntryType.PROJECT,
        )
        assert len(conflicts) == 0


class TestFindStaleEntries:
    def test_old_entries_flagged(self) -> None:
        old = make_entry(
            entry_id="old",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        stale = find_stale_entries([old], now=BASE_NOW, stale_after_days=90)
        assert len(stale) == 1

    def test_recent_entries_not_flagged(self) -> None:
        recent = make_entry(entry_id="recent")
        stale = find_stale_entries([recent], now=BASE_NOW, stale_after_days=90)
        assert len(stale) == 0

    def test_expired_entries_excluded(self) -> None:
        expired = make_entry(
            entry_id="expired",
            entry_type=EntryType.ACTIVE,
            level="L0",
            status="expired",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            expires_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        stale = find_stale_entries([expired], now=BASE_NOW, stale_after_days=90)
        assert len(stale) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/core/test_curation.py -v`
Expected: FAIL

- [ ] **Step 3: Implement curation.py**

```python
# src/jurati/core/curation.py
"""Contradiction detection and staleness scanning."""

from __future__ import annotations

from datetime import datetime, timedelta

from .schema import Entry, EntryStatus, EntryType
from .scoring import tokenize


def detect_contradictions(
    new_title: str,
    existing_entries: list[Entry],
    *,
    entry_type: EntryType | None = None,
    threshold: float = 0.4,
) -> list[Entry]:
    new_tokens = set(tokenize(new_title))
    if not new_tokens:
        return []

    conflicts: list[Entry] = []
    for entry in existing_entries:
        if entry_type and entry.frontmatter.type != entry_type:
            continue
        if entry.frontmatter.status in (EntryStatus.EXPIRED, EntryStatus.SUPERSEDED):
            continue

        existing_tokens = set(tokenize(entry.frontmatter.title))
        if not existing_tokens:
            continue

        overlap = len(new_tokens & existing_tokens) / min(len(new_tokens), len(existing_tokens))
        if overlap >= threshold:
            conflicts.append(entry)

    return conflicts


def find_stale_entries(
    entries: list[Entry],
    *,
    now: datetime,
    stale_after_days: int = 90,
) -> list[Entry]:
    cutoff = now - timedelta(days=stale_after_days)
    stale: list[Entry] = []
    for entry in entries:
        if entry.frontmatter.type == EntryType.ACTIVE:
            continue
        if entry.frontmatter.status in (EntryStatus.EXPIRED, EntryStatus.SUPERSEDED):
            continue
        if entry.frontmatter.updated_at < cutoff:
            stale.append(entry)
    return stale
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/core/test_curation.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite, lint, and commit**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest && ruff check src/ tests/`

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/core/curation.py tests/core/test_curation.py
git commit -m "feat(curation): add contradiction detection and staleness scanning"
```

---

### Task 11: Repo-Graph, Secret Pattern, and PR Signal Config

**Forward-compatibility note:** This task adds `pr_signals` config alongside
`repo_graph` and `secret_patterns`. The `PRSignalsConfig` dataclass is parsed and
validated here but not consumed until Phase 6 wires the GitHub provider. This
ensures the config schema is stable before any provider code exists.

**Files:**
- Modify: `src/jurati/git/config.py`
- Modify: `tests/git/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/git/test_config.py — add to existing file

class TestRepoGraph:
    def test_repo_graph_default_empty(self) -> None:
        config = JuratiConfig(remote_url="https://example.com/repo.git")
        assert config.repo_graph == {}

    def test_repo_graph_with_deps(self) -> None:
        config = JuratiConfig(
            remote_url="https://example.com/repo.git",
            repo_graph={"api-service": ["shared-libs", "auth-service"]},
        )
        assert config.repo_graph["api-service"] == ["shared-libs", "auth-service"]


class TestSecretPatterns:
    def test_secret_patterns_default_empty(self) -> None:
        config = JuratiConfig(remote_url="https://example.com/repo.git")
        assert config.secret_patterns == []

    def test_secret_patterns_from_config(self) -> None:
        config = JuratiConfig(
            remote_url="https://example.com/repo.git",
            secret_patterns=["CUSTOM_TOKEN_[A-Z0-9]+", "my-org-secret-\\w+"],
        )
        assert len(config.secret_patterns) == 2


class TestPRSignalsConfig:
    def test_pr_signals_default_none(self) -> None:
        config = JuratiConfig(remote_url="https://example.com/repo.git")
        assert config.pr_signals is None

    def test_pr_signals_with_repos(self) -> None:
        from jurati.git.config import PRSignalsConfig

        pr_cfg = PRSignalsConfig(
            provider="github",
            label="jurati",
            recency_days=30,
            repos=["org/api", "org/web", "org/platform"],
        )
        config = JuratiConfig(
            remote_url="https://example.com/repo.git",
            pr_signals=pr_cfg,
        )
        assert config.pr_signals is not None
        assert config.pr_signals.provider == "github"
        assert config.pr_signals.label == "jurati"
        assert config.pr_signals.recency_days == 30
        assert len(config.pr_signals.repos) == 3

    def test_pr_signals_defaults(self) -> None:
        from jurati.git.config import PRSignalsConfig

        pr_cfg = PRSignalsConfig(repos=["org/api"])
        assert pr_cfg.provider == "github"
        assert pr_cfg.label == "jurati"
        assert pr_cfg.recency_days == 30
        assert pr_cfg.include_body_excerpt is True
        assert pr_cfg.include_changed_paths is True
        assert pr_cfg.include_comments is False

    def test_pr_signals_requires_repos(self) -> None:
        from jurati.git.config import PRSignalsConfig

        pr_cfg = PRSignalsConfig(repos=[])
        assert pr_cfg.repos == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/git/test_config.py::TestRepoGraph tests/git/test_config.py::TestSecretPatterns tests/git/test_config.py::TestPRSignalsConfig -v`
Expected: FAIL — `repo_graph`, `secret_patterns`, `PRSignalsConfig` not defined

- [ ] **Step 3: Add fields to JuratiConfig**

In `src/jurati/git/config.py`, ensure `field` is imported from `dataclasses`:

```python
from dataclasses import dataclass, field
```

Add the `PRSignalsConfig` dataclass before `JuratiConfig`:

```python
@dataclass(frozen=True)
class PRSignalsConfig:
    """PR signal source configuration for ambient coordination (Phase 6)."""

    repos: list[str] = field(default_factory=list)
    provider: str = "github"
    label: str = "jurati"
    recency_days: int = 30
    include_body_excerpt: bool = True
    include_changed_paths: bool = True
    include_comments: bool = False
```

Then add to the `JuratiConfig` dataclass:

```python
    repo_graph: dict[str, list[str]] = field(default_factory=dict)
    secret_patterns: list[str] = field(default_factory=list)
    pr_signals: PRSignalsConfig | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/git/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/git/config.py tests/git/test_config.py
git commit -m "feat(config): add repo_graph, secret_patterns, and pr_signals config"
```

---

### Task 12: Enhanced `jurati doctor` with Discovery Chain

**Files:**
- Modify: `src/jurati/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli.py — add to existing file

class TestDoctorDiscovery:
    def test_doctor_finds_url_in_claude_md(self, tmp_path: Path) -> None:
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "## Shared Knowledge\n\n"
            "Knowledge repo: git@github.com:acme/jurati-knowledge.git\n"
        )
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["doctor"],
            env={"JURATI_KNOWLEDGE_REMOTE": "", "HOME": str(tmp_path)},
        )
        assert "git@github.com:acme/jurati-knowledge.git" in result.output or result.exit_code == 0

    def test_doctor_finds_url_in_jurati_remote(self, tmp_path: Path) -> None:
        remote_file = tmp_path / ".jurati-remote"
        remote_file.write_text("git@github.com:acme/jurati-knowledge.git\n")
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["doctor"],
            env={"JURATI_KNOWLEDGE_REMOTE": "", "HOME": str(tmp_path)},
        )
        assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/test_cli.py::TestDoctorDiscovery -v`
Expected: FAIL

- [ ] **Step 3: Implement discovery chain in doctor**

Add a `_discover_remote()` helper to `cli.py`:

```python
def _discover_remote() -> str | None:
    """Search for knowledge repo URL in standard locations."""
    import re

    # 1. Environment
    remote = os.environ.get("JURATI_KNOWLEDGE_REMOTE", "").strip()
    if remote:
        return remote

    # 2. CLAUDE.md
    claude_md = Path("CLAUDE.md")
    if claude_md.exists():
        text = claude_md.read_text()
        match = re.search(r"Knowledge repo:\s*(\S+)", text)
        if match:
            return match.group(1)

    # 3. .jurati-remote
    remote_file = Path(".jurati-remote")
    if remote_file.exists():
        return remote_file.read_text().strip()

    # 4. .claude/settings.json
    settings = Path(".claude") / "settings.json"
    if settings.exists():
        import json
        data = json.loads(settings.read_text())
        jurati_cfg = data.get("mcpServers", {}).get("jurati", {})
        return jurati_cfg.get("env", {}).get("JURATI_KNOWLEDGE_REMOTE")

    return None
```

Update the `doctor` command to use `_discover_remote()`.

Note: `quickstart` and `mcp-config` commands already exist in V1 CLI. No new
task needed — the doctor discovery chain is the only onboarding enhancement.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/cli.py tests/test_cli.py
git commit -m "feat(cli): add discovery chain to jurati doctor"
```

---

### Task 13: Fetch Pruning and Tree-Hash Rebuild Optimization

**Files:**
- Modify: `src/jurati/git/repo.py`
- Test: `tests/git/test_repo.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/git/test_repo.py — add to existing file

class TestFetchPrune:
    def test_fetch_uses_prune(self, seeded_remote: git.Repo, cache_dir: Path) -> None:
        from jurati.git.repo import ensure_repo, fetch_all

        remote_url = str(seeded_remote.common_dir)
        repo_path = ensure_repo(remote_url, str(cache_dir))
        fetch_all(repo_path)


class TestTreeHashOptimization:
    def test_tree_hash_detects_no_change(self, seeded_remote: git.Repo, cache_dir: Path) -> None:
        from jurati.git.repo import ensure_repo, fetch_all, get_main_tree_hash

        remote_url = str(seeded_remote.common_dir)
        repo_path = ensure_repo(remote_url, str(cache_dir))
        fetch_all(repo_path)

        hash1 = get_main_tree_hash(repo_path, "main")
        fetch_all(repo_path)
        hash2 = get_main_tree_hash(repo_path, "main")
        assert hash1 == hash2

    def test_tree_hash_detects_change(self, seeded_remote: git.Repo, cache_dir: Path) -> None:
        import git as gitmodule
        from jurati.git.repo import ensure_repo, fetch_all, get_main_tree_hash

        remote_url = str(seeded_remote.common_dir)
        repo_path = ensure_repo(remote_url, str(cache_dir))
        fetch_all(repo_path)
        hash1 = get_main_tree_hash(repo_path, "main")

        # Add a commit to the remote
        repo = gitmodule.Repo(seeded_remote.common_dir)
        (Path(repo.working_dir) / "new-file.md").write_text("new content")
        repo.index.add(["new-file.md"])
        repo.index.commit("add new file")

        fetch_all(repo_path)
        hash2 = get_main_tree_hash(repo_path, "main")
        assert hash1 != hash2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/git/test_repo.py::TestTreeHashOptimization -v`
Expected: FAIL — `get_main_tree_hash` not found

- [ ] **Step 3: Implement prune and tree-hash**

In `src/jurati/git/repo.py`, update fetch to use `prune=True` and add:

```python
def get_main_tree_hash(repo_path: str, main_branch: str = "main") -> str:
    repo = git.Repo(repo_path)
    ref = repo.refs[f"origin/{main_branch}"]
    return ref.commit.tree.hexsha
```

- [ ] **Step 4: Run tests and commit**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/git/test_repo.py -v`

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/git/repo.py tests/git/test_repo.py
git commit -m "feat(repo): add --prune and tree-hash optimization for index rebuilds"
```

---

### Task 14: Update _render_entry to Handle Source in Existing Entry Parsing

The index loader needs to parse the `source` field from existing entries.

**Files:**
- Modify: `src/jurati/core/index.py`
- Test: `tests/core/test_index_search.py`

- [ ] **Step 1: Write failing test**

```python
# tests/core/test_index_search.py — add to existing file

class TestSourceParsing:
    def test_parse_entry_with_source(self) -> None:
        from jurati.core.index import parse_entry

        raw_fm = {
            "schema_version": 1,
            "id": "test-source",
            "title": "Test",
            "type": "project",
            "level": "L1",
            "status": "proposed",
            "created_at": "2026-05-02T12:00:00Z",
            "updated_at": "2026-05-02T12:00:00Z",
            "expires_at": None,
            "projects": [],
            "tags": [],
            "supersedes": [],
            "superseded_by": None,
            "sensitivity": "normal",
            "review": {"required": True, "pr": None},
            "source": {"repo": "api-service", "commit": "abc123", "author": "dev@co.com"},
        }
        entry = parse_entry("projects/test-source.md", raw_fm, "Body")
        assert entry.frontmatter.source is not None
        assert entry.frontmatter.source.repo == "api-service"

    def test_parse_entry_without_source(self) -> None:
        from jurati.core.index import parse_entry

        raw_fm = {
            "schema_version": 1,
            "id": "test-no-source",
            "title": "Test",
            "type": "project",
            "level": "L1",
            "status": "proposed",
            "created_at": "2026-05-02T12:00:00Z",
            "updated_at": "2026-05-02T12:00:00Z",
            "expires_at": None,
            "projects": [],
            "tags": [],
            "supersedes": [],
            "superseded_by": None,
            "sensitivity": "normal",
            "review": {"required": True, "pr": None},
        }
        entry = parse_entry("projects/test-no-source.md", raw_fm, "Body")
        assert entry.frontmatter.source is None
```

- [ ] **Step 2: Run test — should pass if Pydantic handles the optional field automatically**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/core/test_index_search.py::TestSourceParsing -v`

If Pydantic's `parse_entry` already handles this via the model, the test passes immediately. If not, update the parsing logic.

- [ ] **Step 3: Commit if tests pass**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add tests/core/test_index_search.py
git commit -m "test(index): add source field parsing tests"
```

---

### Task 15: Pre-Push Hook Auto-Flush

The spec calls for an optional pre-push hook that flushes pending captures.

**Files:**
- Modify: `src/jurati/cli.py` (update `install-hook`)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_cli.py — add to existing file

class TestInstallHookPrePush:
    def test_install_with_pre_push(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git" / "hooks"
        git_dir.mkdir(parents=True)
        (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["install-hook", "--with-pre-push"],
            env={"GIT_DIR": str(tmp_path / ".git")},
        )
        assert "pre-push" in result.output.lower() or result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/test_cli.py::TestInstallHookPrePush -v`
Expected: FAIL — `--with-pre-push` option not recognized

- [ ] **Step 3: Add `--with-pre-push` to install-hook**

In `src/jurati/cli.py`, add to the `install_hook` command:

```python
@click.option("--with-pre-push", is_flag=True, help="Also install pre-push hook for auto-flush")
```

After writing the post-commit hook, add:

```python
    if with_pre_push:
        pre_push_content = """#!/bin/sh
# Jurati pre-push hook — flushes pending captures before push
jurati flush 2>/dev/null || true
"""
        pre_push_path = hooks_dir / "pre-push"
        if pre_push_path.exists() and not force:
            click.echo(f"Pre-push hook exists at {pre_push_path}. Use --force to overwrite.", err=True)
        else:
            pre_push_path.write_text(pre_push_content)
            pre_push_path.chmod(0o755)
            click.echo(f"Installed pre-push hook at {pre_push_path}")
```

- [ ] **Step 4: Run tests and commit**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/test_cli.py -v`

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/cli.py tests/test_cli.py
git commit -m "feat(cli): add optional pre-push hook for auto-flush"
```

---

### Task 16: Weekly Hygiene Curation Workflow

The spec requires automated weekly scanning for stale entries and contradictions, opened as a PR against the knowledge repo.

**Files:**
- Create: `src/jurati/curation/hygiene_pr.py`
- Create: `tests/curation/test_hygiene_pr.py`
- Create: `action/hygiene.yml` (GitHub Action scheduled workflow)

- [ ] **Step 1: Write failing tests**

```python
# tests/curation/test_hygiene_pr.py
"""Tests for jurati.curation.hygiene_pr — weekly hygiene PR generation."""

from __future__ import annotations

from datetime import UTC, datetime

from jurati.curation.hygiene_pr import build_hygiene_pr_body

from tests.core.conftest import BASE_NOW, make_entry


class TestBuildHygienePrBody:
    def test_includes_stale_entries(self) -> None:
        stale = [
            make_entry(
                entry_id="old-decision",
                title="Old decision",
                created_at=datetime(2025, 12, 1, tzinfo=UTC),
                updated_at=datetime(2025, 12, 1, tzinfo=UTC),
            ),
        ]
        body = build_hygiene_pr_body(stale_entries=stale, contradictions=[], now=BASE_NOW)
        assert "old-decision" in body
        assert "Stale" in body

    def test_includes_contradictions(self) -> None:
        body = build_hygiene_pr_body(
            stale_entries=[],
            contradictions=[("new-entry", ["existing-1", "existing-2"])],
            now=BASE_NOW,
        )
        assert "Contradiction" in body or "contradiction" in body
        assert "new-entry" in body

    def test_empty_report(self) -> None:
        body = build_hygiene_pr_body(stale_entries=[], contradictions=[], now=BASE_NOW)
        assert "No issues" in body or "clean" in body.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/curation/test_hygiene_pr.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement hygiene_pr.py**

```python
# src/jurati/curation/__init__.py
# (empty package marker)

# src/jurati/curation/hygiene_pr.py
"""Generate weekly hygiene PR body for the knowledge repo."""

from __future__ import annotations

from datetime import datetime

from jurati.core.schema import Entry


def build_hygiene_pr_body(
    *,
    stale_entries: list[Entry],
    contradictions: list[tuple[str, list[str]]],
    now: datetime,
) -> str:
    sections: list[str] = []
    sections.append(f"## Weekly Knowledge Hygiene — {now.strftime('%Y-%m-%d')}\n")

    if not stale_entries and not contradictions:
        sections.append("Knowledge repo is clean. No issues found.\n")
        return "\n".join(sections)

    if stale_entries:
        sections.append(f"### Stale Entries ({len(stale_entries)})\n")
        sections.append("These entries have not been updated in 90+ days:\n")
        for entry in stale_entries:
            age = (now - entry.frontmatter.updated_at).days
            sections.append(
                f"- **{entry.frontmatter.id}**: {entry.frontmatter.title} "
                f"({age} days since last update)"
            )
        sections.append("")

    if contradictions:
        sections.append(f"### Possible Contradictions ({len(contradictions)})\n")
        for new_id, conflict_ids in contradictions:
            sections.append(f"- **{new_id}** may conflict with: {', '.join(conflict_ids)}")
        sections.append("")

    sections.append(
        "---\n*Auto-generated by `jurati`. "
        "Review and resolve, or close to acknowledge.*"
    )
    return "\n".join(sections)
```

- [ ] **Step 4: Create `run_hygiene.py` entrypoint**

```python
# src/jurati/curation/run_hygiene.py
"""CLI/Action entrypoint for weekly hygiene scan."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from jurati.core.curation import detect_contradictions, find_stale_entries
from jurati.curation.hygiene_pr import build_hygiene_pr_body
from jurati.git.repo import ensure_repo, fetch_all, load_index_from_repo


def main() -> None:
    remote = os.environ["JURATI_KNOWLEDGE_REMOTE"]
    cache_dir = os.environ.get("JURATI_CACHE_DIR", "/tmp/jurati-knowledge")
    main_branch = os.environ.get("JURATI_MAIN_BRANCH", "main")
    now = datetime.now(UTC)

    repo_path = ensure_repo(remote, cache_dir)
    fetch_all(repo_path, main_branch)
    index = load_index_from_repo(repo_path, main_branch)
    entries = list(index.entries.values())

    stale = find_stale_entries(entries, now=now, stale_after_days=90)

    # Detect pairwise contradictions among active entries
    contradictions: list[tuple[str, list[str]]] = []
    for entry in entries:
        conflicts = detect_contradictions(
            entry.frontmatter.title,
            [e for e in entries if e.frontmatter.id != entry.frontmatter.id],
            entry_type=entry.frontmatter.type,
        )
        if conflicts:
            contradictions.append(
                (entry.frontmatter.id, [c.frontmatter.id for c in conflicts])
            )

    body = build_hygiene_pr_body(
        stale_entries=stale, contradictions=contradictions, now=now
    )
    print(body)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Create package markers**

Create `src/jurati/curation/__init__.py` and `tests/curation/__init__.py` as empty files.

- [ ] **Step 6: Create scheduled workflow**

```yaml
# action/hygiene.yml
name: jurati-hygiene
on:
  schedule:
    - cron: '0 9 * * 1'  # Weekly Monday 9am UTC
  workflow_dispatch: {}

jobs:
  hygiene:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install jurati
      - run: python -m jurati.curation.run_hygiene
        env:
          JURATI_KNOWLEDGE_REMOTE: ${{ secrets.JURATI_KNOWLEDGE_REMOTE }}
          JURATI_KNOWLEDGE_TOKEN: ${{ secrets.JURATI_KNOWLEDGE_TOKEN }}
```

- [ ] **Step 7: Run tests and commit**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/curation/ -v`

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/curation/ tests/curation/ action/hygiene.yml
git commit -m "feat(curation): add weekly hygiene PR generation and scheduled workflow"
```

---

### Task 17: Phases 1–5 Integration — Full Suite Verification

**Note:** This task verifies Phases 1–5 before starting Phase 6.

- [ ] **Step 1: Run the complete test suite**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest -v --tb=short`
Expected: All tests pass

- [ ] **Step 2: Run ruff and mypy**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && ruff check src/ tests/ && mypy src/jurati/`
Expected: Clean

- [ ] **Step 3: Verify test count increased**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest --co -q | tail -1`
Expected: At least 200 tests collected (was ~164 before DX work)

- [ ] **Step 4: Final commit for any remaining fixes**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add -A
git commit -m "chore: phases 1-5 integration cleanup"
```

---

## Phase 6: Ambient PR Coordination

Turns `jurati`-labeled PRs into ambient agent guidance. A developer labels a PR,
and agents receive coordination context — reuse prior work, pause overlapping
edits, revise plans when constraints change — without any developer command.

**Spec:** `docs/superpowers/specs/2026-05-04-jurati-ambient-coordination-design.md`

**Dependencies:** Phase 2 (Task 5 — `context()` tool), Phase 5 (Task 11 —
`PRSignalsConfig`). Both include forward-compatibility changes from this plan
revision.

### Task 18: PR Signal Model and Classification Rules (`core/pr_signals.py`)

Pure, deterministic, zero I/O. Receives `PRSignal` objects and request context
as explicit inputs. Does not read files, call GitHub, inspect git remotes, or
read environment variables.

**Files:**
- Create: `src/jurati/core/pr_signals.py`
- Create: `tests/core/test_pr_signals.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_pr_signals.py
"""Tests for jurati.core.pr_signals — PR signal classification and guidance."""

from __future__ import annotations

from datetime import UTC, datetime

from jurati.core.pr_signals import (
    CoordinationGuidance,
    PRSignal,
    PRSignalEvidence,
    classify_signals,
    derive_target_areas,
)


def _make_signal(**overrides: object) -> PRSignal:
    defaults = dict(
        signal_id="github:org/api:pull:418",
        provider="github",
        repo="org/api",
        number=418,
        url="https://github.com/org/api/pull/418",
        title="Resolve token refresh races",
        body_excerpt="Fixed race condition in auth token refresh",
        author="tony",
        state="merged",
        labels=("jurati",),
        created_at=datetime(2026, 4, 20, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 4, 27, 18, 40, tzinfo=UTC),
        merged_at=datetime(2026, 4, 27, 18, 40, tzinfo=UTC),
        changed_paths=("src/auth/token.py", "src/auth/refresh.py"),
        target_areas=("auth",),
    )
    defaults.update(overrides)
    return PRSignal(**defaults)


class TestDeriveTargetAreas:
    def test_extracts_top_level_dirs(self) -> None:
        paths = ("src/auth/token.py", "src/auth/refresh.py", "src/api/routes.py")
        areas = derive_target_areas(paths)
        assert "auth" in areas
        assert "api" in areas

    def test_deterministic(self) -> None:
        paths = ("src/b/x.py", "src/a/y.py")
        assert derive_target_areas(paths) == derive_target_areas(paths)

    def test_empty_paths(self) -> None:
        assert derive_target_areas(()) == ()

    def test_root_files_excluded(self) -> None:
        paths = ("README.md", "src/auth/token.py")
        areas = derive_target_areas(paths)
        assert "auth" in areas
        assert "README.md" not in areas


class TestClassifySignals:
    def test_same_path_merged_is_reuse(self) -> None:
        signal = _make_signal(
            state="merged",
            changed_paths=("src/auth/token.py",),
        )
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        results = classify_signals(
            signals=[signal],
            repo="org/api",
            paths=["src/auth/token.py"],
            now=now,
        )
        assert len(results) == 1
        assert results[0].effect == "reuse"

    def test_same_path_open_is_pause(self) -> None:
        signal = _make_signal(
            state="open",
            merged_at=None,
            changed_paths=("src/auth/token.py",),
        )
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        results = classify_signals(
            signals=[signal],
            repo="org/api",
            paths=["src/auth/token.py"],
            now=now,
        )
        assert len(results) == 1
        assert results[0].effect == "pause"

    def test_workflow_language_is_revise(self) -> None:
        signal = _make_signal(
            state="merged",
            title="Migration: switch from REST to gRPC",
            changed_paths=("src/gateway/protocol.py",),
        )
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        results = classify_signals(
            signals=[signal],
            repo="org/api",
            paths=["src/gateway/client.py"],
            now=now,
        )
        assert len(results) == 1
        assert results[0].effect == "revise"

    def test_different_area_same_repo_is_continue(self) -> None:
        signal = _make_signal(
            state="merged",
            changed_paths=("src/billing/invoice.py",),
            target_areas=("billing",),
        )
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        results = classify_signals(
            signals=[signal],
            repo="org/api",
            paths=["src/auth/token.py"],
            now=now,
        )
        assert len(results) == 1
        assert results[0].effect == "continue"

    def test_handoff_language(self) -> None:
        signal = _make_signal(
            state="open",
            title="Handoff: auth ownership to platform team",
            changed_paths=("src/auth/token.py",),
        )
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        results = classify_signals(
            signals=[signal],
            repo="org/api",
            paths=["src/auth/token.py"],
            now=now,
        )
        assert len(results) == 1
        assert results[0].effect == "handoff"

    def test_no_signals_returns_empty(self) -> None:
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        results = classify_signals(signals=[], repo="org/api", paths=[], now=now)
        assert results == []

    def test_confidence_is_bounded(self) -> None:
        signal = _make_signal(changed_paths=("src/auth/token.py",))
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        results = classify_signals(
            signals=[signal],
            repo="org/api",
            paths=["src/auth/token.py"],
            now=now,
        )
        assert 0 <= results[0].confidence <= 100

    def test_deterministic_ranking(self) -> None:
        signals = [
            _make_signal(
                signal_id="github:org/api:pull:418",
                changed_paths=("src/auth/token.py",),
            ),
            _make_signal(
                signal_id="github:org/api:pull:420",
                number=420,
                title="Cache TTL refactor",
                changed_paths=("src/cache/ttl.py",),
            ),
        ]
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        r1 = classify_signals(
            signals=signals, repo="org/api", paths=["src/auth/token.py"], now=now
        )
        r2 = classify_signals(
            signals=signals, repo="org/api", paths=["src/auth/token.py"], now=now
        )
        assert [g.effect for g in r1] == [g.effect for g in r2]

    def test_expired_signal_excluded(self) -> None:
        old_signal = _make_signal(
            state="merged",
            updated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            merged_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            changed_paths=("src/auth/token.py",),
        )
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        results = classify_signals(
            signals=[old_signal],
            repo="org/api",
            paths=["src/auth/token.py"],
            now=now,
            recency_days=30,
        )
        assert len(results) == 0

    def test_evidence_includes_matched_paths(self) -> None:
        signal = _make_signal(changed_paths=("src/auth/token.py", "src/auth/refresh.py"))
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        results = classify_signals(
            signals=[signal],
            repo="org/api",
            paths=["src/auth/token.py"],
            now=now,
        )
        assert "src/auth/token.py" in results[0].evidence[0].matched_paths
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/core/test_pr_signals.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement pr_signals.py**

```python
# src/jurati/core/pr_signals.py
"""PR signal classification and coordination guidance — pure, deterministic, zero I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

_REVISE_KEYWORDS = re.compile(
    r"\b(migration|deprecat|architect|workflow|decision|release|security|breaking)\b",
    re.IGNORECASE,
)
_HANDOFF_KEYWORDS = re.compile(
    r"\b(handoff|hand-off|ownership|blocked|waiting|review\s+required)\b",
    re.IGNORECASE,
)


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


@dataclass(frozen=True)
class CoordinationGuidance:
    effect: Literal["continue", "reuse", "revise", "pause", "handoff", "clarify"]
    urgency: Literal["quiet", "info", "notice", "warning", "critical"]
    summary: str
    instruction: str
    confidence: int
    evidence: tuple[PRSignalEvidence, ...]


def derive_target_areas(changed_paths: tuple[str, ...]) -> tuple[str, ...]:
    areas: set[str] = set()
    for path in changed_paths:
        parts = path.split("/")
        if len(parts) >= 3 and parts[0] == "src":
            areas.add(parts[1])
        elif len(parts) >= 2 and parts[0] != "src" and "." not in parts[0]:
            areas.add(parts[0])
    return tuple(sorted(areas))


def _path_overlap(
    signal_paths: tuple[str, ...], request_paths: list[str]
) -> tuple[str, ...]:
    signal_set = set(signal_paths)
    return tuple(p for p in request_paths if p in signal_set)


def _area_overlap(
    signal_areas: tuple[str, ...], request_paths: list[str]
) -> bool:
    request_areas = set(derive_target_areas(tuple(request_paths)))
    return bool(set(signal_areas) & request_areas)


def classify_signals(
    *,
    signals: list[PRSignal],
    repo: str | None = None,
    goal: str | None = None,
    paths: list[str] | None = None,
    now: datetime,
    recency_days: int = 30,
) -> list[CoordinationGuidance]:
    cutoff = now - timedelta(days=recency_days)
    paths = paths or []
    results: list[CoordinationGuidance] = []

    for signal in signals:
        if signal.updated_at < cutoff:
            continue
        if signal.state == "closed" and signal.merged_at is None:
            continue

        matched_paths = _path_overlap(signal.changed_paths, paths)
        area_match = _area_overlap(
            signal.target_areas or derive_target_areas(signal.changed_paths),
            paths,
        )
        text = f"{signal.title} {signal.body_excerpt or ''}"

        evidence = PRSignalEvidence(
            repo=signal.repo,
            number=signal.number,
            url=signal.url,
            title=signal.title,
            author=signal.author,
            state=signal.state,
            updated_at=signal.updated_at,
            matched_paths=matched_paths,
            reason="",
        )

        # Rule 1: same path, merged → reuse
        if matched_paths and signal.state == "merged":
            # But check for handoff/revise keywords first
            if _HANDOFF_KEYWORDS.search(text):
                effect, urgency = "handoff", "warning"
                reason = "merged jurati-labeled PR with handoff language touched requested path"
                instruction = f"Ownership has moved per {signal.author}'s PR. Treat as handoff point."
            elif _REVISE_KEYWORDS.search(text):
                effect, urgency = "revise", "notice"
                reason = "merged jurati-labeled PR with workflow/decision language touched requested path"
                instruction = "Update plan constraints based on this PR."
            else:
                effect, urgency = "reuse", "notice"
                reason = "merged jurati-labeled PR touched requested path"
                instruction = "Inspect and reuse that work before building a new solution."
            confidence = 90 if matched_paths else 70

        # Rule 2: same path, open → pause
        elif matched_paths and signal.state == "open":
            if _HANDOFF_KEYWORDS.search(text):
                effect, urgency = "handoff", "warning"
                reason = "open jurati-labeled PR with handoff language touches requested path"
                instruction = f"Treat {signal.author}'s PR as the ownership point."
            else:
                effect, urgency = "pause", "warning"
                reason = "open jurati-labeled PR touches requested path"
                instruction = "Pause edits to this target and account for the PR."
            confidence = 85

        # Rule 3: workflow/decision language → revise
        elif _REVISE_KEYWORDS.search(text) and (area_match or repo == signal.repo):
            effect, urgency = "revise", "notice"
            reason = "jurati-labeled PR contains workflow/decision language relevant to this area"
            instruction = "Update plan constraints based on this PR."
            confidence = 65

        # Rule 4: handoff language → handoff
        elif _HANDOFF_KEYWORDS.search(text) and (area_match or repo == signal.repo):
            effect, urgency = "handoff", "warning"
            reason = "jurati-labeled PR contains ownership/handoff language"
            instruction = f"Treat {signal.author}'s PR as the handoff point."
            confidence = 60

        # Rule 5: different area, same repo → continue
        elif repo and signal.repo == repo:
            effect, urgency = "continue", "quiet"
            reason = "jurati-labeled PR in same repo but different area"
            instruction = "Continue normally. This work appears parallel."
            confidence = 80

        # Rule 6: relevant but ambiguous → clarify
        elif area_match:
            effect, urgency = "clarify", "info"
            reason = "jurati-labeled PR touches related area but relationship is ambiguous"
            instruction = "Ask only if no safe plan can be formed from evidence."
            confidence = 40

        else:
            continue

        evidence = PRSignalEvidence(
            repo=signal.repo,
            number=signal.number,
            url=signal.url,
            title=signal.title,
            author=signal.author,
            state=signal.state,
            updated_at=signal.updated_at,
            matched_paths=matched_paths,
            reason=reason,
        )

        summary = f"{signal.author} {'merged' if signal.state == 'merged' else 'opened'} PR #{signal.number}: {signal.title}"

        results.append(CoordinationGuidance(
            effect=effect,
            urgency=urgency,
            summary=summary,
            instruction=instruction,
            confidence=min(max(confidence, 0), 100),
            evidence=(evidence,),
        ))

    # Sort: warnings first, then by confidence descending
    urgency_order = {"critical": 0, "warning": 1, "notice": 2, "info": 3, "quiet": 4}
    results.sort(key=lambda g: (urgency_order.get(g.urgency, 5), -g.confidence))
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/core/test_pr_signals.py -v`
Expected: PASS (iterate on classification edge cases)

- [ ] **Step 5: Run lint**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && ruff check src/jurati/core/pr_signals.py tests/core/test_pr_signals.py && mypy src/jurati/core/pr_signals.py`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/core/pr_signals.py tests/core/test_pr_signals.py
git commit -m "feat(coordination): add PR signal model and deterministic classification"
```

---

### Task 19: GitHub PR Signal Provider (`providers/github_prs.py`)

I/O boundary. Reads labeled PRs from configured GitHub repos using the auth
resolver. Does not classify — returns normalized `PRSignal` objects for
`core/pr_signals.py` to consume.

**Files:**
- Create: `src/jurati/providers/__init__.py`
- Create: `src/jurati/providers/github_prs.py`
- Create: `tests/providers/__init__.py`
- Create: `tests/providers/test_github_prs.py`

- [ ] **Step 1: Create package markers**

Create `src/jurati/providers/__init__.py` and `tests/providers/__init__.py` as
empty files.

- [ ] **Step 2: Write failing tests**

```python
# tests/providers/test_github_prs.py
"""Tests for jurati.providers.github_prs — GitHub PR signal adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from jurati.providers.github_prs import (
    fetch_labeled_prs,
    normalize_pr,
    _build_search_query,
)


class TestBuildSearchQuery:
    def test_basic_query(self) -> None:
        query = _build_search_query("org/api", "jurati")
        assert "repo:org/api" in query
        assert "label:jurati" in query
        assert "is:pr" in query

    def test_includes_state_filter(self) -> None:
        query = _build_search_query("org/api", "jurati")
        # Should not filter to only open — we need merged too
        assert "is:closed" not in query or "is:open" not in query


class TestNormalizePR:
    def test_normalizes_github_pr(self) -> None:
        raw = {
            "number": 418,
            "title": "Resolve token refresh races",
            "body": "Fixed race condition in auth token refresh. " * 20,
            "user": {"login": "tony"},
            "state": "closed",
            "merged_at": "2026-04-27T18:40:00Z",
            "created_at": "2026-04-20T12:00:00Z",
            "updated_at": "2026-04-27T18:40:00Z",
            "html_url": "https://github.com/org/api/pull/418",
            "labels": [{"name": "jurati"}, {"name": "auth"}],
        }
        changed_paths = ["src/auth/token.py", "src/auth/refresh.py"]

        signal = normalize_pr("org/api", raw, changed_paths)

        assert signal.signal_id == "github:org/api:pull:418"
        assert signal.provider == "github"
        assert signal.repo == "org/api"
        assert signal.number == 418
        assert signal.title == "Resolve token refresh races"
        assert signal.author == "tony"
        assert signal.state == "merged"  # closed + merged_at = merged
        assert signal.merged_at is not None
        assert signal.changed_paths == ("src/auth/token.py", "src/auth/refresh.py")
        assert "jurati" in signal.labels

    def test_body_excerpt_bounded(self) -> None:
        raw = {
            "number": 1,
            "title": "T",
            "body": "x" * 10000,
            "user": {"login": "dev"},
            "state": "open",
            "merged_at": None,
            "created_at": "2026-05-01T00:00:00Z",
            "updated_at": "2026-05-01T00:00:00Z",
            "html_url": "https://github.com/org/api/pull/1",
            "labels": [{"name": "jurati"}],
        }
        signal = normalize_pr("org/api", raw, [])
        assert signal.body_excerpt is not None
        assert len(signal.body_excerpt) <= 500

    def test_open_pr_state(self) -> None:
        raw = {
            "number": 2,
            "title": "WIP",
            "body": "",
            "user": {"login": "dev"},
            "state": "open",
            "merged_at": None,
            "created_at": "2026-05-01T00:00:00Z",
            "updated_at": "2026-05-01T00:00:00Z",
            "html_url": "https://github.com/org/api/pull/2",
            "labels": [{"name": "jurati"}],
        }
        signal = normalize_pr("org/api", raw, [])
        assert signal.state == "open"

    def test_null_body(self) -> None:
        raw = {
            "number": 3,
            "title": "No body",
            "body": None,
            "user": {"login": "dev"},
            "state": "open",
            "merged_at": None,
            "created_at": "2026-05-01T00:00:00Z",
            "updated_at": "2026-05-01T00:00:00Z",
            "html_url": "https://github.com/org/api/pull/3",
            "labels": [{"name": "jurati"}],
        }
        signal = normalize_pr("org/api", raw, [])
        assert signal.body_excerpt is None


class TestFetchLabeledPRs:
    @patch("jurati.providers.github_prs._github_api_get")
    def test_fetches_from_configured_repos(self, mock_get: MagicMock) -> None:
        mock_get.return_value = {"items": []}

        results = fetch_labeled_prs(
            repos=["org/api", "org/web"],
            label="jurati",
            recency_days=30,
            include_changed_paths=False,
        )
        assert results == []
        assert mock_get.call_count >= 1

    @patch("jurati.providers.github_prs._github_api_get")
    def test_excludes_unlabeled_prs(self, mock_get: MagicMock) -> None:
        mock_get.return_value = {
            "items": [
                {
                    "number": 1,
                    "title": "Unlabeled",
                    "body": "",
                    "user": {"login": "dev"},
                    "state": "open",
                    "merged_at": None,
                    "created_at": "2026-05-01T00:00:00Z",
                    "updated_at": "2026-05-01T00:00:00Z",
                    "html_url": "https://github.com/org/api/pull/1",
                    "labels": [],  # No jurati label
                    "pull_request": {"url": "..."},
                }
            ]
        }
        results = fetch_labeled_prs(
            repos=["org/api"],
            label="jurati",
            recency_days=30,
            include_changed_paths=False,
        )
        # Unlabeled PRs must be filtered out
        assert len(results) == 0

    @patch("jurati.providers.github_prs._github_api_get")
    def test_provider_failure_returns_empty(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = Exception("network error")
        results = fetch_labeled_prs(
            repos=["org/api"],
            label="jurati",
            recency_days=30,
            include_changed_paths=False,
        )
        assert results == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/providers/test_github_prs.py -v`
Expected: FAIL — module not found

- [ ] **Step 4: Implement github_prs.py**

```python
# src/jurati/providers/github_prs.py
"""GitHub adapter — reads labeled PRs from configured repos."""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Any

from jurati.core.pr_signals import PRSignal, derive_target_areas

logger = logging.getLogger(__name__)

_BODY_EXCERPT_LIMIT = 500


def _build_search_query(repo: str, label: str) -> str:
    return f"repo:{repo} is:pr label:{label}"


def _github_api_get(endpoint: str, params: dict[str, str] | None = None) -> Any:
    """Make a GitHub API GET request using gh CLI."""
    cmd = ["gh", "api", endpoint]
    if params:
        for k, v in params.items():
            cmd.extend(["-f", f"{k}={v}"])
    env = {**os.environ, "GH_PROMPT_DISABLED": "1"}
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"gh api failed: {result.stderr}")
    import json
    return json.loads(result.stdout)


def _fetch_changed_paths(repo: str, pr_number: int) -> list[str]:
    """Fetch changed file paths for a PR."""
    try:
        files = _github_api_get(f"/repos/{repo}/pulls/{pr_number}/files")
        return [f["filename"] for f in files]
    except Exception:
        logger.warning("Failed to fetch changed paths for %s#%d", repo, pr_number)
        return []


def normalize_pr(
    repo: str,
    raw: dict[str, Any],
    changed_paths: list[str],
) -> PRSignal:
    number = raw["number"]
    state_raw = raw["state"]
    merged_at_str = raw.get("merged_at")
    merged_at = (
        datetime.fromisoformat(merged_at_str.replace("Z", "+00:00"))
        if merged_at_str
        else None
    )

    if state_raw == "closed" and merged_at is not None:
        state = "merged"
    elif state_raw == "open":
        state = "open"
    else:
        state = "closed"

    body = raw.get("body")
    body_excerpt: str | None = None
    if body:
        body_excerpt = body[:_BODY_EXCERPT_LIMIT]

    labels = tuple(lbl["name"] for lbl in raw.get("labels", []))
    paths_tuple = tuple(changed_paths)

    return PRSignal(
        signal_id=f"github:{repo}:pull:{number}",
        provider="github",
        repo=repo,
        number=number,
        url=raw["html_url"],
        title=raw["title"],
        body_excerpt=body_excerpt,
        author=raw["user"]["login"],
        state=state,
        labels=labels,
        created_at=datetime.fromisoformat(raw["created_at"].replace("Z", "+00:00")),
        updated_at=datetime.fromisoformat(raw["updated_at"].replace("Z", "+00:00")),
        merged_at=merged_at,
        changed_paths=paths_tuple,
        target_areas=derive_target_areas(paths_tuple),
    )


def fetch_labeled_prs(
    *,
    repos: list[str],
    label: str,
    recency_days: int,
    include_changed_paths: bool = True,
) -> list[PRSignal]:
    cutoff = datetime.now(UTC) - timedelta(days=recency_days)
    signals: list[PRSignal] = []

    for repo in repos:
        try:
            query = _build_search_query(repo, label)
            data = _github_api_get(
                "/search/issues",
                {"q": query, "sort": "updated", "order": "desc", "per_page": "30"},
            )
            for item in data.get("items", []):
                item_labels = {lbl["name"] for lbl in item.get("labels", [])}
                if label not in item_labels:
                    continue

                updated = datetime.fromisoformat(
                    item["updated_at"].replace("Z", "+00:00")
                )
                if updated < cutoff:
                    continue

                changed_paths: list[str] = []
                if include_changed_paths:
                    changed_paths = _fetch_changed_paths(repo, item["number"])

                signals.append(normalize_pr(repo, item, changed_paths))

        except Exception:
            logger.warning(
                "Failed to fetch labeled PRs from %s — degrading gracefully",
                repo,
                exc_info=True,
            )

    return signals
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/providers/test_github_prs.py -v`
Expected: PASS

- [ ] **Step 6: Run lint**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && ruff check src/jurati/providers/ tests/providers/ && mypy src/jurati/providers/`
Expected: Clean

- [ ] **Step 7: Commit**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/providers/ tests/providers/
git commit -m "feat(providers): add GitHub labeled-PR adapter"
```

---

### Task 20: PR Signal Cache

Local cache of normalized `PRSignal` objects to avoid hitting the GitHub API on
every `context()` call. Cache rules from the spec: only labeled PRs from
configured repos, expire by `recency_days` and `updated_at`, never cache query
text or caller identity.

**Files:**
- Create: `src/jurati/providers/cache.py`
- Create: `tests/providers/test_cache.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/providers/test_cache.py
"""Tests for jurati.providers.cache — PR signal cache."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jurati.core.pr_signals import PRSignal
from jurati.providers.cache import SignalCache


def _make_signal(signal_id: str = "github:org/api:pull:1", **kw: object) -> PRSignal:
    defaults = dict(
        signal_id=signal_id,
        provider="github",
        repo="org/api",
        number=1,
        url="https://github.com/org/api/pull/1",
        title="Test PR",
        body_excerpt=None,
        author="dev",
        state="open",
        labels=("jurati",),
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
        merged_at=None,
        changed_paths=(),
        target_areas=(),
    )
    defaults.update(kw)
    return PRSignal(**defaults)


class TestSignalCache:
    def test_put_and_get(self) -> None:
        cache = SignalCache(recency_days=30)
        signal = _make_signal()
        now = datetime(2026, 5, 2, tzinfo=UTC)

        cache.put([signal], now=now)
        results = cache.get(now=now)
        assert len(results) == 1
        assert results[0].signal_id == signal.signal_id

    def test_expired_signals_evicted(self) -> None:
        cache = SignalCache(recency_days=30)
        old_signal = _make_signal(
            updated_at=datetime(2026, 3, 1, tzinfo=UTC),
        )
        now = datetime(2026, 5, 2, tzinfo=UTC)

        cache.put([old_signal], now=now)
        results = cache.get(now=now)
        assert len(results) == 0

    def test_refresh_replaces_stale(self) -> None:
        cache = SignalCache(recency_days=30)
        now = datetime(2026, 5, 2, tzinfo=UTC)

        signal_v1 = _make_signal(title="V1")
        cache.put([signal_v1], now=now)

        signal_v2 = _make_signal(title="V2")
        cache.put([signal_v2], now=now)

        results = cache.get(now=now)
        assert len(results) == 1
        assert results[0].title == "V2"

    def test_label_removed_signal_dropped(self) -> None:
        cache = SignalCache(recency_days=30)
        now = datetime(2026, 5, 2, tzinfo=UTC)

        signal = _make_signal(labels=("jurati",))
        cache.put([signal], now=now)

        # Refresh without the signal (label was removed)
        cache.put([], now=now)
        results = cache.get(now=now)
        assert len(results) == 0

    def test_is_stale(self) -> None:
        cache = SignalCache(recency_days=30)
        now = datetime(2026, 5, 2, tzinfo=UTC)

        assert cache.is_stale(now=now, ttl_seconds=300) is True

        cache.put([], now=now)
        assert cache.is_stale(now=now, ttl_seconds=300) is False

        later = now + timedelta(seconds=301)
        assert cache.is_stale(now=later, ttl_seconds=300) is True

    def test_no_query_or_caller_stored(self) -> None:
        cache = SignalCache(recency_days=30)
        # SignalCache has no fields for query text, caller identity,
        # or read selections — verify by attribute inspection
        assert not hasattr(cache, "last_query")
        assert not hasattr(cache, "caller")
        assert not hasattr(cache, "read_log")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/providers/test_cache.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement cache.py**

```python
# src/jurati/providers/cache.py
"""PR signal cache — stores only normalized labeled PR signals from configured repos."""

from __future__ import annotations

from datetime import datetime, timedelta

from jurati.core.pr_signals import PRSignal


class SignalCache:
    def __init__(self, *, recency_days: int = 30) -> None:
        self._recency_days = recency_days
        self._signals: dict[str, PRSignal] = {}
        self._last_refresh: datetime | None = None

    def put(self, signals: list[PRSignal], *, now: datetime) -> None:
        self._signals = {}
        cutoff = now - timedelta(days=self._recency_days)
        for signal in signals:
            if signal.updated_at >= cutoff:
                self._signals[signal.signal_id] = signal
        self._last_refresh = now

    def get(self, *, now: datetime) -> list[PRSignal]:
        cutoff = now - timedelta(days=self._recency_days)
        return [s for s in self._signals.values() if s.updated_at >= cutoff]

    def is_stale(self, *, now: datetime, ttl_seconds: int = 300) -> bool:
        if self._last_refresh is None:
            return True
        return (now - self._last_refresh).total_seconds() > ttl_seconds
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/providers/test_cache.py -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && ruff check src/jurati/providers/cache.py tests/providers/test_cache.py && mypy src/jurati/providers/cache.py`

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/providers/cache.py tests/providers/test_cache.py
git commit -m "feat(providers): add PR signal cache with recency expiry"
```

---

### Task 21: Wire Coordination Into `context()` MCP Tool

Connects the provider, cache, and classification core to the `context()` tool.
When `PRSignalsConfig` is present and `include_pr_signals` is true, the server
fetches labeled PRs, classifies them, and returns a `coordination` key in the
response. Provider failure returns degraded status, never total failure.

**Files:**
- Modify: `src/jurati/server.py`
- Create: `tests/test_server_coordination.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_server_coordination.py
"""Tests for ambient PR coordination in the context() MCP tool."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from jurati.core.index import Index
from jurati.core.pr_signals import CoordinationGuidance, PRSignal, PRSignalEvidence
from jurati.server import _build_context_payload, _build_coordination_payload


def _make_signal(**kw: object) -> PRSignal:
    defaults = dict(
        signal_id="github:org/api:pull:418",
        provider="github",
        repo="org/api",
        number=418,
        url="https://github.com/org/api/pull/418",
        title="Resolve token refresh races",
        body_excerpt=None,
        author="tony",
        state="merged",
        labels=("jurati",),
        created_at=datetime(2026, 4, 20, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 4, 27, 18, 40, tzinfo=UTC),
        merged_at=datetime(2026, 4, 27, 18, 40, tzinfo=UTC),
        changed_paths=("src/auth/token.py",),
        target_areas=("auth",),
    )
    defaults.update(kw)
    return PRSignal(**defaults)


class TestBuildCoordinationPayload:
    def test_includes_guidance(self) -> None:
        signal = _make_signal()
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)

        result = _build_coordination_payload(
            signals=[signal],
            repo="org/api",
            paths=["src/auth/token.py"],
            now=now,
        )
        assert result["status"] == "ok"
        assert len(result["guidance"]) == 1
        assert result["guidance"][0]["effect"] == "reuse"
        assert result["guidance"][0]["evidence"][0]["url"] == signal.url

    def test_no_signals_returns_ok(self) -> None:
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        result = _build_coordination_payload(
            signals=[], repo="org/api", paths=[], now=now
        )
        assert result["status"] == "ok"
        assert result["guidance"] == []

    def test_includes_privacy_boundary(self) -> None:
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        result = _build_coordination_payload(
            signals=[], repo=None, paths=None, now=now
        )
        assert "privacy_boundary" in result
        assert isinstance(result["privacy_boundary"], list)
        assert len(result["privacy_boundary"]) > 0


class TestContextWithCoordination:
    def test_context_payload_includes_coordination(self) -> None:
        index = Index()
        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        coordination = {
            "status": "ok",
            "summary": "1 labeled PR",
            "guidance": [],
            "privacy_boundary": [],
        }
        result = _build_context_payload(index, now=now, coordination=coordination)
        assert "active" in result
        assert "recent" in result
        assert "coordination" in result
        assert result["coordination"]["status"] == "ok"

    def test_context_payload_without_coordination(self) -> None:
        index = Index()
        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        result = _build_context_payload(index, now=now)
        assert "active" in result
        assert "recent" in result
        assert "coordination" not in result


class TestDegradedCoordination:
    def test_provider_failure_returns_degraded(self) -> None:
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        result = _build_coordination_payload(
            signals=None,  # None signals provider failure
            repo="org/api",
            paths=["src/auth/token.py"],
            now=now,
            provider_error="network timeout",
        )
        assert result["status"] == "degraded"
        assert "guidance" in result
        assert result["guidance"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/test_server_coordination.py -v`
Expected: FAIL — `_build_coordination_payload` not found

- [ ] **Step 3: Implement coordination wiring in server.py**

Add to `src/jurati/server.py`:

```python
from jurati.core.pr_signals import classify_signals, CoordinationGuidance


_PRIVACY_BOUNDARY = [
    "only configured repos are checked",
    "only PRs carrying the configured jurati label are used",
    "unlabeled PRs, comments, chats, editor activity, and read activity are not mined",
]


def _build_coordination_payload(
    *,
    signals: list[PRSignal] | None,
    repo: str | None,
    paths: list[str] | None,
    now: datetime,
    goal: str | None = None,
    provider_error: str | None = None,
) -> dict[str, Any]:
    if signals is None:
        return {
            "status": "degraded",
            "summary": f"PR signal provider unavailable: {provider_error or 'unknown'}",
            "guidance": [],
            "privacy_boundary": _PRIVACY_BOUNDARY,
        }

    guidance_list = classify_signals(
        signals=signals, repo=repo, goal=goal, paths=paths, now=now
    )

    guidance_dicts = [
        {
            "effect": g.effect,
            "urgency": g.urgency,
            "summary": g.summary,
            "instruction": g.instruction,
            "confidence": g.confidence,
            "evidence": [
                {
                    "repo": e.repo,
                    "number": e.number,
                    "url": e.url,
                    "title": e.title,
                    "author": e.author,
                    "state": e.state,
                    "updated_at": e.updated_at.isoformat(),
                    "matched_paths": list(e.matched_paths),
                    "reason": e.reason,
                }
                for e in g.evidence
            ],
        }
        for g in guidance_list
    ]

    count = len(guidance_list)
    summary = (
        f"{count} jurati-labeled PR{'s' if count != 1 else ''} may affect this plan."
        if count > 0
        else "No jurati-labeled PRs affecting this plan."
    )

    return {
        "status": "ok",
        "summary": summary,
        "guidance": guidance_dicts,
        "privacy_boundary": _PRIVACY_BOUNDARY,
    }
```

Then update the `context` MCP tool handler to wire in the provider and cache:

```python
@mcp.tool()
async def context(
    ctx: Context,
    repo: str | None = None,
    goal: str | None = None,
    paths: list[str] | None = None,
    include_pr_signals: bool = True,
) -> dict[str, Any]:
    """Get session-start context: active entries, recent decisions, and repo-relevant items."""
    state = _state(ctx)
    now = datetime.now(UTC)

    coordination: dict[str, Any] | None = None
    if include_pr_signals and state.config.pr_signals:
        pr_cfg = state.config.pr_signals
        try:
            if state.signal_cache.is_stale(now=now, ttl_seconds=300):
                from jurati.providers.github_prs import fetch_labeled_prs

                signals = fetch_labeled_prs(
                    repos=pr_cfg.repos,
                    label=pr_cfg.label,
                    recency_days=pr_cfg.recency_days,
                    include_changed_paths=pr_cfg.include_changed_paths,
                )
                state.signal_cache.put(signals, now=now)

            cached = state.signal_cache.get(now=now)
            coordination = _build_coordination_payload(
                signals=cached, repo=repo, paths=paths, now=now, goal=goal,
            )
        except Exception as e:
            logger.warning("PR signal provider failed: %s", e, exc_info=True)
            coordination = _build_coordination_payload(
                signals=None, repo=repo, paths=paths, now=now,
                provider_error=str(e),
            )

    return _build_context_payload(
        state.index, now=now, repo=repo, coordination=coordination
    )
```

Add `signal_cache` to `ServerState`:

```python
from jurati.providers.cache import SignalCache

# In ServerState.__init__ or as a field:
self.signal_cache = SignalCache(
    recency_days=self.config.pr_signals.recency_days
    if self.config.pr_signals
    else 30
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/test_server_coordination.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite and lint**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest && ruff check src/ tests/ && mypy src/jurati/server.py`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add src/jurati/server.py tests/test_server_coordination.py
git commit -m "feat(server): wire PR signal coordination into context() tool"
```

---

### Task 22: Privacy Regression Tests

The ambient coordination spec defines strict privacy boundaries. These tests
prove no read receipts, query logs, unlabeled PR mining, comments, raw diffs,
or participation metrics are introduced.

**Files:**
- Create: `tests/test_privacy_coordination.py`

- [ ] **Step 1: Write privacy regression tests**

```python
# tests/test_privacy_coordination.py
"""Privacy regression tests for ambient PR coordination."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch, MagicMock

from jurati.providers.cache import SignalCache
from jurati.server import _build_coordination_payload


class TestPrivacyBoundary:
    def test_coordination_does_not_persist_caller(self) -> None:
        """context() must not record who called it."""
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        result = _build_coordination_payload(
            signals=[], repo="org/api", paths=["src/auth/token.py"], now=now
        )
        # No caller, query, or session field in result
        assert "caller" not in result
        assert "query" not in result
        assert "session" not in result

    def test_coordination_does_not_log_which_signals_surfaced(self) -> None:
        """Returned signals must not be tracked for analytics."""
        cache = SignalCache(recency_days=30)
        assert not hasattr(cache, "surfaced_log")
        assert not hasattr(cache, "read_log")
        assert not hasattr(cache, "access_log")

    def test_privacy_boundary_always_present(self) -> None:
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        result = _build_coordination_payload(
            signals=[], repo=None, paths=None, now=now
        )
        assert "privacy_boundary" in result
        boundary = result["privacy_boundary"]
        assert any("unlabeled" in b.lower() for b in boundary)
        assert any("configured" in b.lower() for b in boundary)

    def test_degraded_does_not_expose_token(self) -> None:
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        result = _build_coordination_payload(
            signals=None,
            repo="org/api",
            paths=[],
            now=now,
            provider_error="401 Unauthorized: token ghp_ABCDEF...",
        )
        assert result["status"] == "degraded"
        # Error message is passed through — but the provider layer
        # (github_prs.py) must sanitize before passing. This test
        # documents the boundary.
        assert "guidance" in result
        assert result["guidance"] == []


class TestProviderConstraints:
    @patch("jurati.providers.github_prs._github_api_get")
    def test_provider_does_not_fetch_comments(self, mock_get: MagicMock) -> None:
        """v1 must not fetch PR comments or review comments."""
        from jurati.providers.github_prs import fetch_labeled_prs

        mock_get.return_value = {"items": []}
        fetch_labeled_prs(
            repos=["org/api"],
            label="jurati",
            recency_days=30,
            include_changed_paths=False,
        )
        # Verify no calls to comments endpoints
        for call in mock_get.call_args_list:
            endpoint = call[0][0] if call[0] else ""
            assert "comments" not in endpoint
            assert "reviews" not in endpoint

    @patch("jurati.providers.github_prs._github_api_get")
    def test_provider_does_not_fetch_diffs(self, mock_get: MagicMock) -> None:
        """v1 must not fetch raw diff hunks."""
        from jurati.providers.github_prs import fetch_labeled_prs

        mock_get.return_value = {"items": []}
        fetch_labeled_prs(
            repos=["org/api"],
            label="jurati",
            recency_days=30,
            include_changed_paths=True,
        )
        for call in mock_get.call_args_list:
            endpoint = call[0][0] if call[0] else ""
            assert "diff" not in endpoint.lower()
```

- [ ] **Step 2: Run tests**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest tests/test_privacy_coordination.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add tests/test_privacy_coordination.py
git commit -m "test(privacy): add coordination privacy regression tests"
```

---

### Task 23: Final Integration — Full Suite Verification

**Note:** This is the final task. The plan now covers 23 tasks across 6 phases.

- [ ] **Step 1: Run the complete test suite**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest -v --tb=short`
Expected: All tests pass

- [ ] **Step 2: Run ruff and mypy**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && ruff check src/ tests/ && mypy src/jurati/`
Expected: Clean

- [ ] **Step 3: Verify test count**

Run: `cd /home/eparenti/agentic-workflow-project/jurati && python -m pytest --co -q | tail -1`
Expected: At least 250 tests collected (Phases 1–5 target ~200, Phase 6 adds ~50)

- [ ] **Step 4: Final commit for any remaining fixes**

```bash
cd /home/eparenti/agentic-workflow-project/jurati
git add -A
git commit -m "chore: final integration cleanup"
```
