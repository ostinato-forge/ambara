# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Source kernel types and helpers.

The source kernel is the v1-track replacement for PR-shaped signal providers.
Legacy providers keep working while source artifacts, central safety, and
per-source policy stabilize.
"""

from ambara.sources.adapters import (
    coordination_signal_from_source_artifact,
    legacy_signal_from_source_artifact,
    source_artifact_from_coordination_signal,
    source_artifact_from_legacy_signal,
    source_artifact_from_pr_signal,
)
from ambara.sources.auth import (
    EnvSourceAuthBroker,
    SourceAuthBroker,
    SourceAuthRef,
    SourceAuthRefKind,
    default_env_auth_refs,
    resolve_source_auth,
    source_auth_ref_from_value,
)
from ambara.sources.cache import SourceCache, SourceCacheLookup, SourceCacheRecord
from ambara.sources.config import (
    PRSignalsConfig,
    SourceInputsConfig,
    SourcesConfig,
    sources_from_legacy_pr_signals,
    sources_from_source_inputs_config,
)
from ambara.sources.health import SourceHealth, SourceHealthStatus
from ambara.sources.manager import SourceManager, SourceManagerResult
from ambara.sources.registry import SourceProviderRegistry, SourceProviderRegistryError
from ambara.sources.safety import enforce_source_budget, sanitize_source_artifact
from ambara.sources.types import (
    AuthMode,
    BodyPolicy,
    IdentityPolicy,
    Sensitivity,
    SourceArtifact,
    SourceBudget,
    SourceCapabilities,
    SourceCategory,
    SourceFetchRequest,
    SourceFetchResult,
    SourceInstanceConfig,
    SourceOmissions,
    SourceProvenance,
    SourceProvider,
    TextTrust,
)

__all__ = [
    "AuthMode",
    "EnvSourceAuthBroker",
    "BodyPolicy",
    "IdentityPolicy",
    "LegacySignalSourceProvider",
    "PRSignalsConfig",
    "Sensitivity",
    "SourceArtifact",
    "SourceAuthBroker",
    "SourceAuthRef",
    "SourceAuthRefKind",
    "SourceBudget",
    "SourceCache",
    "SourceCacheLookup",
    "SourceCacheRecord",
    "SourceCapabilities",
    "SourceCategory",
    "SourceFetchRequest",
    "SourceFetchResult",
    "SourceInstanceConfig",
    "SourceInputsConfig",
    "SourceManager",
    "SourceManagerResult",
    "SourceOmissions",
    "SourceProvider",
    "SourceProviderRegistry",
    "SourceProviderRegistryError",
    "SourceProvenance",
    "SourcesConfig",
    "SourceHealth",
    "SourceHealthStatus",
    "TextTrust",
    "built_in_legacy_source_providers",
    "coordination_signal_from_source_artifact",
    "default_env_auth_refs",
    "enforce_source_budget",
    "legacy_signal_from_source_artifact",
    "pr_signals_config_from_source_instance",
    "resolve_source_auth",
    "sanitize_source_artifact",
    "source_auth_ref_from_value",
    "source_artifact_from_coordination_signal",
    "source_artifact_from_legacy_signal",
    "source_artifact_from_pr_signal",
    "sources_from_legacy_pr_signals",
    "sources_from_source_inputs_config",
]


def __getattr__(name: str) -> object:
    if name in {
        "LegacySignalSourceProvider",
        "built_in_legacy_source_providers",
        "pr_signals_config_from_source_instance",
    }:
        from ambara.sources import legacy_providers

        return getattr(legacy_providers, name)
    raise AttributeError(f"module 'ambara.sources' has no attribute {name!r}")
