from __future__ import annotations

import ast
from pathlib import Path


def test_core_modules_do_not_import_git_boundary() -> None:
    core_root = Path("src/jurati/core")

    for source_path in core_root.glob("*.py"):
        tree = ast.parse(source_path.read_text(), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                continue

            assert not any(name.startswith("jurati.git") for name in imported), source_path
