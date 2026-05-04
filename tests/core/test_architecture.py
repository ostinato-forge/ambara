from __future__ import annotations

import ast
from pathlib import Path

import pytest

_CORE_ROOT = Path(__file__).resolve().parent.parent.parent / "src" / "jurati" / "core"

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
