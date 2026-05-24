"""Tests for core/privacy.py — identity opacity at integration boundary."""

from __future__ import annotations

import pytest

from jurati.core.privacy import (
    PRIVACY_SALT_ENV,
    generate_privacy_salt,
    load_privacy_salt,
    opaque_identity,
    opaque_identity_from_env,
)
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


class TestPrivacySalt:
    def test_loads_plaintext_env_salt(self) -> None:
        assert load_privacy_salt({PRIVACY_SALT_ENV: "local-dev-salt"}) == b"local-dev-salt"

    def test_loads_generated_salt(self) -> None:
        encoded = generate_privacy_salt(num_bytes=16)
        assert encoded.startswith("base64:")
        assert len(load_privacy_salt({PRIVACY_SALT_ENV: encoded})) == 16

    def test_requires_salt(self) -> None:
        with pytest.raises(ValueError, match=PRIVACY_SALT_ENV):
            load_privacy_salt({})

    def test_hashes_identity_from_env_salt(self) -> None:
        rb = RecordedBy(client="claude-code")
        direct, _ = opaque_identity(rb, None, "system-a", b"local-dev-salt")
        from_env, _ = opaque_identity_from_env(
            rb,
            None,
            "system-a",
            {PRIVACY_SALT_ENV: "local-dev-salt"},
        )
        assert from_env == direct
