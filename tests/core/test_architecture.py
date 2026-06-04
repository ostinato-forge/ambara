# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_CORE_ROOT = Path(__file__).resolve().parent.parent.parent / "src" / "ambara" / "core"
_AMBARA_ROOT = Path(__file__).resolve().parent.parent.parent / "src" / "ambara"

_FORBIDDEN_BOUNDARIES = ["git", "providers"]


def _assert_no_boundary_imports(source_path: Path, boundary: str) -> None:
    tree = ast.parse(source_path.read_text(), filename=str(source_path))
    abs_prefix = f"ambara.{boundary}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(abs_prefix), (
                    f"{source_path}: absolute import {alias.name!r} crosses {boundary} boundary"
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level > 0 and module.split(".")[0] == boundary:
                raise AssertionError(f"{source_path}: relative import crosses {boundary} boundary")
            if node.level > 0 and module == "":
                for alias in node.names:
                    if alias.name.split(".")[0] == boundary:
                        raise AssertionError(
                            f"{source_path}: relative import "
                            f"{alias.name!r} crosses {boundary} boundary"
                        )
            if node.level == 0 and module.startswith(abs_prefix):
                raise AssertionError(
                    f"{source_path}: absolute import {module!r} crosses {boundary} boundary"
                )


@pytest.mark.parametrize("boundary", _FORBIDDEN_BOUNDARIES)
def test_core_modules_do_not_cross_boundary(boundary: str) -> None:
    for source_path in _CORE_ROOT.rglob("*.py"):
        _assert_no_boundary_imports(source_path, boundary)


def test_server_facade_keeps_extracted_helper_modules() -> None:
    server_path = _AMBARA_ROOT / "server.py"
    server_source = server_path.read_text()

    assert len(server_source.splitlines()) < 1300
    assert "class ServerState" not in server_source
    assert "def _format_entry" not in server_source
    assert "def _write_receipt" not in server_source
    assert "def _format_guidance" not in server_source
    for module in (
        "server_state.py",
        "server_read.py",
        "server_write.py",
        "server_guidance.py",
        "server_coordination.py",
        "server_curation.py",
    ):
        assert (_AMBARA_ROOT / module).exists()


def test_server_facade_reexports_extracted_helper_names() -> None:
    import ambara.server as server

    names = [
        "ServerState",
        "SyncHealth",
        "build_context_payload",
        "_build_search_results",
        "_format_entry",
        "_format_entry_manifest",
        "_format_result",
        "_explain_payload",
        "_format_hygiene_report",
        "_state_status_payload",
        "_health_dict",
        "_write_receipt",
        "_expire_receipt",
        "_write_path_error",
        "_propose_correction",
        "_record_correction",
        "_write_advisories_for_intent",
        "build_coordination_payload",
        "build_curation_payload",
    ]

    for name in names:
        assert hasattr(server, name)


def test_cli_facade_keeps_client_smoke_extracted() -> None:
    cli_path = _AMBARA_ROOT / "cli.py"
    cli_source = cli_path.read_text()
    client_smoke_source = (_AMBARA_ROOT / "cli_client_smoke.py").read_text()

    assert len(cli_source.splitlines()) < 4450
    assert "@main.command(\"client-smoke\")" not in cli_source
    assert "register_client_smoke_command(" in cli_source
    assert "@main.command(\"client-smoke\")" in client_smoke_source
