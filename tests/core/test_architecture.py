from __future__ import annotations

import ast
from pathlib import Path


def test_core_modules_do_not_import_git_boundary() -> None:
    core_root = Path(__file__).resolve().parent.parent.parent / "src" / "jurati" / "core"

    for source_path in core_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("jurati.git"), (
                        f"{source_path}: absolute import {alias.name!r} crosses git boundary"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level > 0 and module.split(".")[0] == "git":
                    raise AssertionError(f"{source_path}: relative import crosses git boundary")
                if node.level > 0 and module == "":
                    for alias in node.names:
                        if alias.name.split(".")[0] == "git":
                            raise AssertionError(
                                f"{source_path}: relative import "
                                f"{alias.name!r} crosses git boundary"
                            )
                if node.level == 0 and module.startswith("jurati.git"):
                    raise AssertionError(
                        f"{source_path}: absolute import {module!r} crosses git boundary"
                    )
