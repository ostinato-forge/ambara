# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

from __future__ import annotations

from pathlib import Path

from ambara.core.changes import render_entry
from ambara.core.schema import Sensitivity
from ambara.static_html import generate_static_html
from tests.core.conftest import make_entry


def _write_entry(root: Path, entry) -> None:
    path = root / entry.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_entry(entry.frontmatter, entry.body))


def test_generate_static_html_renders_links_backlinks_and_escaping(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    source = make_entry(
        entry_id="source-entry",
        body="See [[target-entry|the target]], <script>alert(1)</script>, and [[missing-entry]].",
    )
    target = make_entry(entry_id="target-entry", body="Target body.")
    restricted = make_entry(
        entry_id="restricted-entry",
        body="Restricted body.",
        sensitivity=Sensitivity.RESTRICTED,
    )
    for entry in [source, target, restricted]:
        _write_entry(root, entry)

    result = generate_static_html(root)

    assert result.skipped_restricted == 1
    assert (root / "_site" / "index.html") in result.pages
    index_html = (root / "_site" / "index.html").read_text()
    source_html = (root / "_site" / "entries" / "source-entry.html").read_text()
    target_html = (root / "_site" / "entries" / "target-entry.html").read_text()

    assert "restricted-entry" not in index_html
    assert '<a href="target-entry.html">the target</a>' in source_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in source_html
    assert '<span class="broken">[[missing-entry]]</span>' in source_html
    assert '<a href="source-entry.html">source-entry</a>' in target_html


def test_generate_static_html_hides_restricted_link_targets(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    source = make_entry(
        entry_id="source-entry",
        body="See [[restricted-entry|restricted details]] before publishing.",
    )
    restricted = make_entry(
        entry_id="restricted-entry",
        body="Restricted body.",
        sensitivity=Sensitivity.RESTRICTED,
    )
    for entry in [source, restricted]:
        _write_entry(root, entry)

    generate_static_html(root)

    source_html = (root / "_site" / "entries" / "source-entry.html").read_text()

    assert "restricted-entry" not in source_html
    assert "restricted details" not in source_html
    assert "restricted link omitted" in source_html


def test_generate_static_html_is_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    _write_entry(root, make_entry(entry_id="alpha-entry", title="Alpha"))
    _write_entry(root, make_entry(entry_id="beta-entry", title="Beta"))

    first = generate_static_html(root)
    first_contents = {
        path.relative_to(first.output_dir).as_posix(): path.read_text() for path in first.pages
    }
    second = generate_static_html(root)
    second_contents = {
        path.relative_to(second.output_dir).as_posix(): path.read_text() for path in second.pages
    }

    assert second_contents == first_contents


def test_generate_static_html_refuses_unmarked_existing_output(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    output = tmp_path / "site"
    output.mkdir()
    (output / "keep.txt").write_text("do not delete")
    _write_entry(root, make_entry(entry_id="alpha-entry", title="Alpha"))

    try:
        generate_static_html(root, output_dir=output)
    except ValueError as exc:
        assert "not marked as generated" in str(exc)
    else:
        raise AssertionError("expected output safety check to fail")

    assert (output / "keep.txt").exists()
