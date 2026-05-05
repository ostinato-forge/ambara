"""Identity opacity for cross-system integration boundaries.

API-layer privacy boundary — raw git history still exposes identities
to anyone with repo access. The guarantee is that jurati's integration
contract does not propagate linkable identities across systems.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jurati.core.schema import RecordedBy, SourceMeta


def opaque_identity(
    recorded_by: RecordedBy | None,
    source: SourceMeta | None,
    system_id: str,
    salt: bytes,
) -> tuple[str | None, str | None]:
    """One-way hash preventing cross-system identity correlation.

    Returns (opaque_client, opaque_author).
    """
    opaque_client = _hash(recorded_by.client, system_id, salt) if recorded_by else None
    opaque_author = _hash(source.author, system_id, salt) if source else None
    return opaque_client, opaque_author


def _hash(value: str, system_id: str, salt: bytes) -> str:
    payload = f"{value}:{system_id}".encode() + salt
    return hashlib.sha256(payload).hexdigest()[:16]
