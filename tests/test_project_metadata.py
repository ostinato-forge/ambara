from __future__ import annotations

import tomllib
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent


def test_readme_development_status_badge_tracks_pyproject_classifier() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    classifiers = pyproject["project"]["classifiers"]
    status = next(
        classifier.removeprefix("Development Status :: ")
        for classifier in classifiers
        if classifier.startswith("Development Status :: ")
    )
    badge_message = status.replace(" - ", " -- ")
    badge = (
        f"https://img.shields.io/badge/Development%20Status-"
        f"{quote(badge_message, safe='')}-brightgreen"
    )

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"Development Status: {status}" in readme
    assert badge in readme
