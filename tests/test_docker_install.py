# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_defines_local_preview_cli_image() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert text.startswith("# syntax=docker/dockerfile:1")
    assert "FROM python:3.12-slim AS runtime" in text
    assert "apt-get install -y --no-install-recommends" in text
    for package in ("bash", "ca-certificates", "git"):
        assert package in text
    assert "COPY pyproject.toml README.md LICENSE ./" in text
    assert "COPY src ./src" in text
    assert "python -m pip install ." in text
    assert "python -m pip check" in text
    assert "USER ambara" in text
    assert "WORKDIR /workspace" in text
    assert 'ENTRYPOINT ["ambara"]' in text
    assert 'CMD ["--help"]' in text

    lowered = text.lower()
    for deferred_surface in ("compose", "kubernetes", "kubectl", "swarm", "fleet"):
        assert deferred_surface not in lowered


def test_dockerignore_excludes_local_churn_without_hiding_package_inputs() -> None:
    ignored = set((ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())

    assert {".git", ".venv", "dist", "build", "planning"} <= ignored
    assert "src" not in ignored
    assert "pyproject.toml" not in ignored
    assert "README.md" not in ignored
    assert "LICENSE" not in ignored


def test_docker_install_smoke_script_is_preview_scoped_and_executable() -> None:
    script = ROOT / "scripts" / "docker-install-smoke.sh"
    text = script.read_text(encoding="utf-8")

    assert os.access(script, os.X_OK)
    assert "AMBARA_CONTAINER_ENGINE" in text
    assert "docker" in text
    assert "podman" in text
    assert "AMBARA_DOCKER_SMOKE_ROOT must be under /tmp" in text
    assert '"$ENGINE" build -t "$IMAGE"' in text
    assert '"$ENGINE" run --rm "$IMAGE" --version' in text
    assert "demo --path /workspace/demo --force" in text
    assert "/workspace/demo/run-proof.sh" in text
    assert "--provider linear" in text
    assert "--provider confluence" in text
    assert "source-smoke" in text

    lowered = text.lower()
    for deferred_surface in ("docker compose", "kubernetes", "kubectl", "swarm", "fleet"):
        assert deferred_surface not in lowered
