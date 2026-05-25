from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import git
import pytest

from jurati.git.curation import (
    default_curation_report_branch,
    default_curation_report_path,
    materialize_curation_report,
)

NOW = datetime(2026, 5, 25, 9, 30, tzinfo=UTC)


def _init_repo(tmp_path: Path) -> git.Repo:
    repo = git.Repo.init(tmp_path / "repo")
    with repo.config_writer() as writer:
        writer.set_value("user", "name", "Jurati Test")
        writer.set_value("user", "email", "jurati-test@example.com")
    readme = Path(repo.working_dir) / "README.md"
    readme.write_text("# knowledge repo\n")
    repo.index.add(["README.md"])
    repo.index.commit("initial commit")
    return repo


def test_default_curation_report_names_are_date_scoped() -> None:
    assert default_curation_report_branch(NOW) == "jurati/curation/2026-05-25"
    assert default_curation_report_path(NOW) == ".jurati/curation/2026-05-25-weekly-hygiene.md"


def test_materialize_curation_report_writes_review_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    result = materialize_curation_report(
        str(repo.working_dir),
        "## Weekly Knowledge Hygiene\n\n- review old-decision",
        branch="jurati/curation/test",
        now=NOW,
    )

    assert len(result.commit) == 40
    assert result.branch == "jurati/curation/test"
    assert result.path == ".jurati/curation/2026-05-25-weekly-hygiene.md"
    assert repo.active_branch.name == "jurati/curation/test"
    report = Path(repo.working_dir) / result.path
    assert report.read_text().endswith("\n")
    assert "review old-decision" in report.read_text()
    assert "add curation report 2026-05-25" in repo.head.commit.message


def test_materialize_curation_report_accepts_custom_curation_path(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    result = materialize_curation_report(
        str(repo.working_dir),
        "## Weekly Knowledge Hygiene",
        branch="jurati/curation/custom-path",
        path=".jurati/curation/manual-review.md",
        now=NOW,
    )

    assert result.path == ".jurati/curation/manual-review.md"
    assert (Path(repo.working_dir) / ".jurati/curation/manual-review.md").exists()


def test_materialize_curation_report_rejects_empty_body(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    with pytest.raises(ValueError, match="must not be empty"):
        materialize_curation_report(
            str(repo.working_dir),
            "  \n",
            branch="jurati/curation/test",
            now=NOW,
        )


def test_materialize_curation_report_rejects_path_traversal(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    with pytest.raises(ValueError, match="Path traversal rejected"):
        materialize_curation_report(
            str(repo.working_dir),
            "body",
            branch="jurati/curation/test",
            path="../weekly-hygiene.md",
            now=NOW,
        )


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("README.md", "under .jurati/curation"),
        ("decisions/old-decision.md", "under .jurati/curation"),
        (".jurati/curation/report.txt", "Markdown file"),
        (".jurati/curation/../README.md", "Invalid curation report path"),
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
            branch="jurati/curation/test",
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
            branch="jurati/curation/test",
            now=NOW,
        )


def test_materialize_curation_report_same_branch_rerun_fails_explicitly(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    materialize_curation_report(
        str(repo.working_dir),
        "first body",
        branch="jurati/curation/test",
        now=NOW,
    )

    with pytest.raises(git.exc.GitCommandError, match="already exists"):
        materialize_curation_report(
            str(repo.working_dir),
            "second body",
            branch="jurati/curation/test",
            now=NOW,
        )
