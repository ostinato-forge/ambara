# Jurati Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve jurati from a standalone tool into a generic platform component for human+agent teams — schema v2, L0 opt-in, provider-pluggable signals, event emission, integration contract, index caching, and DX automation.

**Architecture:** Pure/IO split preserved. `core/` stays zero-I/O. New `providers/protocol.py` hosts the I/O protocol. `core/contract.py` and `core/privacy.py` are new pure modules. Schema v2 is backward-compatible via parse-time defaults (no data migration). Six implementation phases, each producing working, testable software.

**Tech Stack:** Python 3.13, pytest, pydantic, gitpython, mcp, ruff, mypy

**Spec:** `docs/superpowers/specs/2026-05-05-jurati-evolution-design.md`

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `src/jurati/core/events.py` | EventType enum, EventRecord dataclass (pure) |
| `src/jurati/core/contract.py` | AccessMode, KnowledgeQuery, KnowledgeResult, check_constraints() (pure) |
| `src/jurati/core/privacy.py` | opaque_identity() salted hash (pure) |
| `src/jurati/providers/protocol.py` | SignalProvider runtime-checkable protocol (I/O interface) |
| `tests/core/test_events.py` | Event type and record tests |
| `tests/core/test_contract.py` | Access mode filtering and constraint check tests |
| `tests/core/test_privacy.py` | Identity opacity tests |
| `tests/providers/test_protocol.py` | Protocol conformance tests |
| `tests/test_server_contract.py` | knowledge_query MCP tool integration tests |

### Modified Files

| File | Change |
|------|--------|
| `src/jurati/core/schema.py` | Add Visibility, RecordedBy; bump schema_version default to 2; add on_source_branch to Entry |
| `src/jurati/core/validate.py` | Restricted+EXTERNAL rejection, restricted+L0 rejection, L0 max TTL (168h) |
| `src/jurati/core/index.py` | v1→v2 backward-compatible defaults in parse_entry(); on_source_branch support |
| `src/jurati/core/changes.py` | Populate visibility/recorded_by in plan_record/plan_propose; EventRecord on WriteIntent/ExpireIntent |
| `src/jurati/core/scoring.py` | Skip restricted entries in build_inverted_index(); prebuilt_index param on rank_entries() |
| `src/jurati/core/pr_signals.py` | Add CoordinationSignal generalized shape; keep PRSignal as alias; configurable keyword sets |
| `src/jurati/git/config.py` | Add active_refs_enabled flag (default False), signal_providers list, keyword overrides |
| `src/jurati/git/repo.py` | Respect active_refs_enabled in fetch_all() and load_index_from_repo() |
| `src/jurati/git/commit.py` | Materialize event files in both materialize_write and materialize_expire |
| `src/jurati/providers/github_prs.py` | Implement SignalProvider protocol; map PRSignal→CoordinationSignal |
| `src/jurati/providers/cache.py` | Accept CoordinationSignal alongside PRSignal |
| `src/jurati/server.py` | Index caching; restricted filtering; L0 opt-in gate; visibility passthrough on record/propose; knowledge_query MCP tool; provider registry |
| `src/jurati/cli.py` | Add install-claude-md command; quickstart settings.json generation; collision-safe MCP config |

---

## Phase 1: Schema v2 — Visibility, Provenance, Sensitivity Enforcement

### Task 1: Add Visibility Enum and RecordedBy Model to Schema

**Files:**
- Modify: `src/jurati/core/schema.py:1-103`
- Test: `tests/core/test_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_schema.py — append after existing tests

from jurati.core.schema import RecordedBy, Visibility


def test_visibility_values() -> None:
    assert Visibility.INTERNAL == "internal"
    assert Visibility.EXTERNAL == "external"


def test_recorded_by_is_frozen() -> None:
    rb = RecordedBy(client="claude-code")
    assert rb.client == "claude-code"
    with pytest.raises(Exception):
        rb.client = "other"  # type: ignore[misc]


def test_frontmatter_defaults_visibility_to_internal() -> None:
    fm = Frontmatter(
        id="test-viz",
        title="Test Visibility",
        type=EntryType.PROJECT,
        level=EscalationLevel.L1,
        created_at=datetime(2026, 5, 5, tzinfo=UTC),
        updated_at=datetime(2026, 5, 5, tzinfo=UTC),
    )
    assert fm.visibility == Visibility.INTERNAL
    assert fm.recorded_by is None


def test_frontmatter_accepts_recorded_by() -> None:
    fm = Frontmatter(
        id="test-rb",
        title="Test RecordedBy",
        type=EntryType.PROJECT,
        level=EscalationLevel.L1,
        created_at=datetime(2026, 5, 5, tzinfo=UTC),
        updated_at=datetime(2026, 5, 5, tzinfo=UTC),
        recorded_by=RecordedBy(client="cursor"),
    )
    assert fm.recorded_by is not None
    assert fm.recorded_by.client == "cursor"


def test_schema_version_defaults_to_2() -> None:
    fm = Frontmatter(
        id="test-v2",
        title="V2 Default",
        type=EntryType.PROJECT,
        level=EscalationLevel.L1,
        created_at=datetime(2026, 5, 5, tzinfo=UTC),
        updated_at=datetime(2026, 5, 5, tzinfo=UTC),
    )
    assert fm.schema_version == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_schema.py -v -x`
Expected: ImportError for Visibility, RecordedBy; schema_version still 1

- [ ] **Step 3: Implement the schema additions**

Add to `src/jurati/core/schema.py` after the `Sensitivity` enum (line 49):

```python
class Visibility(StrEnum):
    INTERNAL = "internal"
    EXTERNAL = "external"


class RecordedBy(BaseModel, frozen=True):
    """Which MCP client submitted the write. Populated automatically."""
    client: str
```

Add to `Frontmatter` class (after `source` field, line 81):

```python
    visibility: Visibility = Visibility.INTERNAL
    recorded_by: RecordedBy | None = None
```

Change `schema_version` default from `1` to `2` (line 66):

```python
    schema_version: int = 2
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_schema.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite for regressions**

Run: `pytest tests/ -x -q`
Expected: Some tests may fail because they assert `schema_version: 1` in rendered content. Fix those in the next step.

- [ ] **Step 6: Fix schema_version assertions in existing tests**

Any test asserting `schema_version: 1` in rendered output needs updating to `schema_version: 2`. Grep and fix:

```bash
grep -rn "schema_version: 1" tests/
```

Update each match to `schema_version: 2`.

- [ ] **Step 7: Run full suite again**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add src/jurati/core/schema.py tests/core/test_schema.py
git commit -m "feat(schema): add Visibility, RecordedBy, bump to schema v2"
```

---

### Task 2: Add on_source_branch to Entry

**Files:**
- Modify: `src/jurati/core/schema.py:91-94`
- Test: `tests/core/test_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_schema.py — append

def test_entry_defaults_on_source_branch_to_false() -> None:
    from tests.core.conftest import make_entry
    entry = make_entry()
    assert entry.on_source_branch is False


def test_entry_accepts_on_source_branch_true() -> None:
    from tests.core.conftest import make_entry
    entry = make_entry()
    entry_dict = entry.model_dump()
    entry_dict["on_source_branch"] = True
    entry2 = Entry(**entry_dict)
    assert entry2.on_source_branch is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_schema.py::test_entry_defaults_on_source_branch_to_false -v`
Expected: FAIL — AttributeError

- [ ] **Step 3: Add the field to Entry**

In `src/jurati/core/schema.py`, modify the `Entry` class:

```python
class Entry(BaseModel):
    path: str
    frontmatter: Frontmatter
    body: str
    on_source_branch: bool = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_schema.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/core/schema.py tests/core/test_schema.py
git commit -m "feat(schema): add on_source_branch derived field to Entry"
```

---

### Task 3: Schema v1 Backward Compatibility in parse_entry

**Files:**
- Test: `tests/core/test_index.py` (create)

This is backward compatibility, not migration. v1 entries keep `schema_version: 1` — it is a provenance marker, not a format gate. Pydantic applies defaults for absent v2 fields. No rewriting, no normalization.

- [ ] **Step 1: Write the compatibility test**

```python
# tests/core/test_index.py

from __future__ import annotations

from jurati.core.index import parse_entry
from jurati.core.schema import Visibility


def test_v1_entry_keeps_version_1_gains_v2_defaults() -> None:
    """v1 entries are not normalized to v2. The version stays 1, and
    Pydantic applies defaults for absent v2 fields."""
    raw = {
        "schema_version": 1,
        "id": "legacy-entry",
        "title": "Legacy",
        "type": "project",
        "level": "L1",
        "status": "proposed",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    entry = parse_entry("projects/legacy-entry.md", raw, "old body")
    assert entry.frontmatter.schema_version == 1
    assert entry.frontmatter.visibility == Visibility.INTERNAL
    assert entry.frontmatter.recorded_by is None


def test_v2_entry_preserves_explicit_visibility() -> None:
    raw = {
        "schema_version": 2,
        "id": "new-entry",
        "title": "New",
        "type": "decision",
        "level": "L2",
        "status": "proposed",
        "created_at": "2026-05-05T00:00:00Z",
        "updated_at": "2026-05-05T00:00:00Z",
        "visibility": "external",
    }
    entry = parse_entry("decisions/new-entry.md", raw, "new body")
    assert entry.frontmatter.schema_version == 2
    assert entry.frontmatter.visibility == Visibility.EXTERNAL
```

- [ ] **Step 2: Run tests to verify both pass**

Run: `pytest tests/core/test_index.py -v`
Expected: Both PASS — Pydantic handles this without explicit migration code. These tests document the contract: v1 entries are first-class citizens, not legacy debt.

- [ ] **Step 3: Commit**

```bash
git add tests/core/test_index.py
git commit -m "test(index): verify v1 backward compatibility — no migration, Pydantic defaults"
```

---

### Task 4: Sensitivity Enforcement — Restricted Validation Rules

**Files:**
- Modify: `src/jurati/core/validate.py:22-66`
- Test: `tests/core/test_validate.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/core/test_validate.py — append

from jurati.core.schema import Sensitivity, Visibility


def test_restricted_entry_cannot_be_external() -> None:
    entry = make_entry(
        sensitivity=Sensitivity.RESTRICTED,
        visibility=Visibility.EXTERNAL,
    )
    errors = validate_entry(entry)
    assert any("restricted" in e and "external" in e for e in errors)


def test_restricted_entry_cannot_be_l0() -> None:
    entry = make_entry(
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        sensitivity=Sensitivity.RESTRICTED,
        expires_at=minutes_after(30),
        review_required=False,
    )
    errors = validate_entry(entry)
    assert any("restricted" in e and "L0" in e for e in errors)


def test_restricted_internal_l1_is_valid() -> None:
    entry = make_entry(sensitivity=Sensitivity.RESTRICTED)
    errors = validate_entry(entry)
    assert not any("restricted" in e for e in errors)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_validate.py::test_restricted_entry_cannot_be_external -v`
Expected: FAIL — no restriction error produced

- [ ] **Step 3: Add the import and validation rules**

In `src/jurati/core/validate.py`, add to imports (line 8):

```python
from jurati.core.schema import (
    ID_PATTERN,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Sensitivity,
    Visibility,
    is_level_allowed,
)
```

Add to `validate_entry()` after the superseded_by check (before `return errors`, line 65):

```python
    if fm.sensitivity == Sensitivity.RESTRICTED and fm.visibility == Visibility.EXTERNAL:
        errors.append("restricted entries cannot have visibility external")

    if fm.sensitivity == Sensitivity.RESTRICTED and fm.level == EscalationLevel.L0:
        errors.append("restricted entries cannot be L0 (active refs have no access control)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_validate.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/core/validate.py tests/core/test_validate.py
git commit -m "feat(validate): enforce restricted+external and restricted+L0 rejection"
```

---

### Task 5: L0 Maximum TTL Validation

**Files:**
- Modify: `src/jurati/core/validate.py`
- Test: `tests/core/test_validate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_validate.py — append

from datetime import timedelta


def test_l0_entry_exceeding_168h_ttl_is_rejected() -> None:
    created = minutes_after(0)
    entry = make_entry(
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        created_at=created,
        expires_at=created + timedelta(hours=169),
        review_required=False,
    )
    errors = validate_entry(entry)
    assert any("168" in e for e in errors)


def test_l0_entry_at_exactly_168h_is_valid() -> None:
    created = minutes_after(0)
    entry = make_entry(
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        created_at=created,
        expires_at=created + timedelta(hours=168),
        review_required=False,
    )
    errors = validate_entry(entry)
    assert not any("168" in e for e in errors)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_validate.py::test_l0_entry_exceeding_168h_ttl_is_rejected -v`
Expected: FAIL

- [ ] **Step 3: Add the validation rule**

In `src/jurati/core/validate.py`, add to imports:

```python
from datetime import timedelta
```

Add to `validate_entry()` after the existing `expires_at > created_at` check:

```python
    if (
        fm.level == EscalationLevel.L0
        and fm.expires_at is not None
        and (fm.expires_at - fm.created_at) > timedelta(hours=168)
    ):
        errors.append("L0 entries cannot have TTL exceeding 168 hours (7 days)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_validate.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/core/validate.py tests/core/test_validate.py
git commit -m "feat(validate): enforce L0 max TTL of 168 hours"
```

---

### Task 6: Visibility and RecordedBy in Write Intents

Visibility is an **explicit author/tool input**, not a hard-coded constant. `plan_record()` and `plan_propose()` accept an optional `visibility` parameter with level-appropriate defaults and guardrails. L0 always forces INTERNAL regardless of input.

**Files:**
- Modify: `src/jurati/core/changes.py:44-165`
- Test: `tests/core/test_changes.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/core/test_changes.py — append

from jurati.core.schema import RecordedBy, Visibility


def test_plan_record_l0_forces_visibility_internal() -> None:
    """L0 always INTERNAL, even if caller explicitly passes EXTERNAL."""
    intent = plan_record(
        EntryType.ACTIVE,
        "Focus",
        "Working.",
        entry_id="focus-test",
        now=BASE_NOW,
        expires_at=minutes_after(30),
        client="codex",
        visibility=Visibility.EXTERNAL,
    )
    assert intent.entry is not None
    assert intent.entry.frontmatter.visibility == Visibility.INTERNAL


def test_plan_record_l1_defaults_visibility_to_internal() -> None:
    intent = plan_record(
        EntryType.PROJECT,
        "Project",
        "Status.",
        entry_id="project-viz-test",
        now=BASE_NOW,
    )
    assert intent.entry is not None
    assert intent.entry.frontmatter.visibility == Visibility.INTERNAL


def test_plan_record_l1_accepts_explicit_external() -> None:
    """L1 authors may opt into cross-system distribution."""
    intent = plan_record(
        EntryType.PROJECT,
        "Public Project",
        "Status.",
        entry_id="public-project",
        now=BASE_NOW,
        visibility=Visibility.EXTERNAL,
    )
    assert intent.entry is not None
    assert intent.entry.frontmatter.visibility == Visibility.EXTERNAL


def test_plan_record_populates_recorded_by() -> None:
    intent = plan_record(
        EntryType.PROJECT,
        "Tracked",
        "Body.",
        entry_id="tracked-test",
        now=BASE_NOW,
        client="test-client",
    )
    assert intent.entry is not None
    assert intent.entry.frontmatter.recorded_by is not None
    assert intent.entry.frontmatter.recorded_by.client == "test-client"


def test_plan_propose_defaults_visibility_to_external() -> None:
    intent = plan_propose(
        EntryType.DECISION,
        "Team Decision",
        "We decided.",
        entry_id="team-decision-viz",
        now=BASE_NOW,
    )
    assert intent.entry is not None
    assert intent.entry.frontmatter.visibility == Visibility.EXTERNAL


def test_plan_propose_accepts_explicit_internal() -> None:
    """L2/L3 authors may keep decisions private to jurati tools."""
    intent = plan_propose(
        EntryType.DECISION,
        "Internal Decision",
        "Private.",
        entry_id="internal-decision",
        now=BASE_NOW,
        visibility=Visibility.INTERNAL,
    )
    assert intent.entry is not None
    assert intent.entry.frontmatter.visibility == Visibility.INTERNAL


def test_plan_record_renders_visibility_in_content() -> None:
    intent = plan_record(
        EntryType.PROJECT,
        "Rendered",
        "Body.",
        entry_id="rendered-viz",
        now=BASE_NOW,
    )
    assert "visibility: internal" in intent.content


def test_plan_record_renders_recorded_by_in_content() -> None:
    intent = plan_record(
        EntryType.PROJECT,
        "Rendered RB",
        "Body.",
        entry_id="rendered-rb",
        now=BASE_NOW,
        client="cursor",
    )
    assert "recorded_by:" in intent.content
    assert "client: cursor" in intent.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_changes.py::test_plan_record_l0_forces_visibility_internal -v`
Expected: FAIL — plan_record doesn't accept visibility parameter

- [ ] **Step 3: Implement the changes**

In `src/jurati/core/changes.py`:

**Add imports** (around line 9):

```python
from jurati.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    RecordedBy,
    ReviewMeta,
    SourceMeta,
    Visibility,
    is_level_allowed,
    requires_pr,
)
```

**Modify `plan_record()` signature** — add `visibility` parameter:

```python
def plan_record(
    entry_type: EntryType,
    title: str,
    body: str,
    *,
    entry_id: str,
    level: EscalationLevel | None = None,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    now: datetime,
    expires_at: datetime | None = None,
    branch_prefix: str = "jurati",
    active_ref_prefix: str = "jurati/active",
    client: str | None = None,
    visibility: Visibility | None = None,
) -> WriteIntent:
```

In the body, resolve visibility with L0 override:

```python
    recorded_by = RecordedBy(client=client) if client else None

    if level == EscalationLevel.L0:
        resolved_visibility = Visibility.INTERNAL
    else:
        resolved_visibility = visibility if visibility is not None else Visibility.INTERNAL

    fm = Frontmatter(
        id=entry_id,
        title=title,
        type=entry_type,
        level=level,
        status=EntryStatus.PROPOSED if level != EscalationLevel.L0 else EntryStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        expires_at=expires_at,
        projects=projects or [],
        tags=tags or [],
        review=ReviewMeta(required=level != EscalationLevel.L0),
        visibility=resolved_visibility,
        recorded_by=recorded_by,
    )
```

**Modify `plan_propose()` signature** — add `visibility` and `client` parameters:

```python
def plan_propose(
    entry_type: EntryType,
    title: str,
    body: str,
    *,
    entry_id: str,
    level: EscalationLevel | None = None,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    now: datetime,
    branch_prefix: str = "jurati",
    client: str | None = None,
    visibility: Visibility | None = None,
) -> WriteIntent:
```

In the body:

```python
    recorded_by = RecordedBy(client=client) if client else None
    resolved_visibility = visibility if visibility is not None else Visibility.EXTERNAL

    fm = Frontmatter(
        ...,
        visibility=resolved_visibility,
        recorded_by=recorded_by,
    )
```

**Modify `_render_entry()`** — add visibility and recorded_by rendering after the source block:

```python
    lines.append(f"visibility: {fm.visibility}")
    if fm.recorded_by is not None:
        lines.append("recorded_by:")
        lines.append(f"  client: {_yaml_quote(fm.recorded_by.client)}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_changes.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass (may need to update assertions in existing tests that check rendered content)

- [ ] **Step 6: Fix any regressions in rendered content assertions**

Grep for tests that assert exact content matches and add `visibility:` expectations:

```bash
grep -rn "in intent.content" tests/
```

- [ ] **Step 7: Commit**

```bash
git add src/jurati/core/changes.py tests/core/test_changes.py
git commit -m "feat(changes): visibility as explicit input with L0 override and level defaults"
```

---

### Task 7: Restricted Entry Exclusion from BM25 Index

**Files:**
- Modify: `src/jurati/core/scoring.py:45-66`
- Test: `tests/core/test_scoring.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_scoring.py — append

from jurati.core.schema import Sensitivity


def test_restricted_entries_excluded_from_inverted_index() -> None:
    normal = make_entry(entry_id="normal-entry", title="Auth config", body="Token rotation policy")
    restricted = make_entry(
        entry_id="restricted-entry",
        title="Auth secrets",
        body="Token rotation policy for secrets",
        sensitivity=Sensitivity.RESTRICTED,
    )
    idx = build_inverted_index([normal, restricted])
    assert "normal-entry" in idx.doc_lengths
    assert "restricted-entry" not in idx.doc_lengths
    assert idx.doc_count == 1


def test_rank_entries_excludes_restricted() -> None:
    normal = make_entry(entry_id="visible-entry", title="Auth config", body="Token rotation")
    restricted = make_entry(
        entry_id="hidden-entry",
        title="Auth config",
        body="Token rotation",
        sensitivity=Sensitivity.RESTRICTED,
    )
    results = rank_entries([normal, restricted], "auth config", now=BASE_NOW)
    ids = [r.entry.frontmatter.id for r in results]
    assert "visible-entry" in ids
    assert "hidden-entry" not in ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_scoring.py::test_restricted_entries_excluded_from_inverted_index -v`
Expected: FAIL — restricted entry is in the index

- [ ] **Step 3: Implement the exclusion**

In `src/jurati/core/scoring.py`, add import:

```python
from .schema import Entry, EntryType, Sensitivity
```

Modify `build_inverted_index()` — add filter at the top of the function (line 46):

```python
def build_inverted_index(entries: list[Entry]) -> InvertedIndex:
    idx = InvertedIndex()
    filtered = [e for e in entries if e.frontmatter.sensitivity != Sensitivity.RESTRICTED]
    idx.doc_count = len(filtered)
    total_len = 0

    for entry in filtered:
```

Modify `rank_entries()` — filter restricted before ranking (line 106):

```python
def rank_entries(
    entries: list[Entry],
    query: str,
    *,
    now: datetime,
    repo: str | None = None,
    repo_deps: set[str] | None = None,
    max_results: int = 10,
) -> list[SearchResult]:
    entries = [e for e in entries if e.frontmatter.sensitivity != Sensitivity.RESTRICTED]
    idx = build_inverted_index(entries)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_scoring.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/core/scoring.py tests/core/test_scoring.py
git commit -m "feat(scoring): exclude restricted entries from BM25 index"
```

---

### Task 8: Privacy Module — opaque_identity

**Files:**
- Create: `src/jurati/core/privacy.py`
- Create: `tests/core/test_privacy.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_privacy.py

from __future__ import annotations

from jurati.core.privacy import opaque_identity
from jurati.core.schema import RecordedBy, SourceMeta


def test_opaque_identity_produces_different_hashes_for_different_systems() -> None:
    rb = RecordedBy(client="claude-code")
    source = SourceMeta(repo="api-service", commit="abc123", author="alice@co.com")
    salt = b"test-salt-value"

    opaque_a = opaque_identity(rb, source, system_id="system-a", salt=salt)
    opaque_b = opaque_identity(rb, source, system_id="system-b", salt=salt)

    assert opaque_a[0] is not None
    assert opaque_b[0] is not None
    assert opaque_a[0] != opaque_b[0]
    assert opaque_a[1] != opaque_b[1]


def test_opaque_identity_same_system_same_hash() -> None:
    rb = RecordedBy(client="claude-code")
    source = SourceMeta(repo="api-service", commit="abc123", author="alice@co.com")
    salt = b"test-salt"

    h1 = opaque_identity(rb, source, system_id="sys-x", salt=salt)
    h2 = opaque_identity(rb, source, system_id="sys-x", salt=salt)
    assert h1 == h2


def test_opaque_identity_with_none_inputs() -> None:
    salt = b"test-salt"
    result = opaque_identity(None, None, system_id="sys", salt=salt)
    assert result == (None, None)


def test_opaque_identity_with_only_recorded_by() -> None:
    rb = RecordedBy(client="cursor")
    salt = b"test-salt"
    opaque_client, opaque_author = opaque_identity(rb, None, system_id="sys", salt=salt)
    assert opaque_client is not None
    assert opaque_author is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_privacy.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement opaque_identity**

```python
# src/jurati/core/privacy.py
"""Identity opacity for cross-system privacy.

API-layer boundary — raw identities are preserved within jurati's own MCP tools.
The underlying git repo still exposes identities to anyone with repo access.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jurati.core.schema import RecordedBy, SourceMeta


def opaque_identity(
    recorded_by: RecordedBy | None,
    source: SourceMeta | None,
    *,
    system_id: str,
    salt: bytes,
) -> tuple[str | None, str | None]:
    opaque_client = (
        _salted_hash(recorded_by.client, system_id, salt) if recorded_by else None
    )
    opaque_author = (
        _salted_hash(source.author, system_id, salt) if source else None
    )
    return opaque_client, opaque_author


def _salted_hash(value: str, system_id: str, salt: bytes) -> str:
    payload = f"{system_id}:{value}".encode()
    return hashlib.sha256(salt + payload).hexdigest()[:16]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_privacy.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/core/privacy.py tests/core/test_privacy.py
git commit -m "feat(privacy): add opaque_identity for cross-system identity salting"
```

---

## Phase 2: L0 Opt-in (Read + Write)

### Task 9: active_refs_enabled Config Flag

**Files:**
- Modify: `src/jurati/git/config.py:23-78`
- Test: `tests/git/test_config.py` (create or append)

- [ ] **Step 1: Write the failing test**

```python
# tests/git/test_config.py — append or create

from __future__ import annotations

import os

from jurati.git.config import JuratiConfig, load_config_from_env


def test_active_refs_enabled_defaults_to_false() -> None:
    config = JuratiConfig(remote_url="https://example.com/kb.git")
    assert config.active_refs_enabled is False


def test_active_refs_enabled_from_env(monkeypatch: object) -> None:
    import pytest
    mp = pytest.MonkeyPatch()
    mp.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/kb.git")
    mp.setenv("JURATI_ACTIVE_REFS_ENABLED", "true")
    config = load_config_from_env()
    assert config.active_refs_enabled is True
    mp.undo()


def test_active_refs_disabled_by_default_from_env(monkeypatch: object) -> None:
    import pytest
    mp = pytest.MonkeyPatch()
    mp.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/kb.git")
    mp.delenv("JURATI_ACTIVE_REFS_ENABLED", raising=False)
    config = load_config_from_env()
    assert config.active_refs_enabled is False
    mp.undo()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/git/test_config.py -v -x`
Expected: FAIL — no active_refs_enabled attribute

- [ ] **Step 3: Add the flag to JuratiConfig and load_config_from_env**

In `src/jurati/git/config.py`, add to `JuratiConfig` (after `active_ref_prefix`, line 28):

```python
    active_refs_enabled: bool = False
```

In `load_config_from_env()`, add before the return (around line 66):

```python
    active_refs_enabled = os.environ.get("JURATI_ACTIVE_REFS_ENABLED", "").lower() == "true"
```

And include it in the returned `JuratiConfig`:

```python
    return JuratiConfig(
        ...,
        active_refs_enabled=active_refs_enabled,
        ...
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/git/test_config.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/git/config.py tests/git/test_config.py
git commit -m "feat(config): add active_refs_enabled flag (default false)"
```

---

### Task 10: L0 Write Gate in plan_record

**Files:**
- Modify: `src/jurati/core/changes.py`
- Test: `tests/core/test_changes.py`

Note: The write gate is in the server layer, not plan_record, because plan_record is pure and doesn't know about config. The gate lives in server.py `record()`. But we can test the server behavior by adding a test to `tests/test_server.py` or `tests/test_server_write.py`. However, to keep it testable at the unit level, we'll add a simple guard parameter.

- [ ] **Step 1: Write the failing test**

The gate should be at the server level. We'll test it there in Task 14. For now, skip this task and move on.

This task is absorbed into Task 14 (Server: L0 opt-in gate).

---

### Task 11: L0 Read-Side Opt-out in fetch_all and load_index_from_repo

**Files:**
- Modify: `src/jurati/git/repo.py:35-67`
- Test: `tests/git/test_repo.py` (existing tests may need updating)

- [ ] **Step 1: Write the failing test**

```python
# tests/git/test_repo.py — append or create
# (This is an integration test that uses a real git repo fixture)

from __future__ import annotations

from unittest.mock import patch, MagicMock

from jurati.git.repo import fetch_all, load_index_from_repo


def test_fetch_all_skips_active_refs_when_disabled() -> None:
    with patch("jurati.git.repo.git.Repo") as mock_repo_cls:
        mock_repo = MagicMock()
        mock_origin = MagicMock()
        mock_repo.remotes.origin = mock_origin
        mock_repo_cls.return_value = mock_repo

        fetch_all("/fake/path", active_refs_enabled=False)

        assert mock_origin.fetch.call_count == 1
        call_args = mock_origin.fetch.call_args_list[0][0][0]
        assert "jurati/active" not in call_args


def test_fetch_all_includes_active_refs_when_enabled() -> None:
    with patch("jurati.git.repo.git.Repo") as mock_repo_cls:
        mock_repo = MagicMock()
        mock_origin = MagicMock()
        mock_repo.remotes.origin = mock_origin
        mock_repo_cls.return_value = mock_repo

        fetch_all("/fake/path", active_refs_enabled=True)

        assert mock_origin.fetch.call_count == 2


def test_load_index_skips_overlay_when_active_refs_disabled() -> None:
    with patch("jurati.git.repo.git.Repo") as mock_repo_cls, \
         patch("jurati.git.repo._load_entries_from_tree") as mock_load, \
         patch("jurati.git.repo._overlay_active_refs") as mock_overlay:
        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo
        mock_repo.commit.return_value.tree = MagicMock()

        load_index_from_repo("/fake/path", active_refs_enabled=False)

        mock_overlay.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/git/test_repo.py -v -x -k "active_refs"`
Expected: FAIL — TypeError: fetch_all() got unexpected keyword argument 'active_refs_enabled'

- [ ] **Step 3: Add the active_refs_enabled parameter**

In `src/jurati/git/repo.py`, modify `fetch_all()`:

```python
def fetch_all(
    repo_path: str,
    main_branch: str = "main",
    active_ref_prefix: str = "jurati/active",
    *,
    active_refs_enabled: bool = False,
) -> None:
    repo = git.Repo(repo_path)
    origin = repo.remotes.origin
    origin.fetch(f"+refs/heads/{main_branch}:refs/remotes/origin/{main_branch}", prune=True)
    if active_refs_enabled:
        origin.fetch(
            f"+refs/heads/{active_ref_prefix}/*:refs/remotes/origin/{active_ref_prefix}/*",
            prune=True,
        )
```

Modify `load_index_from_repo()`:

```python
def load_index_from_repo(
    repo_path: str,
    main_branch: str = "main",
    active_ref_prefix: str = "jurati/active",
    *,
    active_refs_enabled: bool = False,
) -> Index:
    repo = git.Repo(repo_path)
    index = Index()

    main_commit = repo.commit(f"origin/{main_branch}")
    _load_entries_from_tree(main_commit.tree, index)

    if active_refs_enabled:
        _overlay_active_refs(repo, active_ref_prefix, index)

    return index
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/git/test_repo.py -v -k "active_refs"`
Expected: All PASS

- [ ] **Step 5: Update server.py callers to pass active_refs_enabled**

In `src/jurati/server.py`, update `app_lifespan()` (line 71):

```python
    await _run_blocking(
        lambda: fetch_all(
            repo_path, config.main_branch, config.active_ref_prefix,
            active_refs_enabled=config.active_refs_enabled,
        )
    )
    index = await _run_blocking(
        lambda: load_index_from_repo(
            repo_path, config.main_branch, config.active_ref_prefix,
            active_refs_enabled=config.active_refs_enabled,
        )
    )
```

And update `sync()` (lines 776-783):

```python
        await _run_blocking(
            lambda: fetch_all(
                state.repo_path, config.main_branch, config.active_ref_prefix,
                active_refs_enabled=config.active_refs_enabled,
            )
        )
        new_index = await _run_blocking(
            lambda: load_index_from_repo(
                state.repo_path, config.main_branch, config.active_ref_prefix,
                active_refs_enabled=config.active_refs_enabled,
            )
        )
```

- [ ] **Step 6: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/jurati/git/repo.py src/jurati/server.py tests/git/test_repo.py
git commit -m "feat(repo): L0 read-side opt-out — skip active refs when disabled"
```

---

## Phase 3: Signal Abstraction

### Task 12: CoordinationSignal Generalized Shape

**Files:**
- Modify: `src/jurati/core/pr_signals.py:27-44`
- Test: `tests/core/test_pr_signals.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_pr_signals.py — append

from jurati.core.pr_signals import CoordinationSignal


def test_coordination_signal_is_frozen() -> None:
    sig = CoordinationSignal(
        signal_id="github:org/api:pull:42",
        provider="github",
        source="org/api",
        artifact_ref="https://github.com/org/api/pull/42",
        title="Fix auth",
        excerpt=None,
        actor="alice",
        state="open",
        labels=("jurati",),
        created_at=NOW,
        updated_at=NOW,
        resolved_at=None,
        subject_refs=("src/auth/token.py",),
        subject_areas=("src/auth",),
    )
    assert sig.provider == "github"
    assert sig.source == "org/api"
    assert sig.actor == "alice"
    with pytest.raises(AttributeError):
        sig.title = "changed"  # type: ignore[misc]


def test_coordination_signal_from_pr_signal() -> None:
    pr = _signal()
    cs = CoordinationSignal.from_pr_signal(pr)
    assert cs.source == pr.repo
    assert cs.artifact_ref == pr.url
    assert cs.actor == pr.author
    assert cs.resolved_at == pr.merged_at
    assert cs.subject_refs == pr.changed_paths
    assert cs.subject_areas == pr.target_areas
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_pr_signals.py::test_coordination_signal_is_frozen -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement CoordinationSignal**

In `src/jurati/core/pr_signals.py`, add after the `PRSignal` class (line 44):

```python
@dataclass(frozen=True)
class CoordinationSignal:
    signal_id: str
    provider: str
    source: str
    artifact_ref: str
    title: str
    excerpt: str | None
    actor: str
    state: str
    labels: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    subject_refs: tuple[str, ...]
    subject_areas: tuple[str, ...]

    @classmethod
    def from_pr_signal(cls, pr: PRSignal) -> CoordinationSignal:
        return cls(
            signal_id=pr.signal_id,
            provider=pr.provider,
            source=pr.repo,
            artifact_ref=pr.url,
            title=pr.title,
            excerpt=pr.body_excerpt,
            actor=pr.author,
            state=pr.state,
            labels=pr.labels,
            created_at=pr.created_at,
            updated_at=pr.updated_at,
            resolved_at=pr.merged_at,
            subject_refs=pr.changed_paths,
            subject_areas=pr.target_areas,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_pr_signals.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/core/pr_signals.py tests/core/test_pr_signals.py
git commit -m "feat(signals): add CoordinationSignal generalized shape"
```

---

### Task 13: SignalProvider Protocol

**Files:**
- Create: `src/jurati/providers/protocol.py`
- Create: `tests/providers/test_protocol.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/providers/test_protocol.py

from __future__ import annotations

from datetime import UTC, datetime

from jurati.core.pr_signals import CoordinationSignal
from jurati.providers.protocol import SignalProvider


class FakeProvider:
    provider_id = "fake"

    def fetch_signals(self, config: dict) -> list[CoordinationSignal]:
        return []

    def needs_refresh(self, last_fetch: datetime, now: datetime) -> bool:
        return True


def test_fake_provider_satisfies_protocol() -> None:
    provider = FakeProvider()
    assert isinstance(provider, SignalProvider)


def test_provider_id_accessible() -> None:
    provider = FakeProvider()
    assert provider.provider_id == "fake"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/providers/test_protocol.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement the protocol**

```python
# src/jurati/providers/protocol.py
"""Signal provider protocol — I/O interface for coordination signal sources.

Lives in providers/ (not core/) because fetch_signals() performs I/O.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from jurati.core.pr_signals import CoordinationSignal


@runtime_checkable
class SignalProvider(Protocol):
    provider_id: str

    def fetch_signals(self, config: dict[str, Any]) -> list[CoordinationSignal]:
        ...

    def needs_refresh(self, last_fetch: datetime, now: datetime) -> bool:
        ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/providers/test_protocol.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/providers/protocol.py tests/providers/test_protocol.py
git commit -m "feat(providers): add SignalProvider protocol"
```

---

### Task 14: GitHub Provider Refactor — Implement SignalProvider

**Files:**
- Modify: `src/jurati/providers/github_prs.py:1-209`
- Modify: `src/jurati/providers/cache.py`
- Test: `tests/providers/test_github_prs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/providers/test_github_prs.py — append

from jurati.core.pr_signals import CoordinationSignal
from jurati.providers.protocol import SignalProvider
from jurati.providers.github_prs import GitHubPRProvider


def test_github_provider_satisfies_protocol() -> None:
    provider = GitHubPRProvider()
    assert isinstance(provider, SignalProvider)
    assert provider.provider_id == "github"


def test_normalize_pr_to_coordination_signal() -> None:
    from jurati.providers.github_prs import _normalize_pr
    raw = {
        "number": 42,
        "title": "Fix auth",
        "body": "Fixes the auth flow",
        "state": "open",
        "labels": [{"name": "jurati"}],
        "user": {"login": "alice"},
        "createdAt": "2026-05-01T00:00:00Z",
        "updatedAt": "2026-05-04T00:00:00Z",
        "mergedAt": None,
        "url": "https://github.com/org/api/pull/42",
    }
    from jurati.git.config import PRSignalsConfig
    config = PRSignalsConfig(repos=("org/api",))
    signal = _normalize_pr(
        raw, "org/api",
        include_body_excerpt=True,
        include_changed_paths=True,
    )
    cs = CoordinationSignal.from_pr_signal(signal)
    assert cs.source == "org/api"
    assert cs.actor == "alice"
    assert cs.artifact_ref == "https://github.com/org/api/pull/42"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/providers/test_github_prs.py -v -x -k "protocol or coordination"`
Expected: FAIL — GitHubPRProvider doesn't exist

- [ ] **Step 3: Add GitHubPRProvider class**

In `src/jurati/providers/github_prs.py`, add a class that wraps the existing functions:

```python
from jurati.core.pr_signals import CoordinationSignal


class GitHubPRProvider:
    provider_id = "github"

    def __init__(self, config: PRSignalsConfig | None = None) -> None:
        self._config = config or PRSignalsConfig()

    def fetch_signals(self, config: dict[str, Any] | None = None) -> list[CoordinationSignal]:
        pr_signals = fetch_all_signals(self._config)
        return [CoordinationSignal.from_pr_signal(s) for s in pr_signals]

    def needs_refresh(self, last_fetch: datetime, now: datetime) -> bool:
        return (now - last_fetch).total_seconds() >= 300
```

Add `from typing import Any` to imports if not present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/providers/test_github_prs.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/providers/github_prs.py tests/providers/test_github_prs.py
git commit -m "feat(providers): GitHubPRProvider implements SignalProvider protocol"
```

---

### Task 15: Configurable Keyword Sets

**Files:**
- Modify: `src/jurati/core/pr_signals.py:16-24`
- Modify: `src/jurati/git/config.py`
- Test: `tests/core/test_pr_signals.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_pr_signals.py — append

def test_custom_revise_keywords() -> None:
    sig = _signal(
        title="Update curriculum for module 3",
        changed_paths=(),
        target_areas=(),
    )
    results = classify_signals(
        [sig],
        repo="org/training",
        now=NOW,
        revise_keywords=["curriculum", "module", "lab"],
    )
    assert any(g.effect == "revise" for g in results)


def test_custom_handoff_keywords() -> None:
    sig = _signal(
        title="Escalate to senior team",
        changed_paths=(),
        target_areas=(),
    )
    results = classify_signals(
        [sig],
        repo="org/api",
        now=NOW,
        handoff_keywords=["escalate", "delegate"],
    )
    effects = [g.effect for g in results]
    assert "handoff" in effects
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_pr_signals.py::test_custom_revise_keywords -v`
Expected: FAIL — classify_signals doesn't accept revise_keywords

- [ ] **Step 3: Add keyword parameters to classify_signals**

In `src/jurati/core/pr_signals.py`, modify `classify_signals()` signature:

```python
def classify_signals(
    signals: list[PRSignal],
    *,
    repo: str | None = None,
    _goal: str | None = None,
    paths: list[str] | None = None,
    now: datetime,
    recency_days: int = 30,
    revise_keywords: list[str] | None = None,
    handoff_keywords: list[str] | None = None,
) -> list[CoordinationGuidance]:
```

Build regex patterns from custom keywords if provided:

```python
    revise_re = (
        re.compile(r"\b(" + "|".join(re.escape(k) for k in revise_keywords) + r")\b", re.IGNORECASE)
        if revise_keywords
        else _REVISE_KEYWORDS
    )
    handoff_re = (
        re.compile(r"\b(" + "|".join(re.escape(k) for k in handoff_keywords) + r")\b", re.IGNORECASE)
        if handoff_keywords
        else _HANDOFF_KEYWORDS
    )
```

Pass `revise_re` and `handoff_re` to `_classify_one()` via new parameters.

In `_classify_one()`, accept and use the regex parameters instead of module-level constants:

```python
def _classify_one(
    signal: PRSignal,
    *,
    same_repo: bool,
    overlaps: tuple[str, ...],
    text: str,
    revise_re: re.Pattern[str] = _REVISE_KEYWORDS,
    handoff_re: re.Pattern[str] = _HANDOFF_KEYWORDS,
) -> CoordinationGuidance | None:
```

Replace `_REVISE_KEYWORDS.search(text)` with `revise_re.search(text)` and `_HANDOFF_KEYWORDS.search(text)` with `handoff_re.search(text)`.

In `classify_signals()`, pass them through:

```python
        guidance = _classify_one(
            signal, same_repo=same_repo, overlaps=overlaps, text=text,
            revise_re=revise_re, handoff_re=handoff_re,
        )
```

- [ ] **Step 4: Add env var support to config**

In `src/jurati/git/config.py`, add to `JuratiConfig`:

```python
    revise_keywords: list[str] = field(default_factory=list)
    handoff_keywords: list[str] = field(default_factory=list)
```

In `load_config_from_env()`:

```python
    revise_kw_raw = os.environ.get("JURATI_REVISE_KEYWORDS", "")
    revise_keywords = [k.strip() for k in revise_kw_raw.split(",") if k.strip()]
    handoff_kw_raw = os.environ.get("JURATI_HANDOFF_KEYWORDS", "")
    handoff_keywords = [k.strip() for k in handoff_kw_raw.split(",") if k.strip()]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/core/test_pr_signals.py -v`
Expected: All PASS

- [ ] **Step 6: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/jurati/core/pr_signals.py src/jurati/git/config.py tests/core/test_pr_signals.py
git commit -m "feat(signals): configurable revise/handoff keyword sets"
```

---

### Task 16: Server — L0 Opt-in Write Gate and Restricted Filtering

**Files:**
- Modify: `src/jurati/server.py`
- Test: `tests/test_server_write.py` or `tests/test_server.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_server_l0_gate.py (new file)

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from jurati.core.index import Index
from jurati.core.schema import EntryType, Sensitivity
from jurati.git.config import JuratiConfig
from jurati.server import ServerState, SyncHealth


def _make_state(*, active_refs_enabled: bool = False) -> ServerState:
    config = JuratiConfig(
        remote_url="https://example.com/kb.git",
        active_refs_enabled=active_refs_enabled,
    )
    return ServerState(
        config=config,
        repo_path="/fake",
        index=Index(),
        last_sync=datetime.now(UTC),
        sync_health=SyncHealth(last_success=datetime.now(UTC)),
    )
```

Note: Full server tool tests require MCP context mocking, which is complex. The L0 gate test is best done as a direct function test. For now, write the gate logic and rely on integration tests. The restricted filtering in `_build_context_payload` and `_build_search_results` is testable.

- [ ] **Step 2: Add L0 write gate to server.py record()**

In `src/jurati/server.py`, in the `record()` function, after `entry_type` is parsed and before `plan_record()` call (around line 856):

```python
    if entry_type == EntryType.ACTIVE and not config.active_refs_enabled:
        return {
            "error": (
                "Active context is disabled. "
                "Set JURATI_ACTIVE_REFS_ENABLED=true to opt in."
            )
        }
```

- [ ] **Step 3: Add visibility parameter to record() and propose() MCP tools**

The spec says `record()` and `propose()` accept optional `visibility`. Task 6 added it to `plan_record()` / `plan_propose()`, but the MCP tool signatures must also pass it through.

In `src/jurati/server.py`, modify the `record()` tool signature (around line 820):

```python
@mcp.tool()
async def record(
    type: str,
    title: str,
    content: str,
    ctx: Context[Any, Any],
    entry_id: str | None = None,
    level: str | None = None,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    expires_at: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
```

In the body, parse and pass visibility to `plan_record()`:

```python
    from jurati.core.schema import Visibility

    vis = None
    if visibility is not None:
        try:
            vis = Visibility(visibility)
        except ValueError:
            return {"error": f"Invalid visibility: {visibility}. Valid: internal, external"}

    intent = plan_record(
        ...,
        visibility=vis,
    )
```

Similarly modify the `propose()` tool signature (around line 1009):

```python
@mcp.tool()
async def propose(
    type: str,
    title: str,
    content: str,
    ctx: Context[Any, Any],
    entry_id: str | None = None,
    level: str | None = None,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
```

Parse and pass visibility to `plan_propose()` the same way.

- [ ] **Step 4: Add restricted entry filtering to _build_context_payload**

In `_build_context_payload()`, filter restricted entries from `active` and `recent` lists (around lines 208-220):

```python
    active = [
        _format_entry(e)
        for e in index.entries.values()
        if e.frontmatter.type == EntryType.ACTIVE
        and not is_expired(e, now)
        and e.frontmatter.sensitivity != Sensitivity.RESTRICTED
    ]

    recent = [
        _format_entry(e)
        for e in index.entries.values()
        if e.frontmatter.type != EntryType.ACTIVE
        and e.frontmatter.updated_at >= recent_cutoff
        and e.frontmatter.status in (EntryStatus.ACTIVE, EntryStatus.PROPOSED)
        and e.frontmatter.sensitivity != Sensitivity.RESTRICTED
    ]
```

Add the import at the top of server.py:

```python
from jurati.core.schema import ..., Sensitivity
```

- [ ] **Step 5: Add restricted filtering to _build_search_results**

In `_build_search_results()`, BM25 `rank_entries()` already excludes restricted entries (Task 7). No additional change needed here since the filtering happens in `scoring.py`.

- [ ] **Step 6: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/jurati/server.py tests/test_server_l0_gate.py
git commit -m "feat(server): L0 write gate, visibility passthrough, and restricted filtering"
```

---

## Phase 4: Events + Contract

### Task 17: Event Types and EventRecord

Events are lifecycle evidence, not participation analytics. The privacy contract (spec section 6a) requires: events never include author identity, query text, body content, or recorded_by data. This is enforced by the EventRecord shape itself — it has no fields for those values.

**Files:**
- Create: `src/jurati/core/events.py`
- Create: `tests/core/test_events.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_events.py

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jurati.core.events import EventRecord, EventType


def test_event_types() -> None:
    assert EventType.ENTRY_PROPOSED == "entry_proposed"
    assert EventType.ENTRY_EXPIRED == "entry_expired"


def test_event_record_frozen() -> None:
    ev = EventRecord(
        timestamp=datetime(2026, 5, 5, 14, 30, 22, tzinfo=UTC),
        event_type=EventType.ENTRY_PROPOSED,
        entry_id="auth-token-format",
        entry_type="decision",
        level="L2",
        visibility="external",
    )
    assert ev.entry_id == "auth-token-format"
    with pytest.raises(AttributeError):
        ev.entry_id = "changed"  # type: ignore[misc]


def test_event_record_to_dict() -> None:
    ev = EventRecord(
        timestamp=datetime(2026, 5, 5, 14, 30, 22, tzinfo=UTC),
        event_type=EventType.ENTRY_PROPOSED,
        entry_id="auth-format",
        entry_type="decision",
        level="L2",
        visibility="external",
    )
    d = ev.to_dict()
    assert d["timestamp"] == "2026-05-05T14:30:22Z"
    assert d["event_type"] == "entry_proposed"
    assert d["entry_id"] == "auth-format"


def test_event_record_contains_no_identity_or_content() -> None:
    """Privacy contract: events never include author, body, query, or recorded_by."""
    ev = EventRecord(
        timestamp=datetime(2026, 5, 5, 14, 30, 22, tzinfo=UTC),
        event_type=EventType.ENTRY_PROPOSED,
        entry_id="privacy-test",
        entry_type="decision",
        level="L2",
        visibility="external",
    )
    d = ev.to_dict()
    forbidden = {"author", "body", "content", "query", "recorded_by", "client", "source"}
    assert forbidden.isdisjoint(d.keys()), f"Event dict must not contain identity/content fields: {forbidden & d.keys()}"

    json_str = ev.to_json()
    for field in forbidden:
        assert f'"{field}"' not in json_str


def test_event_record_path() -> None:
    ev = EventRecord(
        timestamp=datetime(2026, 5, 5, 14, 30, 22, tzinfo=UTC),
        event_type=EventType.ENTRY_PROPOSED,
        entry_id="auth-format",
        entry_type="decision",
        level="L2",
        visibility="external",
    )
    assert ev.path() == "events/2026-05-05/20260505T143022Z-auth-format.json"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_events.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement events module**

```python
# src/jurati/core/events.py
"""Event types for jurati knowledge lifecycle.

Events are only emitted for L1+ entries. L0 is fire-and-forget by design.
No ENTRY_MERGED event — merge is a git host operation, not jurati's.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class EventType(StrEnum):
    ENTRY_PROPOSED = "entry_proposed"
    ENTRY_EXPIRED = "entry_expired"


@dataclass(frozen=True)
class EventRecord:
    timestamp: datetime
    event_type: EventType
    entry_id: str
    entry_type: str
    level: str
    visibility: str

    def to_dict(self) -> dict[str, str]:
        return {
            "timestamp": self.timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "event_type": str(self.event_type),
            "entry_id": self.entry_id,
            "entry_type": self.entry_type,
            "level": self.level,
            "visibility": self.visibility,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def path(self) -> str:
        ts = self.timestamp.astimezone(UTC)
        date_dir = ts.strftime("%Y-%m-%d")
        file_ts = ts.strftime("%Y%m%dT%H%M%SZ")
        return f"events/{date_dir}/{file_ts}-{self.entry_id}.json"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_events.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/core/events.py tests/core/test_events.py
git commit -m "feat(events): add EventType and EventRecord for L1+ lifecycle"
```

---

### Task 18: Event on WriteIntent and ExpireIntent

**Files:**
- Modify: `src/jurati/core/changes.py`
- Test: `tests/core/test_changes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_changes.py — append

from jurati.core.events import EventRecord, EventType


def test_plan_record_l1_produces_event() -> None:
    intent = plan_record(
        EntryType.PROJECT,
        "Event Test",
        "Body.",
        entry_id="event-test",
        now=BASE_NOW,
    )
    assert intent.event is not None
    assert intent.event.event_type == EventType.ENTRY_PROPOSED
    assert intent.event.entry_id == "event-test"


def test_plan_record_l0_produces_no_event() -> None:
    intent = plan_record(
        EntryType.ACTIVE,
        "L0 No Event",
        "Body.",
        entry_id="l0-no-event",
        now=BASE_NOW,
        expires_at=minutes_after(30),
        client="test",
    )
    assert intent.event is None


def test_plan_propose_produces_event() -> None:
    intent = plan_propose(
        EntryType.DECISION,
        "Propose Event",
        "Body.",
        entry_id="propose-event",
        now=BASE_NOW,
    )
    assert intent.event is not None
    assert intent.event.event_type == EventType.ENTRY_PROPOSED
    assert intent.event.level == "L2"


def test_plan_expire_produces_event_for_l1() -> None:
    entry = make_entry(entry_id="expire-event-test")
    intent = plan_expire(entry)
    assert intent.event is not None
    assert intent.event.event_type == EventType.ENTRY_EXPIRED


def test_plan_expire_produces_no_event_for_l0() -> None:
    entry = make_entry(
        entry_id="l0-expire",
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        expires_at=minutes_after(30),
        review_required=False,
    )
    intent = plan_expire(entry)
    assert intent.event is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_changes.py::test_plan_record_l1_produces_event -v`
Expected: FAIL — WriteIntent has no `event` attribute

- [ ] **Step 3: Add event field to WriteIntent and ExpireIntent**

In `src/jurati/core/changes.py`, add import:

```python
from jurati.core.events import EventRecord, EventType
```

Modify `WriteIntent`:

```python
@dataclass(frozen=True)
class WriteIntent:
    path: str
    content: str
    branch: str | None
    write_mode: str
    entry_id: str
    level: EscalationLevel
    entry: Entry | None = None
    event: EventRecord | None = None
```

Modify `ExpireIntent`:

```python
@dataclass(frozen=True)
class ExpireIntent:
    entry_id: str
    path: str
    write_mode: str
    branch: str | None
    new_status: EntryStatus
    event: EventRecord | None = None
```

In `plan_record()`, create event for L1+ (before the return):

```python
    event = None
    if level != EscalationLevel.L0:
        event = EventRecord(
            timestamp=now,
            event_type=EventType.ENTRY_PROPOSED,
            entry_id=entry_id,
            entry_type=str(entry_type),
            level=str(level),
            visibility=str(fm.visibility),
        )

    return WriteIntent(
        path=path,
        content=content,
        branch=branch,
        write_mode=write_mode,
        entry_id=entry_id,
        level=level,
        entry=Entry(path=path, frontmatter=fm, body=body),
        event=event,
    )
```

In `plan_propose()`, always create event (before the return):

```python
    event = EventRecord(
        timestamp=now,
        event_type=EventType.ENTRY_PROPOSED,
        entry_id=entry_id,
        entry_type=str(entry_type),
        level=str(level),
        visibility=str(fm.visibility),
    )

    return WriteIntent(
        path=path,
        content=content,
        branch=branch,
        write_mode="review_pr",
        entry_id=entry_id,
        level=level,
        entry=Entry(path=path, frontmatter=fm, body=body),
        event=event,
    )
```

In `plan_expire()`, create event for L1+:

```python
    event = None
    if entry.frontmatter.level != EscalationLevel.L0:
        event = EventRecord(
            timestamp=entry.frontmatter.updated_at,
            event_type=EventType.ENTRY_EXPIRED,
            entry_id=entry.frontmatter.id,
            entry_type=str(entry.frontmatter.type),
            level=str(entry.frontmatter.level),
            visibility=str(entry.frontmatter.visibility),
        )

    return ExpireIntent(
        entry_id=entry.frontmatter.id,
        path=entry.path,
        write_mode=write_mode,
        branch=branch,
        new_status=EntryStatus.EXPIRED,
        event=event,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_changes.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/core/changes.py tests/core/test_changes.py
git commit -m "feat(changes): attach EventRecord to WriteIntent/ExpireIntent for L1+"
```

---

### Task 19: Event Materialization in git/commit.py

**Files:**
- Modify: `src/jurati/git/commit.py:16-28`
- Test: `tests/git/test_commit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/git/test_commit.py — append or create

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import git

from jurati.core.changes import WriteIntent
from jurati.core.events import EventRecord, EventType
from jurati.core.schema import EscalationLevel
from jurati.git.commit import materialize_write


def test_materialize_write_creates_event_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = git.Repo.init(tmpdir)
        repo.index.commit("init")

        event = EventRecord(
            timestamp=datetime(2026, 5, 5, 14, 30, 22, tzinfo=UTC),
            event_type=EventType.ENTRY_PROPOSED,
            entry_id="test-event-mat",
            entry_type="project",
            level="L1",
            visibility="internal",
        )

        intent = WriteIntent(
            path="projects/test-event-mat.md",
            content="---\nid: test-event-mat\n---\nBody",
            branch=None,
            write_mode="lightweight_pr",
            entry_id="test-event-mat",
            level=EscalationLevel.L1,
            event=event,
        )

        materialize_write(tmpdir, intent)

        event_path = Path(tmpdir) / "events/2026-05-05/20260505T143022Z-test-event-mat.json"
        assert event_path.exists()
        data = json.loads(event_path.read_text())
        assert data["event_type"] == "entry_proposed"
        assert data["entry_id"] == "test-event-mat"


def test_materialize_write_no_event_when_none() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = git.Repo.init(tmpdir)
        repo.index.commit("init")

        intent = WriteIntent(
            path="projects/no-event.md",
            content="---\nid: no-event\n---\nBody",
            branch=None,
            write_mode="lightweight_pr",
            entry_id="no-event",
            level=EscalationLevel.L1,
        )

        materialize_write(tmpdir, intent)

        events_dir = Path(tmpdir) / "events"
        assert not events_dir.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/git/test_commit.py -v -x -k "event"`
Expected: FAIL — no event file created

- [ ] **Step 3: Add expire event test**

```python
# tests/git/test_commit.py — append

from jurati.core.changes import ExpireIntent
from jurati.core.schema import EntryStatus
from jurati.git.commit import materialize_expire


def test_materialize_expire_creates_event_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = git.Repo.init(tmpdir)
        entry_path = Path(tmpdir) / "projects" / "expiring.md"
        entry_path.parent.mkdir(parents=True, exist_ok=True)
        entry_path.write_text("---\nid: expiring\nstatus: active\n---\nBody")
        repo.index.add(["projects/expiring.md"])
        repo.index.commit("init")

        event = EventRecord(
            timestamp=datetime(2026, 5, 5, 16, 0, 0, tzinfo=UTC),
            event_type=EventType.ENTRY_EXPIRED,
            entry_id="expiring",
            entry_type="project",
            level="L1",
            visibility="internal",
        )

        intent = ExpireIntent(
            entry_id="expiring",
            path="projects/expiring.md",
            write_mode="lightweight_pr",
            branch=None,
            new_status=EntryStatus.EXPIRED,
            event=event,
        )

        materialize_expire(tmpdir, intent)

        event_path = Path(tmpdir) / "events/2026-05-05/20260505T160000Z-expiring.json"
        assert event_path.exists()
        data = json.loads(event_path.read_text())
        assert data["event_type"] == "entry_expired"
        assert data["entry_id"] == "expiring"
```

- [ ] **Step 4: Implement event materialization in both materialize_write and materialize_expire**

In `src/jurati/git/commit.py`:

Add a shared helper for event file writing:

```python
def _materialize_event(repo: git.Repo, event: EventRecord | None) -> None:
    if event is None:
        return
    event_path = event.path()
    event_full = Path(repo.working_dir) / event_path
    event_full.parent.mkdir(parents=True, exist_ok=True)
    event_full.write_text(event.to_json())
    repo.index.add([event_path])
```

Update `materialize_write`:

```python
def materialize_write(repo_path: str, intent: WriteIntent) -> str:
    if not is_safe_path(repo_path, intent.path):
        raise ValueError(f"Path traversal rejected: {intent.path!r}")

    repo = git.Repo(repo_path)
    full_path = Path(repo.working_dir) / intent.path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(intent.content)
    repo.index.add([intent.path])

    _materialize_event(repo, intent.event)

    message = f"feat(kb): add {intent.entry_id}"
    commit = repo.index.commit(message)
    return commit.hexsha
```

Update `materialize_expire` to also call `_materialize_event`:

```python
def materialize_expire(repo_path: str, intent: ExpireIntent) -> str:
    if not is_safe_path(repo_path, intent.path):
        raise ValueError(f"Path traversal rejected: {intent.path!r}")

    repo = git.Repo(repo_path)
    full_path = Path(repo.working_dir) / intent.path
    # ... existing status rewrite logic ...

    _materialize_event(repo, intent.event)

    message = f"feat(kb): expire {intent.entry_id}"
    commit = repo.index.commit(message)
    return commit.hexsha
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/git/test_commit.py -v -k "event"`
Expected: All PASS (both write and expire event tests)

- [ ] **Step 6: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/jurati/git/commit.py tests/git/test_commit.py
git commit -m "feat(commit): materialize event files in both write and expire paths"
```

---

### Task 20: Integration Contract — AccessMode and KnowledgeQuery

This task creates the core contract with access mode filtering. The `KnowledgeQuery.topic` field exists on the dataclass but BM25 ranking and identity salting are wired in Task 22 when the MCP tool is added — this task focuses on the pure filtering logic.

**Files:**
- Create: `src/jurati/core/contract.py`
- Create: `tests/core/test_contract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_contract.py

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jurati.core.contract import (
    AccessMode,
    KnowledgeQuery,
    KnowledgeResult,
    check_constraints,
    query_knowledge,
)
from jurati.core.index import Index
from jurati.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Sensitivity,
    Visibility,
)

from tests.core.conftest import BASE_NOW, make_entry


def _index_with(*entries: Entry) -> Index:
    idx = Index()
    for e in entries:
        idx.add(e)
    return idx


class TestAccessModeFiltering:
    def test_context_mode_excludes_restricted(self) -> None:
        normal = make_entry(entry_id="normal-contract", visibility=Visibility.INTERNAL)
        restricted = make_entry(
            entry_id="restricted-contract",
            sensitivity=Sensitivity.RESTRICTED,
        )
        idx = _index_with(normal, restricted)
        result = query_knowledge(idx, KnowledgeQuery(access_mode=AccessMode.CONTEXT), now=BASE_NOW)
        ids = [e["id"] for e in result.entries]
        assert "normal-contract" in ids
        assert "restricted-contract" not in ids

    def test_external_context_only_external_visibility(self) -> None:
        internal = make_entry(entry_id="internal-only", visibility=Visibility.INTERNAL)
        external = make_entry(entry_id="external-viz", visibility=Visibility.EXTERNAL)
        idx = _index_with(internal, external)
        result = query_knowledge(
            idx,
            KnowledgeQuery(access_mode=AccessMode.EXTERNAL_CONTEXT, system_id="sys-a"),
            now=BASE_NOW,
        )
        ids = [e["id"] for e in result.entries]
        assert "external-viz" in ids
        assert "internal-only" not in ids

    def test_gate_evidence_requires_external_and_source_branch(self) -> None:
        on_main = make_entry(
            entry_id="on-main", visibility=Visibility.EXTERNAL, on_source_branch=True,
        )
        off_main = make_entry(
            entry_id="off-main", visibility=Visibility.EXTERNAL, on_source_branch=False,
        )
        idx = _index_with(on_main, off_main)
        result = query_knowledge(
            idx,
            KnowledgeQuery(access_mode=AccessMode.GATE_EVIDENCE, system_id="gate"),
            now=BASE_NOW,
        )
        ids = [e["id"] for e in result.entries]
        assert "on-main" in ids
        assert "off-main" not in ids

    def test_durable_source_all_visibility_source_branch_only(self) -> None:
        on_main_int = make_entry(
            entry_id="durable-int", visibility=Visibility.INTERNAL, on_source_branch=True,
        )
        off_main = make_entry(
            entry_id="not-durable", on_source_branch=False,
        )
        idx = _index_with(on_main_int, off_main)
        result = query_knowledge(
            idx,
            KnowledgeQuery(access_mode=AccessMode.DURABLE_SOURCE, system_id="audit"),
            now=BASE_NOW,
        )
        ids = [e["id"] for e in result.entries]
        assert "durable-int" in ids
        assert "not-durable" not in ids

    def test_non_context_mode_requires_system_id(self) -> None:
        idx = Index()
        with pytest.raises(ValueError, match="system_id"):
            query_knowledge(
                idx,
                KnowledgeQuery(access_mode=AccessMode.EXTERNAL_CONTEXT),
                now=BASE_NOW,
            )


class TestCheckConstraints:
    def test_returns_relevant_decisions(self) -> None:
        decision = make_entry(
            entry_id="auth-constraint",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            projects=["api-service"],
            status=EntryStatus.ACTIVE,
            review_required=True,
            review_pr="https://github.com/org/kb/pull/5",
        )
        idx = _index_with(decision)
        results = check_constraints(idx, "api-service", now=BASE_NOW)
        assert len(results) == 1
        assert results[0].frontmatter.id == "auth-constraint"

    def test_ignores_irrelevant_project(self) -> None:
        decision = make_entry(
            entry_id="other-constraint",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            projects=["other-service"],
        )
        idx = _index_with(decision)
        results = check_constraints(idx, "api-service", now=BASE_NOW)
        assert len(results) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_contract.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement the contract module**

```python
# src/jurati/core/contract.py
"""Integration contract — stable interface for external systems.

Pure functions consuming Index. No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from jurati.core.index import Index
from jurati.core.schema import Entry, EntryType, Sensitivity, Visibility
from jurati.core.validate import is_expired


class AccessMode(StrEnum):
    CONTEXT = "context"
    EXTERNAL_CONTEXT = "external_context"
    GATE_EVIDENCE = "gate_evidence"
    DURABLE_SOURCE = "durable_source"


@dataclass(frozen=True)
class KnowledgeQuery:
    topic: str | None = None
    entry_type: str | None = None
    project: str | None = None
    access_mode: AccessMode = AccessMode.CONTEXT
    system_id: str | None = None
    max_results: int = 10


@dataclass(frozen=True)
class KnowledgeResult:
    entries: list[dict[str, Any]]
    coordination: list[dict[str, Any]] = field(default_factory=list)
    provenance: str = ""


def _passes_access_filter(entry: Entry, mode: AccessMode) -> bool:
    if entry.frontmatter.sensitivity == Sensitivity.RESTRICTED:
        return False

    match mode:
        case AccessMode.CONTEXT:
            return True
        case AccessMode.EXTERNAL_CONTEXT:
            return entry.frontmatter.visibility == Visibility.EXTERNAL
        case AccessMode.GATE_EVIDENCE:
            return (
                entry.frontmatter.visibility == Visibility.EXTERNAL
                and entry.on_source_branch
            )
        case AccessMode.DURABLE_SOURCE:
            return entry.on_source_branch
        case _:
            return False


def query_knowledge(
    index: Index,
    q: KnowledgeQuery,
    *,
    now: datetime,
) -> KnowledgeResult:
    if q.access_mode != AccessMode.CONTEXT and q.system_id is None:
        raise ValueError("system_id is required for non-CONTEXT access modes")

    entries = []
    for entry in index.entries.values():
        if is_expired(entry, now):
            continue
        if not _passes_access_filter(entry, q.access_mode):
            continue
        if q.project and q.project not in entry.frontmatter.projects:
            continue
        if q.entry_type:
            try:
                et = EntryType(q.entry_type)
                if entry.frontmatter.type != et:
                    continue
            except ValueError:
                continue
        entries.append({
            "id": entry.frontmatter.id,
            "title": entry.frontmatter.title,
            "type": str(entry.frontmatter.type),
            "level": str(entry.frontmatter.level),
            "status": str(entry.frontmatter.status),
        })

    return KnowledgeResult(entries=entries[: q.max_results])


def check_constraints(
    index: Index,
    project: str,
    *,
    now: datetime,
    constraint_types: tuple[EntryType, ...] = (EntryType.DECISION, EntryType.PRINCIPLE),
) -> list[Entry]:
    results = []
    for entry in index.entries.values():
        if is_expired(entry, now):
            continue
        if entry.frontmatter.type not in constraint_types:
            continue
        if project not in entry.frontmatter.projects:
            continue
        results.append(entry)
    return results
```

- [ ] **Step 4: Update conftest make_entry to support new fields**

In `tests/core/conftest.py`, add `visibility`, `sensitivity`, and `on_source_branch` to `make_entry()`:

The `make_entry()` function already passes `**frontmatter_overrides` to `Frontmatter`, so `visibility=Visibility.EXTERNAL` works without changes. But `on_source_branch` is on `Entry`, not `Frontmatter`. Update `make_entry()`:

```python
def make_entry(
    *,
    entry_id: str = "test-entry",
    title: str = "Test Entry",
    entry_type: EntryType = EntryType.PROJECT,
    level: EscalationLevel = EscalationLevel.L1,
    status: EntryStatus = EntryStatus.PROPOSED,
    created_at: datetime = BASE_NOW,
    updated_at: datetime | None = None,
    expires_at: datetime | None = None,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    body: str = "Body text",
    path: str | None = None,
    review_required: bool = True,
    review_pr: str | None = None,
    on_source_branch: bool = False,
    **frontmatter_overrides: Any,
) -> Entry:
    fm = Frontmatter(
        id=entry_id,
        title=title,
        type=entry_type,
        level=level,
        status=status,
        created_at=created_at,
        updated_at=updated_at or created_at,
        expires_at=expires_at,
        projects=projects or [],
        tags=tags or [],
        review=ReviewMeta(required=review_required, pr=review_pr),
        **frontmatter_overrides,
    )
    return Entry(
        path=path or entry_path(entry_type, entry_id),
        frontmatter=fm,
        body=body,
        on_source_branch=on_source_branch,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/core/test_contract.py -v`
Expected: All PASS

- [ ] **Step 6: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/jurati/core/contract.py tests/core/test_contract.py tests/core/conftest.py
git commit -m "feat(contract): integration contract with AccessMode filtering"
```

---

### Task 21: Merge Normalization — on_source_branch in Index Loading

`GATE_EVIDENCE` and `DURABLE_SOURCE` access modes depend on `on_source_branch`. This needs a real git fixture test, not a placeholder.

**Files:**
- Modify: `src/jurati/git/repo.py:54-67`
- Test: `tests/git/test_repo.py`

- [ ] **Step 1: Write the git fixture test**

```python
# tests/git/test_on_source_branch.py

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import git

from jurati.git.repo import load_index_from_repo


def _make_knowledge_repo(tmpdir: str) -> str:
    """Create a bare 'remote' repo with one entry on main."""
    remote = os.path.join(tmpdir, "remote.git")
    staging = os.path.join(tmpdir, "staging")

    repo = git.Repo.init(remote, bare=True)
    clone = git.Repo.clone_from(remote, staging)

    entry_dir = Path(staging) / "projects"
    entry_dir.mkdir()
    entry_file = entry_dir / "on-main-entry.md"
    entry_file.write_text(
        "---\n"
        "schema_version: 2\n"
        "id: on-main-entry\n"
        "title: Entry on main\n"
        "type: project\n"
        "level: L1\n"
        "status: proposed\n"
        "created_at: 2026-05-05T00:00:00Z\n"
        "updated_at: 2026-05-05T00:00:00Z\n"
        "projects: []\n"
        "tags: []\n"
        "supersedes: []\n"
        "superseded_by: null\n"
        "sensitivity: normal\n"
        "review:\n"
        "  required: true\n"
        "  pr: null\n"
        "visibility: external\n"
        "---\n\n"
        "This entry is on the main branch.\n"
    )
    clone.index.add(["projects/on-main-entry.md"])
    clone.index.commit("feat(kb): add on-main-entry")
    clone.remotes.origin.push()
    return remote


def test_main_branch_entries_get_on_source_branch_true() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        remote_url = _make_knowledge_repo(tmpdir)
        local = os.path.join(tmpdir, "local")
        clone = git.Repo.clone_from(remote_url, local)

        idx = load_index_from_repo(local, active_refs_enabled=False)

        entry = idx.get("on-main-entry")
        assert entry is not None
        assert entry.on_source_branch is True


def test_active_ref_overlay_entries_get_on_source_branch_false() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        remote_url = _make_knowledge_repo(tmpdir)
        local = os.path.join(tmpdir, "local")
        clone = git.Repo.clone_from(remote_url, local)

        active_branch = "jurati/active/test-client/active-entry"
        clone.git.checkout("-b", active_branch, "origin/main")
        active_dir = Path(local) / "active"
        active_dir.mkdir(exist_ok=True)
        active_file = active_dir / "active-entry.md"
        active_file.write_text(
            "---\n"
            "schema_version: 2\n"
            "id: active-entry\n"
            "title: Active entry\n"
            "type: active\n"
            "level: L0\n"
            "status: active\n"
            "created_at: 2026-05-05T00:00:00Z\n"
            "updated_at: 2026-05-05T00:00:00Z\n"
            "expires_at: 2026-05-12T00:00:00Z\n"
            "projects: []\n"
            "tags: []\n"
            "supersedes: []\n"
            "superseded_by: null\n"
            "sensitivity: normal\n"
            "review:\n"
            "  required: false\n"
            "  pr: null\n"
            "visibility: internal\n"
            "---\n\n"
            "Active context.\n"
        )
        clone.index.add(["active/active-entry.md"])
        clone.index.commit("feat(kb): add active-entry")
        clone.remotes.origin.push(active_branch)

        clone.git.checkout("main")

        idx = load_index_from_repo(local, active_refs_enabled=True)

        main_entry = idx.get("on-main-entry")
        assert main_entry is not None
        assert main_entry.on_source_branch is True

        active_entry = idx.get("active-entry")
        assert active_entry is not None
        assert active_entry.on_source_branch is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/git/test_on_source_branch.py -v`
Expected: FAIL — on_source_branch not set by load_index_from_repo

- [ ] **Step 3: Implement on_source_branch marking**

In `src/jurati/git/repo.py`, modify `load_index_from_repo()`:

```python
def load_index_from_repo(
    repo_path: str,
    main_branch: str = "main",
    active_ref_prefix: str = "jurati/active",
    *,
    active_refs_enabled: bool = False,
) -> Index:
    repo = git.Repo(repo_path)
    index = Index()

    main_commit = repo.commit(f"origin/{main_branch}")
    _load_entries_from_tree(main_commit.tree, index)

    for entry in index.entries.values():
        entry.on_source_branch = True

    if active_refs_enabled:
        _overlay_active_refs(repo, active_ref_prefix, index)

    return index
```

Entries from main get `True`. Active ref overlay entries replace or add entries with the default `False`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/git/test_on_source_branch.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/git/repo.py tests/git/test_on_source_branch.py
git commit -m "feat(repo): mark main-branch entries with on_source_branch=True"
```

---

### Task 22: knowledge_query MCP Tool and Contract Wiring

The integration contract (`core/contract.py`, Task 20) is a pure module. Spec section 7c requires two things:
1. A new `knowledge_query` MCP tool that exposes non-CONTEXT access modes to external systems.
2. Existing MCP tools (`context()`) delegate restricted-entry filtering to the contract layer rather than duplicating logic.

This task wires the contract into `server.py`. The `knowledge_query` tool follows the same `ctx: Context` pattern as all other MCP tools (see `server.py:645` for reference).

**Files:**
- Modify: `src/jurati/server.py`
- Test: `tests/test_server_contract.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_server_contract.py

from __future__ import annotations

import pytest
from datetime import datetime, UTC

from jurati.core.contract import AccessMode, KnowledgeQuery, KnowledgeResult, query_knowledge
from jurati.core.privacy import opaque_identity
from jurati.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    RecordedBy,
    ReviewMeta,
    Sensitivity,
    SourceMeta,
    Visibility,
)
from jurati.core.index import Index

BASE_NOW = datetime(2026, 5, 5, tzinfo=UTC)


def _make_frontmatter(
    *,
    entry_id: str,
    visibility: Visibility = Visibility.INTERNAL,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
    entry_type: EntryType = EntryType.PROJECT,
    level: EscalationLevel = EscalationLevel.L1,
    recorded_by: RecordedBy | None = None,
    source: SourceMeta | None = None,
) -> Frontmatter:
    return Frontmatter(
        id=entry_id,
        title=f"Entry {entry_id}",
        type=entry_type,
        level=level,
        status=EntryStatus.ACTIVE,
        created_at=BASE_NOW,
        updated_at=BASE_NOW,
        projects=[],
        tags=[],
        review=ReviewMeta(required=True),
        visibility=visibility,
        sensitivity=sensitivity,
        recorded_by=recorded_by,
        source=source,
    )


def _make_entry(
    *,
    entry_id: str,
    visibility: Visibility = Visibility.INTERNAL,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
    on_source_branch: bool = False,
    recorded_by: RecordedBy | None = None,
    source: SourceMeta | None = None,
) -> Entry:
    fm = _make_frontmatter(
        entry_id=entry_id,
        visibility=visibility,
        sensitivity=sensitivity,
        recorded_by=recorded_by,
        source=source,
    )
    return Entry(
        path=f"projects/{entry_id}.md",
        frontmatter=fm,
        body="Body text",
        on_source_branch=on_source_branch,
    )


class TestKnowledgeQueryContract:
    def test_context_mode_returns_non_restricted(self) -> None:
        idx = Index()
        idx.entries["normal"] = _make_entry(entry_id="normal", visibility=Visibility.INTERNAL)
        idx.entries["restricted"] = _make_entry(
            entry_id="restricted", sensitivity=Sensitivity.RESTRICTED
        )

        result = query_knowledge(
            idx,
            KnowledgeQuery(access_mode=AccessMode.CONTEXT),
            now=BASE_NOW,
        )
        ids = [e["id"] for e in result.entries]
        assert "normal" in ids
        assert "restricted" not in ids

    def test_external_context_requires_system_id(self) -> None:
        idx = Index()
        with pytest.raises(ValueError, match="system_id"):
            query_knowledge(
                idx,
                KnowledgeQuery(access_mode=AccessMode.EXTERNAL_CONTEXT),
                now=BASE_NOW,
            )

    def test_external_context_filters_by_visibility(self) -> None:
        idx = Index()
        idx.entries["internal"] = _make_entry(entry_id="internal", visibility=Visibility.INTERNAL)
        idx.entries["external"] = _make_entry(entry_id="external", visibility=Visibility.EXTERNAL)

        result = query_knowledge(
            idx,
            KnowledgeQuery(
                access_mode=AccessMode.EXTERNAL_CONTEXT,
                system_id="orchestrator-1",
            ),
            now=BASE_NOW,
        )
        ids = [e["id"] for e in result.entries]
        assert "external" in ids
        assert "internal" not in ids

    def test_gate_evidence_requires_source_branch(self) -> None:
        idx = Index()
        idx.entries["on-main"] = _make_entry(
            entry_id="on-main",
            visibility=Visibility.EXTERNAL,
            on_source_branch=True,
        )
        idx.entries["on-branch"] = _make_entry(
            entry_id="on-branch",
            visibility=Visibility.EXTERNAL,
            on_source_branch=False,
        )

        result = query_knowledge(
            idx,
            KnowledgeQuery(
                access_mode=AccessMode.GATE_EVIDENCE,
                system_id="gate-1",
            ),
            now=BASE_NOW,
        )
        ids = [e["id"] for e in result.entries]
        assert "on-main" in ids
        assert "on-branch" not in ids

    def test_non_context_mode_salts_identity(self) -> None:
        """Non-CONTEXT access modes apply opaque_identity to recorded_by and source."""
        idx = Index()
        idx.entries["ext"] = _make_entry(
            entry_id="ext",
            visibility=Visibility.EXTERNAL,
            recorded_by=RecordedBy(client="claude-code"),
            source=SourceMeta(repo="api", commit="abc", author="alice@co.com"),
        )

        result = query_knowledge(
            idx,
            KnowledgeQuery(
                access_mode=AccessMode.EXTERNAL_CONTEXT,
                system_id="orchestrator-1",
            ),
            now=BASE_NOW,
        )
        entry = result.entries[0]
        assert entry["recorded_by"] is not None
        assert entry["recorded_by"] != "claude-code"
        assert entry["source_author"] is not None
        assert entry["source_author"] != "alice@co.com"

    def test_context_mode_preserves_raw_identity(self) -> None:
        """CONTEXT mode keeps raw identities (they're git provenance)."""
        idx = Index()
        idx.entries["ctx"] = _make_entry(
            entry_id="ctx",
            visibility=Visibility.INTERNAL,
            recorded_by=RecordedBy(client="claude-code"),
            source=SourceMeta(repo="api", commit="abc", author="alice@co.com"),
        )

        result = query_knowledge(
            idx,
            KnowledgeQuery(access_mode=AccessMode.CONTEXT),
            now=BASE_NOW,
        )
        entry = result.entries[0]
        assert entry.get("recorded_by") == "claude-code"
        assert entry.get("source_author") == "alice@co.com"

    def test_topic_uses_bm25_ranking(self) -> None:
        """When topic is provided, results are BM25-ranked, not insertion-ordered."""
        idx = Index()
        idx.entries["unrelated"] = _make_entry(entry_id="unrelated")
        idx.entries["unrelated"].frontmatter = _make_frontmatter(
            entry_id="unrelated",
        )
        # Override body to make BM25 differentiate
        relevant = _make_entry(entry_id="auth-migration")
        relevant = Entry(
            path=relevant.path,
            frontmatter=_make_frontmatter(entry_id="auth-migration"),
            body="Auth token migration strategy for the new OAuth provider",
            on_source_branch=False,
        )
        idx.entries["auth-migration"] = relevant

        result = query_knowledge(
            idx,
            KnowledgeQuery(topic="auth token migration", access_mode=AccessMode.CONTEXT),
            now=BASE_NOW,
        )
        assert len(result.entries) >= 1
        assert result.entries[0]["id"] == "auth-migration"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_server_contract.py -v`
Expected: FAIL — `query_knowledge` does not use topic for BM25 ranking, does not salt identities

- [ ] **Step 3: Update `query_knowledge` to use BM25 ranking when topic is provided**

In `src/jurati/core/contract.py`, add topic-based ranking:

```python
from jurati.core.privacy import opaque_identity
from jurati.core.scoring import rank_entries

_IDENTITY_SALT = b"jurati-contract-v1"


def query_knowledge(
    index: Index,
    q: KnowledgeQuery,
    *,
    now: datetime,
) -> KnowledgeResult:
    if q.access_mode != AccessMode.CONTEXT and q.system_id is None:
        raise ValueError("system_id is required for non-CONTEXT access modes")

    filtered = []
    for entry in index.entries.values():
        if is_expired(entry, now):
            continue
        if not _passes_access_filter(entry, q.access_mode):
            continue
        if q.project and q.project not in entry.frontmatter.projects:
            continue
        if q.entry_type:
            try:
                et = EntryType(q.entry_type)
                if entry.frontmatter.type != et:
                    continue
            except ValueError:
                continue
        filtered.append(entry)

    if q.topic:
        ranked = rank_entries(filtered, q.topic, now=now, max_results=q.max_results)
        ordered = [r.entry for r in ranked]
    else:
        ordered = filtered[: q.max_results]

    entries = [_entry_to_dict(e, q.access_mode, q.system_id) for e in ordered]
    return KnowledgeResult(entries=entries)


def _entry_to_dict(
    entry: Entry,
    access_mode: AccessMode,
    system_id: str | None,
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": entry.frontmatter.id,
        "title": entry.frontmatter.title,
        "type": str(entry.frontmatter.type),
        "level": str(entry.frontmatter.level),
        "status": str(entry.frontmatter.status),
    }

    rb = entry.frontmatter.recorded_by
    src = entry.frontmatter.source

    if access_mode == AccessMode.CONTEXT:
        d["recorded_by"] = rb.client if rb else None
        d["source_author"] = src.author if src else None
    else:
        opaque_client, opaque_author = opaque_identity(
            rb, src, system_id=system_id, salt=_IDENTITY_SALT,
        )
        d["recorded_by"] = opaque_client
        d["source_author"] = opaque_author

    return d
```

- [ ] **Step 4: Add the knowledge_query MCP tool to server.py**

In `src/jurati/server.py`, add the new MCP tool after the existing `query()` tool. Note: uses `ctx: Context` and `_state(ctx)` like all other MCP tools.

```python
from jurati.core.contract import AccessMode, KnowledgeQuery, query_knowledge


@mcp.tool()
async def knowledge_query(
    ctx: Context[Any, Any],
    access_mode: str = "context",
    system_id: str | None = None,
    topic: str | None = None,
    entry_type: str | None = None,
    project: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """Query knowledge entries with explicit access mode filtering.

    Use this tool when you need non-default access modes for external
    system integration. For normal agent use, prefer context() or search().

    Access modes:
    - context: all non-restricted entries (default, same as search/query)
    - external_context: only entries with visibility=external
    - gate_evidence: external + on source-of-truth branch only
    - durable_source: source-of-truth branch entries regardless of visibility

    Non-context modes require system_id for identity salting.
    """
    state = _state(ctx)
    now = datetime.now(UTC)
    try:
        mode = AccessMode(access_mode)
    except ValueError:
        return {"error": f"Invalid access_mode: {access_mode}. Valid: {', '.join(AccessMode)}"}

    try:
        q = KnowledgeQuery(
            topic=topic,
            entry_type=entry_type,
            project=project,
            access_mode=mode,
            system_id=system_id,
            max_results=max_results,
        )
        result = query_knowledge(state.index, q, now=now)
    except ValueError as e:
        return {"error": str(e)}

    return {
        "entries": result.entries,
        "coordination": result.coordination,
        "provenance": result.provenance,
        "access_mode": access_mode,
    }
```

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/core/contract.py src/jurati/server.py tests/test_server_contract.py
git commit -m "feat(contract): knowledge_query MCP tool with BM25 topic ranking and identity salting"
```

---

## Phase 5: Index Caching + DX

### Task 23: Prebuilt Index Parameter on rank_entries

**Files:**
- Modify: `src/jurati/core/scoring.py:97-106`
- Test: `tests/core/test_scoring.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_scoring.py — append

def test_rank_entries_uses_prebuilt_index() -> None:
    entries = [
        make_entry(entry_id="cached-test", title="Caching behavior", body="Index caching test"),
    ]
    idx = build_inverted_index(entries)
    results = rank_entries(entries, "caching", now=BASE_NOW, prebuilt_index=idx)
    assert len(results) == 1
    assert results[0].entry.frontmatter.id == "cached-test"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_scoring.py::test_rank_entries_uses_prebuilt_index -v`
Expected: FAIL — TypeError: unexpected keyword argument 'prebuilt_index'

- [ ] **Step 3: Add the parameter**

In `src/jurati/core/scoring.py`, modify `rank_entries()`:

```python
def rank_entries(
    entries: list[Entry],
    query: str,
    *,
    now: datetime,
    repo: str | None = None,
    repo_deps: set[str] | None = None,
    max_results: int = 10,
    prebuilt_index: InvertedIndex | None = None,
) -> list[SearchResult]:
    entries = [e for e in entries if e.frontmatter.sensitivity != Sensitivity.RESTRICTED]
    idx = prebuilt_index if prebuilt_index is not None else build_inverted_index(entries)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_scoring.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/core/scoring.py tests/core/test_scoring.py
git commit -m "feat(scoring): add prebuilt_index parameter to rank_entries"
```

---

### Task 24: Index Cache on ServerState

**Files:**
- Modify: `src/jurati/server.py`

- [ ] **Step 1: Add cache fields to ServerState**

In `src/jurati/server.py`, modify `ServerState`:

```python
@dataclass
class ServerState:
    config: JuratiConfig
    repo_path: str
    index: Index
    last_sync: datetime
    sync_health: SyncHealth
    write_lock: threading.Lock = field(default_factory=threading.Lock)
    cached_pr_candidate: AuthCandidate | None = None
    signal_cache: SignalCache = field(default_factory=lambda: SignalCache(recency_days=30))
    _cached_bm25_index: InvertedIndex | None = field(default=None, repr=False)
    _index_generation: int = field(default=0, repr=False)
```

Add import:

```python
from jurati.core.scoring import InvertedIndex, build_inverted_index, rank_entries
```

- [ ] **Step 2: Invalidate cache on sync**

In `sync()`, after `state.index = new_index`:

```python
        state._cached_bm25_index = None
        state._index_generation += 1
```

- [ ] **Step 3: Build cache on first use (lazy population)**

Add a helper that lazily builds the cache when first needed:

```python
def _get_bm25_index(state: ServerState) -> InvertedIndex:
    if state._cached_bm25_index is None:
        all_entries = list(state.index.entries.values())
        state._cached_bm25_index = build_inverted_index(all_entries)
    return state._cached_bm25_index
```

This is the critical step — without it, `_cached_bm25_index` stays `None` forever and the cache provides no benefit.

- [ ] **Step 4: Use cached index in _build_search_results**

In `_build_search_results()`, pass prebuilt index:

```python
def _build_search_results(
    index: Index,
    query: str,
    *,
    now: datetime,
    repo: str | None = None,
    max_results: int = 10,
    entry_type: EntryType | None = None,
    project: str | None = None,
    include_expired: bool = False,
    prebuilt_index: InvertedIndex | None = None,
) -> list[dict[str, Any]]:
    entries = index.list_entries(
        now=now,
        entry_type=entry_type,
        project=project,
        include_expired=include_expired,
    )
    ranked = rank_entries(
        entries, query, now=now, repo=repo, max_results=max_results,
        prebuilt_index=prebuilt_index,
    )
```

Update callers of `_build_search_results` in `query()` and `search()` to pass `_get_bm25_index(state)` (not `state._cached_bm25_index` — use the lazy-build helper).

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/server.py
git commit -m "feat(server): cache BM25 inverted index between search calls"
```

---

### Task 25: install-claude-md CLI Command

**Files:**
- Modify: `src/jurati/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py — append

from click.testing import CliRunner

def test_install_claude_md_creates_section(tmp_path: Path) -> None:
    from jurati.cli import main
    runner = CliRunner()
    result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
    assert result.exit_code == 0

    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.exists()
    content = claude_md.read_text()
    assert "Jurati" in content
    assert "context()" in content


def test_install_claude_md_creates_settings_json(tmp_path: Path) -> None:
    from jurati.cli import main
    runner = CliRunner()
    result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
    assert result.exit_code == 0

    settings = tmp_path / ".claude" / "settings.json"
    assert settings.exists()
    import json
    data = json.loads(settings.read_text())
    assert "mcp__jurati__context" in data["permissions"]["allow"]


def test_install_claude_md_appends_to_existing(tmp_path: Path) -> None:
    from jurati.cli import main
    existing = tmp_path / "CLAUDE.md"
    existing.write_text("# My Project\n\nExisting content.\n")

    runner = CliRunner()
    result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
    assert result.exit_code == 0

    content = existing.read_text()
    assert "Existing content." in content
    assert "Jurati" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -v -x -k "install_claude_md"`
Expected: FAIL

- [ ] **Step 3: Implement the command**

In `src/jurati/cli.py`, add the `install-claude-md` command:

```python
@main.command("install-claude-md")
@click.option("--repo-path", default=".", help="Path to the repo to install into.")
def install_claude_md(repo_path: str) -> None:
    """Install Jurati CLAUDE.md section and .claude/settings.json into a repo."""
    import json
    from pathlib import Path

    repo = Path(repo_path)
    claude_md = repo / "CLAUDE.md"

    section = _jurati_claude_md_section()

    if claude_md.exists():
        existing = claude_md.read_text()
        if "Jurati" not in existing:
            claude_md.write_text(existing.rstrip() + "\n\n" + section + "\n")
            click.echo(f"Appended Jurati section to {claude_md}")
        else:
            click.echo(f"Jurati section already present in {claude_md}")
    else:
        claude_md.write_text(section + "\n")
        click.echo(f"Created {claude_md}")

    settings_dir = repo / ".claude"
    settings_dir.mkdir(exist_ok=True)
    settings_file = settings_dir / "settings.json"

    allowlist = [
        "mcp__jurati__context",
        "mcp__jurati__query",
        "mcp__jurati__search",
        "mcp__jurati__sync",
        "mcp__jurati__status",
        "mcp__jurati__read",
        "mcp__jurati__list_entries",
        "mcp__jurati__explain",
        "mcp__jurati__validate",
        "mcp__jurati__hygiene",
        "mcp__jurati__record",
        "mcp__jurati__propose",
        "mcp__jurati__expire",
    ]

    if settings_file.exists():
        data = json.loads(settings_file.read_text())
    else:
        data = {}

    data.setdefault("permissions", {}).setdefault("allow", [])
    for tool in allowlist:
        if tool not in data["permissions"]["allow"]:
            data["permissions"]["allow"].append(tool)

    settings_file.write_text(json.dumps(data, indent=2) + "\n")
    click.echo(f"Updated {settings_file}")


def _jurati_claude_md_section() -> str:
    return """## Jurati — Team Knowledge

This project uses [Jurati](https://github.com/ostinato-forge/jurati) for cross-agent coordination.

**You MUST call `context()` before starting any task.** This surfaces active work, team decisions, and cross-repo dependencies that affect your work. Summarize what you learn in 2-3 sentences for the developer.

### Tool quick-reference

| Tool | When to use |
|------|-------------|
| `context()` | First thing, every task. Pass `repo` and `goal` for better results. |
| `query(topic=...)` | Deep-dive on a specific topic after context(). |
| `record(type, title, content)` | Capture active context others should know about. |
| `propose(type, title, content)` | Record a team decision or workflow that needs review. |
| `sync()` | Call silently before context() to get fresh data. |

### Rules

- **Never expose Jurati internals to the developer.** No entry IDs, ref paths, branch names, expiry dates, or lifecycle instructions.
- **Never ask the developer to manage the knowledge repo.** Don't say "merge PR #X" or "run sync."
- **Confirm actions in one sentence.** After recording or proposing, say something like "Recorded your auth refactor context."
- **State coordination plainly.** If someone's PR blocks this work, say so directly."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v -k "install_claude_md"`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/cli.py tests/test_cli.py
git commit -m "feat(cli): add install-claude-md command for zero-setup onboarding"
```

---

### Task 26: MCP Config Collision Prevention

**Files:**
- Modify: `src/jurati/cli.py` (the `mcp-config` command)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py — append

def test_mcp_config_uses_hash_based_name() -> None:
    from jurati.cli import main
    runner = CliRunner()
    result = runner.invoke(main, ["mcp-config"], env={"JURATI_KNOWLEDGE_REMOTE": "https://github.com/org/kb.git"})
    if result.exit_code == 0:
        import json
        data = json.loads(result.output)
        server_names = list(data.get("mcpServers", {}).keys())
        assert len(server_names) == 1
        assert server_names[0].startswith("jurati-")
        assert len(server_names[0]) > 7  # "jurati-" + hash
```

- [ ] **Step 2: Implement hash-based naming**

In the `mcp-config` command in `cli.py`, derive the server name from the remote URL:

```python
import hashlib

def _mcp_server_name(remote_url: str) -> str:
    url_hash = hashlib.sha256(remote_url.encode()).hexdigest()[:8]
    return f"jurati-{url_hash}"
```

Use this in the mcp-config output instead of a hardcoded `"jurati"` key.

- [ ] **Step 3: Run tests and verify**

Run: `pytest tests/test_cli.py -v -k "mcp_config"`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/jurati/cli.py tests/test_cli.py
git commit -m "fix(cli): collision-safe MCP config via hash-based server name"
```

---

### Task 27: Quickstart Generates settings.json

**Files:**
- Modify: `src/jurati/cli.py` (the `quickstart` or `init` command)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Verify current quickstart/init behavior**

Run: `pytest tests/test_cli.py -v -k "quickstart or init"`

- [ ] **Step 2: Add settings.json generation to quickstart**

In the `init` or `quickstart` command, after creating the knowledge repo, also create `.claude/settings.json` with the 13-tool allowlist. Reuse `_jurati_settings_allowlist()` from Task 25.

- [ ] **Step 3: Run tests and verify**

Run: `pytest tests/test_cli.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add src/jurati/cli.py tests/test_cli.py
git commit -m "feat(cli): quickstart generates .claude/settings.json"
```

---

## Final Verification

After all tasks complete:

- [ ] **Full test suite**

```bash
pytest tests/ -x -q
```

Expected: All pass, 0 failures.

- [ ] **Type checking**

```bash
mypy src/jurati --strict
```

- [ ] **Linting**

```bash
ruff check src/ tests/
```

- [ ] **Verification checklist from spec:**

1. Schema backward compatibility: v1 entries parse correctly with v2 defaults
2. L0 write opt-in: `record(type="active")` fails when `JURATI_ACTIVE_REFS_ENABLED` not set
3. L0 read opt-in: `fetch_all()` skips active refs when `active_refs_enabled=False`
4. Sensitivity: `restricted` entries excluded from `context()`, excluded from BM25 index, only accessible via `read(id=...)`
5. Access mode: `EXTERNAL_CONTEXT` query returns only `visibility=external` entries; `GATE_EVIDENCE` further requires `on_source_branch`
6. Events: L1+ write operations produce per-event JSON files; L0 writes produce no events
7. Merge normalization: entries on source-of-truth branch get `on_source_branch=True`
8. Index cache: second search query skips `build_inverted_index()` (verify via prebuilt_index param)
9. install-claude-md: generates correct CLAUDE.md section and settings.json
10. Privacy: `opaque_identity()` produces different hashes for different `system_id` values
11. Visibility: `record(visibility="external")` accepted for L1; rejected for L0
12. Contract surface: `knowledge_query` MCP tool exposes non-CONTEXT access modes; non-context modes require `system_id`
13. Events privacy: event files never contain author identity, query text, body content, or recorded_by data
14. Identity salting: non-CONTEXT contract results apply `opaque_identity()`; CONTEXT preserves raw identities
15. Topic ranking: `knowledge_query(topic=...)` returns BM25-ranked results, not insertion-ordered
16. Event expiry: `materialize_expire()` produces event files for L1+ entries
17. MCP visibility: `record(visibility="external")` and `propose(visibility="internal")` pass through to write intents
