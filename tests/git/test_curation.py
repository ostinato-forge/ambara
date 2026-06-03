from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import frontmatter
import git
import pytest

from ambara.core.changes import render_entry
from ambara.core.paths import entry_path
from ambara.core.schema import (
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    ReviewMeta,
)
from ambara.git.curation import (
    default_curation_report_branch,
    default_curation_report_path,
    materialize_curation_report,
)

NOW = datetime(2026, 5, 25, 9, 30, tzinfo=UTC)


def _init_repo(tmp_path: Path) -> git.Repo:
    repo = git.Repo.init(tmp_path / "repo")
    with repo.config_writer() as writer:
        writer.set_value("user", "name", "Ambara Test")
        writer.set_value("user", "email", "ambara-test@example.com")
    readme = Path(repo.working_dir) / "README.md"
    readme.write_text("# knowledge repo\n")
    repo.index.add(["README.md"])
    repo.index.commit("initial commit")
    return repo


def _write_entry(
    repo: git.Repo,
    *,
    entry_id: str = "auth-token-decision",
    entry_type: EntryType = EntryType.DECISION,
    status: EntryStatus = EntryStatus.ACTIVE,
) -> str:
    level = EscalationLevel.L0 if entry_type == EntryType.ACTIVE else EscalationLevel.L2
    fm = Frontmatter(
        id=entry_id,
        title="Auth token decision",
        type=entry_type,
        level=level,
        status=status,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        expires_at=datetime(2026, 1, 2, tzinfo=UTC) if entry_type == EntryType.ACTIVE else None,
        projects=["auth"],
        tags=["tokens"],
        review=ReviewMeta(required=True),
    )
    path = entry_path(entry_type, entry_id)
    full_path = Path(repo.working_dir) / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(render_entry(fm, "Use server-driven token rotation."))
    repo.index.add([path])
    repo.index.commit(f"add {entry_id}")
    return path


def test_default_curation_report_names_are_date_scoped() -> None:
    assert default_curation_report_branch(NOW) == "ambara/curation/2026-05-25"
    assert default_curation_report_path(NOW) == ".ambara/curation/2026-05-25-weekly-hygiene.md"


def test_materialize_curation_report_writes_review_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    result = materialize_curation_report(
        str(repo.working_dir),
        "## Weekly Knowledge Hygiene\n\n- review old-decision",
        branch="ambara/curation/test",
        now=NOW,
    )

    assert len(result.commit) == 40
    assert result.branch == "ambara/curation/test"
    assert result.path == ".ambara/curation/2026-05-25-weekly-hygiene.md"
    assert repo.active_branch.name == "ambara/curation/test"
    report = Path(repo.working_dir) / result.path
    assert report.read_text().endswith("\n")
    assert "review old-decision" in report.read_text()
    assert "add curation report 2026-05-25" in repo.head.commit.message


def test_materialize_curation_report_marks_entries_for_revalidation(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    entry_path = _write_entry(repo)

    result = materialize_curation_report(
        str(repo.working_dir),
        "## Weekly Knowledge Hygiene\n\n- revalidate auth-token-decision",
        branch="ambara/curation/revalidate",
        now=NOW,
        revalidation_entry_ids=("auth-token-decision",),
    )

    assert result.marked_paths == (entry_path,)
    post = frontmatter.load(Path(repo.working_dir) / entry_path)
    assert post.metadata["review_after"] == "2026-05-25T09:30:00Z"
    assert post.metadata["updated_at"] == "2026-05-25T09:30:00Z"
    changed_paths = [item.a_path for item in repo.head.commit.diff("HEAD~1")]
    assert ".ambara/curation/2026-05-25-weekly-hygiene.md" in changed_paths
    assert entry_path in changed_paths


def test_materialize_curation_report_expires_active_entries(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    entry_path = _write_entry(
        repo,
        entry_id="current-task",
        entry_type=EntryType.ACTIVE,
    )

    result = materialize_curation_report(
        str(repo.working_dir),
        "## Weekly Knowledge Hygiene\n\n- expire current-task",
        branch="ambara/curation/expire-active",
        now=NOW,
        expired_active_entry_ids=("current-task",),
    )

    assert result.expired_paths == (entry_path,)
    post = frontmatter.load(Path(repo.working_dir) / entry_path)
    assert post.metadata["status"] == "expired"
    assert post.metadata["updated_at"] == "2026-05-25T09:30:00Z"
    changed_paths = [item.a_path for item in repo.head.commit.diff("HEAD~1")]
    assert ".ambara/curation/2026-05-25-weekly-hygiene.md" in changed_paths
    assert entry_path in changed_paths


def test_materialize_curation_report_accepts_custom_curation_path(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    result = materialize_curation_report(
        str(repo.working_dir),
        "## Weekly Knowledge Hygiene",
        branch="ambara/curation/custom-path",
        path=".ambara/curation/manual-review.md",
        now=NOW,
    )

    assert result.path == ".ambara/curation/manual-review.md"
    assert (Path(repo.working_dir) / ".ambara/curation/manual-review.md").exists()


def test_materialize_curation_report_rejects_empty_body(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    with pytest.raises(ValueError, match="must not be empty"):
        materialize_curation_report(
            str(repo.working_dir),
            "  \n",
            branch="ambara/curation/test",
            now=NOW,
        )


def test_materialize_curation_report_rejects_path_traversal(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    with pytest.raises(ValueError, match="Path traversal rejected"):
        materialize_curation_report(
            str(repo.working_dir),
            "body",
            branch="ambara/curation/test",
            path="../weekly-hygiene.md",
            now=NOW,
        )


def test_materialize_curation_report_rejects_missing_revalidation_target(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)

    with pytest.raises(ValueError, match="target not found: missing-entry"):
        materialize_curation_report(
            str(repo.working_dir),
            "body",
            branch="ambara/curation/test",
            now=NOW,
            revalidation_entry_ids=("missing-entry",),
        )


def test_materialize_curation_report_rejects_active_revalidation_target(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _write_entry(repo, entry_id="active-status", entry_type=EntryType.ACTIVE)

    with pytest.raises(ValueError, match="Cannot mark active entry"):
        materialize_curation_report(
            str(repo.working_dir),
            "body",
            branch="ambara/curation/test",
            now=NOW,
            revalidation_entry_ids=("active-status",),
        )


def test_materialize_curation_report_rejects_missing_active_expiry_target(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)

    with pytest.raises(ValueError, match="active expiry target not found: missing-entry"):
        materialize_curation_report(
            str(repo.working_dir),
            "body",
            branch="ambara/curation/test",
            now=NOW,
            expired_active_entry_ids=("missing-entry",),
        )


def test_materialize_curation_report_rejects_non_active_expiry_target(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _write_entry(repo, entry_id="auth-token-decision")

    with pytest.raises(ValueError, match="Cannot expire non-active entry"):
        materialize_curation_report(
            str(repo.working_dir),
            "body",
            branch="ambara/curation/test",
            now=NOW,
            expired_active_entry_ids=("auth-token-decision",),
        )


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("README.md", "under .ambara/curation"),
        ("decisions/old-decision.md", "under .ambara/curation"),
        (".ambara/curation/report.txt", "Markdown file"),
        (".ambara/curation/../README.md", "Invalid curation report path"),
    ],
)
def test_materialize_curation_report_rejects_non_report_paths(
    tmp_path: Path,
    path: str,
    message: str,
) -> None:
    repo = _init_repo(tmp_path)

    with pytest.raises(ValueError, match=message):
        materialize_curation_report(
            str(repo.working_dir),
            "body",
            branch="ambara/curation/test",
            path=path,
            now=NOW,
        )


def test_materialize_curation_report_requires_clean_repo(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (Path(repo.working_dir) / "scratch.txt").write_text("dirty")

    with pytest.raises(ValueError, match="working tree must be clean"):
        materialize_curation_report(
            str(repo.working_dir),
            "body",
            branch="ambara/curation/test",
            now=NOW,
        )


def test_materialize_curation_report_same_branch_rerun_fails_explicitly(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    materialize_curation_report(
        str(repo.working_dir),
        "first body",
        branch="ambara/curation/test",
        now=NOW,
    )

    with pytest.raises(git.exc.GitCommandError, match="already exists"):
        materialize_curation_report(
            str(repo.working_dir),
            "second body",
            branch="ambara/curation/test",
            now=NOW,
        )
