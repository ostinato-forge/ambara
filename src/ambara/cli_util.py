# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Generic leaf utilities shared across the Ambara CLI modules.

Pure helpers with no dependency on the CLI command surface, so command-family
modules can import them without cycling back through ``cli.py``.
"""

from __future__ import annotations

from pathlib import Path

import frontmatter


def _load_yaml_mapping(path: Path) -> dict[str, object]:
    try:
        loaded: object = frontmatter.default_handlers.YAMLHandler().load(path.read_text())
    except OSError as exc:
        raise ValueError(str(exc)) from exc
    except Exception as exc:
        raise ValueError(f"invalid YAML: {exc}") from exc

    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("top-level YAML must be a mapping")
    return {key: value for key, value in loaded.items() if isinstance(key, str)}


def _dump_yaml_mapping(data: dict[str, object]) -> str:
    rendered: str = frontmatter.default_handlers.YAMLHandler().export(data, sort_keys=False)
    return rendered + "\n"


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
