from __future__ import annotations

import ast
from pathlib import Path

import pytest

_CORE_ROOT = Path(__file__).resolve().parent.parent.parent / "src" / "jurati" / "core"
_JURATI_ROOT = Path(__file__).resolve().parent.parent.parent / "src" / "jurati"

_FORBIDDEN_BOUNDARIES = ["git", "providers"]


def _assert_no_boundary_imports(source_path: Path, boundary: str) -> None:
    tree = ast.parse(source_path.read_text(), filename=str(source_path))
    abs_prefix = f"jurati.{boundary}"
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
    server_path = _JURATI_ROOT / "server.py"
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
        assert (_JURATI_ROOT / module).exists()


def test_server_facade_reexports_extracted_helper_names() -> None:
    import jurati.server as server

    names = [
        "ServerState",
        "SyncHealth",
        "_entry_counts",
        "_write_request_examples",
        "_format_entry",
        "_links_for_entry",
        "_build_context_payload",
        "_build_search_results",
        "_parse_tag_filter",
        "_format_result",
        "_explain_payload",
        "_format_hygiene_item",
        "_format_hygiene_report",
        "_format_guidance",
        "_privacy_boundary",
        "_format_revalidation_item",
        "_format_curation_advisory",
        "_curation_privacy_boundary",
        "_write_receipt",
        "_expire_receipt",
        "_format_conflict_entry",
        "_format_write_advisories",
        "_write_advisories_for_intent",
    ]

    for name in names:
        assert hasattr(server, name)
