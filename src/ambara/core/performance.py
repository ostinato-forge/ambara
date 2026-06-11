# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Performance baseline helpers for deterministic local gates."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ambara.core.context_accounting import estimate_tokens

PERFORMANCE_BASELINE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PerformanceFailure:
    metric: str
    observed: float
    maximum: float
    unit: str

    def render(self) -> str:
        observed = _format_number(self.observed)
        maximum = _format_number(self.maximum)
        suffix = f" {self.unit}" if self.unit else ""
        return f"{self.metric}: observed {observed}{suffix} > max {maximum}{suffix}"


def payload_byte_size(value: Any) -> int:
    """Return the stable JSON byte size for a payload."""

    encoded = json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    return len(encoded.encode("utf-8"))


def startup_packet_metrics(
    packet: Mapping[str, Any],
    *,
    latency_samples_ns: Sequence[int] = (),
) -> dict[str, int | float]:
    """Return stable startup-packet metrics, with optional latency summaries."""

    metrics: dict[str, int | float] = {
        "startup_packet_tokens_est": estimate_tokens(packet),
        "startup_packet_bytes": payload_byte_size(packet),
    }
    if latency_samples_ns:
        latencies_ms = tuple(sample / 1_000_000 for sample in latency_samples_ns)
        metrics["compile_latency_ms_p50"] = percentile(latencies_ms, 50)
        metrics["compile_latency_ms_p95"] = percentile(latencies_ms, 95)
        metrics["compile_latency_ms_max"] = max(latencies_ms)
    return metrics


def percentile(values: Sequence[float], percent: int) -> float:
    """Return a nearest-rank percentile for already bounded local samples."""

    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 < percent <= 100:
        raise ValueError("percent must be in the range 1..100")
    ordered = sorted(values)
    rank = max(1, round(len(ordered) * percent / 100))
    return ordered[min(rank, len(ordered)) - 1]


def check_performance_baseline(
    metrics: Mapping[str, int | float],
    baseline: Mapping[str, Any],
    *,
    metric_names: Iterable[str] | None = None,
) -> tuple[PerformanceFailure, ...]:
    """Compare observed metrics with a committed baseline's thresholds."""

    thresholds = baseline.get("thresholds", {})
    if not isinstance(thresholds, Mapping):
        raise ValueError("performance baseline thresholds must be a mapping")
    units = baseline.get("units", {})
    if not isinstance(units, Mapping):
        units = {}
    selected = set(metric_names) if metric_names is not None else set(thresholds)
    failures: list[PerformanceFailure] = []
    for metric in sorted(selected):
        raw_maximum = thresholds.get(metric)
        raw_observed = metrics.get(metric)
        if not isinstance(raw_maximum, int | float):
            raise ValueError(f"performance threshold missing or non-numeric: {metric}")
        if not isinstance(raw_observed, int | float):
            raise ValueError(f"performance metric missing or non-numeric: {metric}")
        observed = float(raw_observed)
        maximum = float(raw_maximum)
        if observed > maximum:
            unit = units.get(metric, "")
            failures.append(
                PerformanceFailure(
                    metric=metric,
                    observed=observed,
                    maximum=maximum,
                    unit=unit if isinstance(unit, str) else "",
                )
            )
    return tuple(failures)


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")
