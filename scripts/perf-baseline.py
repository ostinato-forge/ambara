#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Update or check committed Ambara performance baselines."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from ambara.core.performance import (  # noqa: E402
    PERFORMANCE_BASELINE_SCHEMA_VERSION,
    check_performance_baseline,
    startup_packet_metrics,
)
from tests._performance_scenarios import (  # noqa: E402
    STARTUP_V2_PRODUCTION_DAY_BASELINE,
    startup_v2_production_day_scenario,
)

DEFAULT_BASELINE = (
    ROOT / "tests" / "performance" / "baselines" / f"{STARTUP_V2_PRODUCTION_DAY_BASELINE}.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="check the committed baseline")
    mode.add_argument("--update", action="store_true", help="write the measured baseline")
    args = parser.parse_args(argv)

    if args.iterations < 1:
        parser.error("--iterations must be at least 1")
    if args.warmup < 0:
        parser.error("--warmup must be non-negative")

    metrics = _measure_startup(args.iterations, args.warmup)
    if args.update:
        baseline = _baseline_payload(metrics)
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
        print(f"updated {args.baseline}")
        _print_metrics(metrics)
        return 0

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    failures = check_performance_baseline(metrics, baseline)
    _print_metrics(metrics)
    if failures:
        print("performance baseline failed:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure.render()}", file=sys.stderr)
        print(f"update intentionally with: {Path(__file__).name} --update", file=sys.stderr)
        return 1
    print("performance baseline ok")
    return 0


def _measure_startup(iterations: int, warmup: int) -> dict[str, int | float]:
    scenario = startup_v2_production_day_scenario()
    packet: dict[str, Any] | None = None
    for _ in range(warmup):
        packet = scenario.build_packet()

    samples: list[int] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        packet = scenario.build_packet()
        samples.append(time.perf_counter_ns() - started)

    if packet is None:
        packet = scenario.build_packet()
    return startup_packet_metrics(packet, latency_samples_ns=samples)


def _baseline_payload(metrics: dict[str, int | float]) -> dict[str, Any]:
    return {
        "schema_version": PERFORMANCE_BASELINE_SCHEMA_VERSION,
        "scenario": STARTUP_V2_PRODUCTION_DAY_BASELINE,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "description": (
            "Deterministic startup-s2 production-day fixture with 100 handoffs, "
            "source-input pressure, source omissions, and partial source outage state."
        ),
        "metrics": metrics,
        "thresholds": _thresholds(metrics),
        "units": {
            "startup_packet_tokens_est": "tokens",
            "startup_packet_bytes": "bytes",
            "compile_latency_ms_p95": "ms",
        },
    }


def _thresholds(metrics: dict[str, int | float]) -> dict[str, int | float]:
    tokens = int(metrics["startup_packet_tokens_est"])
    byte_size = int(metrics["startup_packet_bytes"])
    p95 = float(metrics["compile_latency_ms_p95"])
    return {
        "startup_packet_tokens_est": max(math.ceil(tokens * 1.15), tokens + 100),
        "startup_packet_bytes": max(math.ceil(byte_size * 1.15), byte_size + 512),
        "compile_latency_ms_p95": max(round(p95 * 4, 3), 50.0),
    }


def _print_metrics(metrics: dict[str, int | float]) -> None:
    for key in sorted(metrics):
        print(f"{key}: {metrics[key]}")


if __name__ == "__main__":
    raise SystemExit(main())
