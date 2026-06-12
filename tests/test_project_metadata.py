# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent


def _project_version() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(pyproject["project"]["version"])


def test_readme_development_status_badge_tracks_pyproject_classifier() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    classifiers = pyproject["project"]["classifiers"]
    status = next(
        classifier.removeprefix("Development Status :: ")
        for classifier in classifiers
        if classifier.startswith("Development Status :: ")
    )
    badge_message = status.replace(" - ", " -- ")
    color = "yellow" if "Beta" in status else "brightgreen"
    badge = (
        f"https://img.shields.io/badge/Development%20Status-{quote(badge_message, safe='')}-{color}"
    )

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"Development Status: {status}" in readme
    assert badge in readme


def test_package_version_matches_runtime_version() -> None:
    runtime = (ROOT / "src" / "ambara" / "__init__.py").read_text(encoding="utf-8")

    assert f'__version__ = "{_project_version()}"' in runtime


def test_current_release_docs_match_package_version() -> None:
    version = _project_version()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    release_notes_path = ROOT / "docs" / f"release-v{version}.md"
    release_notes = release_notes_path.read_text(encoding="utf-8")

    assert f"## [{version}] — " in changelog
    assert f"## [{version}] — Unreleased" not in changelog
    assert (
        f"[{version}]: https://github.com/ostinato-forge/ambara/releases/tag/v{version}"
        in changelog
    )
    assert f"# Ambara v{version} Release Notes" in release_notes
    assert "release candidate" not in release_notes.lower()


def test_release_proof_tracks_current_version_and_installed_user_path() -> None:
    version = _project_version()
    proof = (ROOT / "docs" / "release-proof.md").read_text(encoding="utf-8")

    assert f"ambara-{version}-py3-none-any.whl" in proof
    assert f"Do not push `v{version}`" not in proof
    assert "scripts/installed-user-path-smoke.sh" in proof
    assert "scripts/docker-install-smoke.sh" in proof
    assert "## Source Preview Proof" in proof
    assert "tests/sources/test_source_conformance.py" in proof
    assert "tests/test_cli_sources.py tests/test_server_health.py" in proof
    assert "tests/test_server_coordination.py tests/test_server_curation.py" in proof
    assert "Claude Code/Codex/Cursor/Gemini file-adapter smokes" in proof
    assert "must not publicly claim live Linear/Confluence API ingestion" in proof


def test_source_provider_docs_publish_support_matrix() -> None:
    docs = (ROOT / "docs" / "source-providers.md").read_text(encoding="utf-8")

    assert "## Source Support Matrix" in docs
    assert "First-class Source Preview" in docs
    assert "Preview contract" in docs
    assert "Fixture-backed Public Preview" in docs
    assert "Deferred" in docs


def test_installed_user_path_smoke_script_is_executable() -> None:
    script = ROOT / "scripts" / "installed-user-path-smoke.sh"

    assert script.exists()
    assert os.access(script, os.X_OK)


def test_docker_install_smoke_script_is_executable() -> None:
    script = ROOT / "scripts" / "docker-install-smoke.sh"

    assert script.exists()
    assert os.access(script, os.X_OK)


def test_installed_user_path_smoke_covers_unavailable_source_privacy() -> None:
    script = (ROOT / "scripts" / "installed-user-path-smoke.sh").read_text(encoding="utf-8")

    assert "sources-doctor-unavailable.json" in script
    assert "source-smoke-unavailable.json" in script
    assert '"status": "unavailable"' in script
    assert '"message": "source refresh failed"' in script
    assert "private-source-details" in script
    assert "No such file or directory" in script
