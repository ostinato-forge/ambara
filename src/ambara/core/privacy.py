# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Identity opacity for cross-system integration boundaries.

API-layer privacy boundary — raw git history still exposes identities
to anyone with repo access. The guarantee is that ambara's integration
contract does not propagate linkable identities across systems.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ambara.core.schema import RecordedBy, SourceMeta

PRIVACY_SALT_ENV = "AMBARA_PRIVACY_SALT"
_BASE64_PREFIX = "base64:"


def generate_privacy_salt(num_bytes: int = 32) -> str:
    """Return an env-var-safe salt value for privacy-preserving identity hashes."""

    token = base64.urlsafe_b64encode(secrets.token_bytes(num_bytes)).decode("ascii")
    return f"{_BASE64_PREFIX}{token}"


def load_privacy_salt(env: Mapping[str, str]) -> bytes:
    """Load the salt used by opaque_identity from environment-style config."""

    raw = env.get(PRIVACY_SALT_ENV)
    if not raw:
        raise ValueError(f"{PRIVACY_SALT_ENV} is required for opaque identity hashing")
    if raw.startswith(_BASE64_PREFIX):
        return base64.urlsafe_b64decode(raw[len(_BASE64_PREFIX) :].encode("ascii"))
    return raw.encode("utf-8")


def opaque_identity_from_env(
    recorded_by: RecordedBy | None,
    source: SourceMeta | None,
    system_id: str,
    env: Mapping[str, str],
) -> tuple[str | None, str | None]:
    """Hash identities using the configured environment salt."""

    return opaque_identity(recorded_by, source, system_id, load_privacy_salt(env))


def opaque_identity(
    recorded_by: RecordedBy | None,
    source: SourceMeta | None,
    system_id: str,
    salt: bytes,
) -> tuple[str | None, str | None]:
    """One-way hash preventing cross-system identity correlation.

    Returns (opaque_client, opaque_author).
    """
    opaque_client = (
        _hash(recorded_by.client, system_id, salt) if recorded_by and recorded_by.client else None
    )
    opaque_author = _hash(source.author, system_id, salt) if source and source.author else None
    return opaque_client, opaque_author


def _hash(value: str, system_id: str, salt: bytes) -> str:
    payload = f"{value}:{system_id}".encode() + salt
    return hashlib.sha256(payload).hexdigest()[:16]
