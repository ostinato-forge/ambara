# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Signal provider registry for built-ins and third-party entry points."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import Any, Protocol, cast

from ambara.core.pr_signals import CoordinationSignal, PRSignal
from ambara.providers.errors import SignalProviderError
from ambara.providers.github_prs import fetch_all_signals as fetch_github_signals
from ambara.providers.gitlab_mrs import fetch_all_signals as fetch_gitlab_signals
from ambara.providers.jira_issues import fetch_all_signals as fetch_jira_signals
from ambara.sources.config import PRSignalsConfig

SIGNAL_PROVIDER_ENTRY_POINT_GROUP = "ambara.signal_providers"
SignalResult = Sequence[PRSignal | CoordinationSignal]


class SignalProviderRegistryError(SignalProviderError):
    """Raised when installed provider metadata would make resolution unsafe."""


class SignalFetcher(Protocol):
    def __call__(
        self,
        config: PRSignalsConfig,
        *,
        token: str | None = None,
    ) -> SignalResult: ...


@dataclass(frozen=True)
class RegisteredSignalProvider:
    provider_id: str
    display_name: str
    fetch: SignalFetcher
    source: str = "entry-point"


def built_in_signal_providers() -> dict[str, RegisteredSignalProvider]:
    return {
        "github": RegisteredSignalProvider(
            provider_id="github",
            display_name="GitHub",
            fetch=fetch_github_signals,
            source="built-in",
        ),
        "gitlab": RegisteredSignalProvider(
            provider_id="gitlab",
            display_name="GitLab",
            fetch=fetch_gitlab_signals,
            source="built-in",
        ),
        "jira": RegisteredSignalProvider(
            provider_id="jira",
            display_name="Jira",
            fetch=fetch_jira_signals,
            source="built-in",
        ),
    }


def discover_entry_point_signal_providers(
    eps: Sequence[EntryPoint] | None = None,
    *,
    reserved_provider_ids: Iterable[str] | None = None,
) -> dict[str, RegisteredSignalProvider]:
    discovered: dict[str, RegisteredSignalProvider] = {}
    reserved = {
        _normalize_provider_id(provider_id)
        for provider_id in (
            reserved_provider_ids
            if reserved_provider_ids is not None
            else built_in_signal_providers().keys()
        )
    }
    for ep in eps if eps is not None else _signal_provider_entry_points():
        provider = _provider_from_entry_point(ep)
        if provider.provider_id in reserved:
            raise SignalProviderRegistryError(
                f"signal provider entry point {ep.name!r} resolves to reserved "
                f"built-in id {provider.provider_id!r}; refusing to shadow it"
            )
        if provider.provider_id in discovered:
            raise SignalProviderRegistryError(
                f"signal provider id {provider.provider_id!r} is registered more than once"
            )
        discovered[provider.provider_id] = provider
    return discovered


def resolve_signal_provider(
    provider_id: str,
    *,
    eps: Sequence[EntryPoint] | None = None,
) -> RegisteredSignalProvider | None:
    normalized = _normalize_provider_id(provider_id)
    providers = built_in_signal_providers()
    providers.update(discover_entry_point_signal_providers(eps))
    return providers.get(normalized)


def _signal_provider_entry_points() -> Sequence[EntryPoint]:
    selected = entry_points(group=SIGNAL_PROVIDER_ENTRY_POINT_GROUP)
    return tuple(selected)


def _provider_from_entry_point(ep: EntryPoint) -> RegisteredSignalProvider:
    loaded = ep.load()
    provider_id = _normalize_provider_id(str(getattr(loaded, "provider_id", ep.name)))
    display_name = str(getattr(loaded, "display_name", provider_id))
    return RegisteredSignalProvider(
        provider_id=provider_id,
        display_name=display_name,
        fetch=_provider_fetcher(loaded),
    )


def _provider_fetcher(loaded: Any) -> SignalFetcher:
    fetch_signals = getattr(loaded, "fetch_signals", None)
    target = fetch_signals if callable(fetch_signals) else loaded
    if not callable(target):
        raise TypeError("Signal provider entry point must be callable or expose fetch_signals()")

    def fetch(config: PRSignalsConfig, token: str | None = None) -> SignalResult:
        return cast(SignalResult, target(config, token=token))

    return fetch


def _normalize_provider_id(provider_id: str) -> str:
    return provider_id.strip().lower().replace("_", "-")
