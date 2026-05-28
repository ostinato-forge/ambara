from __future__ import annotations

import json
import tarfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import git
import pytest

from jurati.git.import_context import materialize_context_import
from jurati.import_context import plan_context_import

NOW = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)


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


def _write_bundle(tmp_path: Path, manifest: dict[str, object], files: dict[str, str]) -> Path:
    bundle = tmp_path / "context-pack.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        _add_text(tar, "manifest.json", json.dumps(manifest))
        for path, content in files.items():
            _add_text(tar, path, content)
    return bundle


def _add_text(tar: tarfile.TarFile, path: str, content: str) -> None:
    data = content.encode("utf-8")
    info = tarfile.TarInfo(path)
    info.size = len(data)
    tar.addfile(info, BytesIO(data))


def _valid_plan(tmp_path: Path, repo: git.Repo):
    bundle = _write_bundle(
        tmp_path,
        {
            "name": "Team Pack",
            "items": [
                {
                    "path": "Repos/api.md",
                    "category": "repo profile",
                    "id": "api-service",
                    "title": "API Service",
                }
            ],
        },
        {"Repos/api.md": "API context."},
    )
    return plan_context_import(bundle, knowledge_repo=Path(repo.working_dir), now=NOW)


def test_materialize_context_import_writes_review_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    plan = _valid_plan(tmp_path, repo)

    result = materialize_context_import(
        str(repo.working_dir),
        plan,
        branch="jurati/import-context-test",
    )

    assert len(result.commit) == 40
    assert result.branch == "jurati/import-context-test"
    assert result.created_paths == ("projects/api-service.md",)
    assert repo.active_branch.name == "jurati/import-context-test"
    assert (Path(repo.working_dir) / "projects" / "api-service.md").exists()
    assert "import context pack Team Pack" in repo.head.commit.message


def test_materialize_context_import_rejects_invalid_plan(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    bundle = _write_bundle(
        tmp_path,
        {
            "name": "Team Pack",
            "items": [
                {
                    "path": "Notes/unknown.md",
                    "category": "unknown",
                    "id": "unknown-entry",
                    "title": "Unknown",
                }
            ],
        },
        {"Notes/unknown.md": "Body."},
    )
    plan = plan_context_import(bundle, knowledge_repo=Path(repo.working_dir), now=NOW)

    with pytest.raises(ValueError, match="invalid context import plan"):
        materialize_context_import(
            str(repo.working_dir),
            plan,
            branch="jurati/import-context-test",
        )


def test_materialize_context_import_requires_clean_repo(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    plan = _valid_plan(tmp_path, repo)
    (Path(repo.working_dir) / "scratch.txt").write_text("dirty")

    with pytest.raises(ValueError, match="working tree must be clean"):
        materialize_context_import(
            str(repo.working_dir),
            plan,
            branch="jurati/import-context-test",
        )
