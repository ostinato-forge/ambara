# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Source authentication references and broker contract.

Source config stores references to auth material, never raw tokens. Runtime
brokers resolve those references into provider-specific auth material without
changing the frozen source-artifact contract.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ambara.core.secrets import scan_secrets
from ambara.sources.types import AuthMode, SourceInstanceConfig, SourceProvider


class SourceAuthRefKind(StrEnum):
    ENV = "env"
    KEYRING = "keyring"
    MANAGED = "managed"


@dataclass(frozen=True)
class SourceAuthRef:
    kind: SourceAuthRefKind
    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("source auth reference name is required")
        lowered = self.name.lower()
        if any(marker in lowered for marker in ("token=", "password=", "secret=")):
            raise ValueError("source auth references must not contain raw credentials")
        if scan_secrets(self.name):
            raise ValueError("source auth references must not contain raw credentials")


class SourceAuthBroker(Protocol):
    """Resolve source auth references to provider auth material.

    Brokers are trusted runtime integrations. Source providers receive only the
    resolved value on ``SourceFetchRequest.auth``; source config and artifacts
    keep stable references and never persist raw credentials.
    """

    def resolve(
        self,
        ref: SourceAuthRef,
        *,
        config: SourceInstanceConfig,
        provider: SourceProvider,
    ) -> object | None: ...


@dataclass(frozen=True)
class EnvSourceAuthBroker:
    """Resolve env-backed source auth references for local/dev deployments."""

    environ: Mapping[str, str] | None = None

    def resolve(
        self,
        ref: SourceAuthRef,
        *,
        config: SourceInstanceConfig,
        provider: SourceProvider,
    ) -> object | None:
        if ref.kind is not SourceAuthRefKind.ENV:
            return None
        environ = os.environ if self.environ is None else self.environ
        value = environ.get(ref.name)
        return value if value else None


def resolve_source_auth(
    config: SourceInstanceConfig,
    *,
    provider: SourceProvider,
    broker: SourceAuthBroker | None,
    explicit_auth: object | None = None,
) -> object | None:
    """Return auth material for one source instance.

    ``explicit_auth`` preserves the existing CLI/server override path. Without
    an override, the configured ``auth_ref`` selector is resolved first. If no
    explicit selector exists, local env defaults are tried for providers that
    declare ``env_token`` support.
    """

    if explicit_auth is not None:
        return explicit_auth
    if broker is None:
        return None

    refs = _configured_auth_refs(config)
    if not refs and AuthMode.ENV_TOKEN in provider.capabilities.auth_modes:
        refs = default_env_auth_refs(provider.provider_id)

    for ref in refs:
        value = broker.resolve(ref, config=config, provider=provider)
        if value is not None:
            return value
    return None


def default_env_auth_refs(provider_id: str) -> tuple[SourceAuthRef, ...]:
    provider = provider_id.strip().lower()
    names = {
        "github": ("AMBARA_SOURCE_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"),
        "gitlab": ("AMBARA_SOURCE_TOKEN", "GL_TOKEN", "GITLAB_TOKEN"),
        "jira": ("AMBARA_SOURCE_TOKEN", "JIRA_API_TOKEN"),
    }.get(provider, ("AMBARA_SOURCE_TOKEN",))
    return tuple(SourceAuthRef(SourceAuthRefKind.ENV, name) for name in names)


def source_auth_ref_from_value(value: object) -> SourceAuthRef | None:
    if value is None:
        return None
    if isinstance(value, SourceAuthRef):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if ":" in raw:
            raw_kind, raw_name = raw.split(":", 1)
            return SourceAuthRef(SourceAuthRefKind(raw_kind.strip()), raw_name.strip())
        return SourceAuthRef(SourceAuthRefKind.ENV, raw)
    if isinstance(value, Mapping):
        raw_kind_value = value.get("kind", SourceAuthRefKind.ENV.value)
        raw_name_value = value.get("name")
        if not isinstance(raw_kind_value, str) or not isinstance(raw_name_value, str):
            raise ValueError("source auth_ref mapping requires string kind and name")
        raw_kind = raw_kind_value
        raw_name = raw_name_value
        return SourceAuthRef(SourceAuthRefKind(raw_kind), raw_name)
    raise ValueError("source auth_ref must be a SourceAuthRef, string, mapping, or null")


def _configured_auth_refs(config: SourceInstanceConfig) -> tuple[SourceAuthRef, ...]:
    raw = config.selectors.get("auth_ref")
    ref = source_auth_ref_from_value(raw)
    return (ref,) if ref is not None else ()
