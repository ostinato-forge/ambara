"""Tests for core/privacy.py — identity opacity at integration boundary."""

from __future__ import annotations

from jurati.core.privacy import opaque_identity
from jurati.core.schema import RecordedBy, SourceMeta

_SALT = b"test-salt-value"


class TestOpaqueIdentity:
    def test_returns_none_when_no_identity(self) -> None:
        client, author = opaque_identity(None, None, "system-a", _SALT)
        assert client is None
        assert author is None

    def test_hashes_recorded_by_client(self) -> None:
        rb = RecordedBy(client="claude-code")
        client, author = opaque_identity(rb, None, "system-a", _SALT)
        assert client is not None
        assert client != "claude-code"
        assert len(client) == 16
        assert author is None

    def test_hashes_source_author(self) -> None:
        source = SourceMeta(repo="api", commit="abc", author="alice@co.com")
        client, author = opaque_identity(None, source, "system-a", _SALT)
        assert client is None
        assert author is not None
        assert author != "alice@co.com"
        assert len(author) == 16

    def test_both_present(self) -> None:
        rb = RecordedBy(client="cursor")
        source = SourceMeta(repo="api", commit="abc", author="bob@co.com")
        client, author = opaque_identity(rb, source, "system-a", _SALT)
        assert client is not None
        assert author is not None

    def test_different_system_ids_produce_different_hashes(self) -> None:
        rb = RecordedBy(client="claude-code")
        c1, _ = opaque_identity(rb, None, "system-a", _SALT)
        c2, _ = opaque_identity(rb, None, "system-b", _SALT)
        assert c1 != c2

    def test_same_inputs_produce_same_hash(self) -> None:
        rb = RecordedBy(client="claude-code")
        c1, _ = opaque_identity(rb, None, "system-a", _SALT)
        c2, _ = opaque_identity(rb, None, "system-a", _SALT)
        assert c1 == c2

    def test_different_salts_produce_different_hashes(self) -> None:
        rb = RecordedBy(client="claude-code")
        c1, _ = opaque_identity(rb, None, "system-a", b"salt-1")
        c2, _ = opaque_identity(rb, None, "system-a", b"salt-2")
        assert c1 != c2
