# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Outside-in CLI smoke for `ambara sources promote` (dev/proof mirror surface)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from ambara.cli import main
from ambara.git.remember import RememberOutcome

NOW = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
ARTIFACT_ID = "github:org/api:pull:7"


def _write_github_fixture(path: Path, **overrides: object) -> None:
    signal: dict[str, object] = {
        "repo": "org/api",
        "number": 7,
        "url": "https://github.com/org/api/pull/7",
        "title": "Adopt gRPC for service calls",
        "body_excerpt": "The team agreed to standardize service-to-service calls on gRPC.",
        "author": "tony",
        "state": "open",
        "labels": ["ambara"],
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "changed_paths": ["src/api/grpc.py"],
    }
    signal.update(overrides)
    path.write_text(json.dumps({"signals": [signal]}) + "\n")


def _promote(*args: str) -> object:
    return CliRunner().invoke(main, ["sources", "promote", *args], prog_name="ambara")


def test_promote_dry_run_prints_receipt_and_writes_nothing(tmp_path: Path) -> None:
    fixture = tmp_path / "signals.json"
    _write_github_fixture(fixture)

    with patch("ambara.cli.sources.materialize_remember") as m_materialize:
        result = _promote(
            ARTIFACT_ID,
            "--provider",
            "fixture",
            "--fixture",
            str(fixture),
            "--repo",
            "org/api",
            "--json",
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "dry_run"
    assert payload["artifact_id"] == ARTIFACT_ID
    assert payload["branch"] == f"ambara/promote/{payload['entry_id']}"
    assert payload["receipt"]["action"] == "create"
    m_materialize.assert_not_called()


def test_promote_human_output_names_the_branch(tmp_path: Path) -> None:
    fixture = tmp_path / "signals.json"
    _write_github_fixture(fixture)

    result = _promote(
        ARTIFACT_ID, "--provider", "fixture", "--fixture", str(fixture), "--repo", "org/api"
    )

    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output.lower()
    assert "ambara/promote/" in result.output


def test_promote_unknown_artifact_errors(tmp_path: Path) -> None:
    fixture = tmp_path / "signals.json"
    _write_github_fixture(fixture)

    result = _promote(
        "github:org/api:pull:999",
        "--provider",
        "fixture",
        "--fixture",
        str(fixture),
        "--repo",
        "org/api",
    )

    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_promote_apply_requires_repo_path(tmp_path: Path) -> None:
    fixture = tmp_path / "signals.json"
    _write_github_fixture(fixture)

    result = _promote(
        ARTIFACT_ID,
        "--provider",
        "fixture",
        "--fixture",
        str(fixture),
        "--repo",
        "org/api",
        "--apply",
    )

    assert result.exit_code != 0
    assert "repo-path" in result.output.lower()


def test_promote_apply_opens_review_branch(tmp_path: Path) -> None:
    fixture = tmp_path / "signals.json"
    _write_github_fixture(fixture)
    repo = tmp_path / "kb"
    repo.mkdir()
    outcome = RememberOutcome(
        entry_id="github-github-org-api-pull-7",
        branch="ambara/promote/github-github-org-api-pull-7",
        sha="cafef00d",
        reused_existing=False,
        receipt={"action": "create", "branch": "ambara/promote/github-github-org-api-pull-7"},
    )

    with (
        patch("ambara.cli.sources.materialize_remember", return_value=outcome) as m_materialize,
        patch("ambara.cli.sources._load_promote_index", return_value=[]),
    ):
        result = _promote(
            ARTIFACT_ID,
            "--provider",
            "fixture",
            "--fixture",
            str(fixture),
            "--repo",
            "org/api",
            "--apply",
            "--repo-path",
            str(repo),
            "--main-branch",
            "main",
            "--json",
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["branch"] == outcome.branch
    m_materialize.assert_called_once()
    args, kwargs = m_materialize.call_args
    assert args[0] == str(repo)
    assert kwargs["main_branch"] == "main"
