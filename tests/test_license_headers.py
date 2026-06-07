# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

from __future__ import annotations

from pathlib import Path

EXPECTED_HEADER = (
    "# SPDX-License-Identifier: Apache-2.0",
    "# Copyright 2026 Ed Parenti",
)


def test_python_files_have_spdx_headers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    missing: list[str] = []

    for root_name in ("src", "tests"):
        for path in sorted((repo_root / root_name).rglob("*.py")):
            lines = path.read_text(encoding="utf-8").splitlines()
            if tuple(lines[:2]) != EXPECTED_HEADER:
                missing.append(path.relative_to(repo_root).as_posix())

    assert not missing, "Missing Apache-2.0 SPDX header: " + ", ".join(missing)
