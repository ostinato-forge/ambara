# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Property and fuzz tests for untrusted source-text sanitization.

These sanitizers defend the read path against prompt injection, control-char
tricks, path traversal, and credential leakage in external source artifacts, so
their guarantees must hold for all inputs, not just curated examples.
"""

from __future__ import annotations

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ambara.core.context_rendering import (
    safe_artifact_ref,
    sanitize_source_paths,
    sanitize_untrusted_source_text,
)

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SAFE_PATH = re.compile(r"^[A-Za-z0-9._/\-]+$")
_URLISH = st.from_regex(r"https?://[\w.:@/?#%&=-]{1,60}", fullmatch=True)


@given(st.text(), st.integers(min_value=1, max_value=2000))
def test_sanitized_text_is_bounded_and_control_free(raw: str, max_chars: int) -> None:
    result = sanitize_untrusted_source_text(raw, max_chars=max_chars)
    if result is None:
        return
    assert result  # never returns an empty string, only None
    # Bounded by max_chars plus the 3-char ellipsis truncation appends.
    assert len(result) <= max_chars + 3
    # External control sequences and line breaks are stripped or flattened away.
    assert not _CONTROL.search(result)
    assert not _ANSI.search(result)
    assert "\n" not in result
    assert "\r" not in result


@given(st.lists(st.text(), max_size=50).map(tuple), st.integers(min_value=1, max_value=30))
def test_sanitized_paths_are_a_safe_subset(paths: tuple[str, ...], max_paths: int) -> None:
    result = sanitize_source_paths(paths, max_paths=max_paths)
    assert len(result) <= max_paths
    for p in result:
        assert p in paths  # only filters input, never fabricates a path
        assert _SAFE_PATH.match(p)
        assert ".." not in p
        assert not p.startswith("/")
        assert len(p) <= 200


@given(st.one_of(st.text(), _URLISH))
def test_safe_artifact_ref_strips_unsafe_parts(value: str) -> None:
    ref = safe_artifact_ref(value)
    if ref is None:
        return
    assert ref.startswith(("http://", "https://"))
    assert "?" not in ref  # query stripped
    assert "#" not in ref  # fragment stripped


@pytest.mark.parametrize(
    "hostile",
    [
        "http://[::1",  # unterminated IPv6 literal: must reject, not raise
        "https://user:pass@evil.com/x",  # embedded credentials
        "https://ok.com/x?token=secret#frag",  # query + fragment
        "javascript:alert(1)",  # non-http scheme
    ],
)
def test_safe_artifact_ref_rejects_hostile_refs_without_raising(hostile: str) -> None:
    ref = safe_artifact_ref(hostile)
    assert ref is None or (
        ref.startswith(("http://", "https://")) and "?" not in ref and "#" not in ref
    )
