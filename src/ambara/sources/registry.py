# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Source provider registry."""

from __future__ import annotations

from collections.abc import Iterable

from ambara.sources.types import SourceProvider


class SourceProviderRegistryError(RuntimeError):
    """Raised when source provider registration would be ambiguous."""


class SourceProviderRegistry:
    def __init__(self, providers: Iterable[SourceProvider] = ()) -> None:
        self._providers: dict[str, SourceProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: SourceProvider, *, replace: bool = False) -> None:
        provider_id = normalize_source_provider_id(provider.provider_id)
        if provider_id in self._providers and not replace:
            raise SourceProviderRegistryError(
                f"source provider id {provider_id!r} is already registered"
            )
        self._providers[provider_id] = provider

    def resolve(self, provider_id: str) -> SourceProvider | None:
        return self._providers.get(normalize_source_provider_id(provider_id))

    def require(self, provider_id: str) -> SourceProvider:
        provider = self.resolve(provider_id)
        if provider is None:
            known = ", ".join(self.provider_ids()) or "none"
            raise SourceProviderRegistryError(
                f"unknown source provider {provider_id!r}; known providers: {known}"
            )
        return provider

    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))


def normalize_source_provider_id(provider_id: str) -> str:
    normalized = provider_id.strip().lower().replace("_", "-")
    if not normalized:
        raise SourceProviderRegistryError("source provider id is required")
    return normalized
