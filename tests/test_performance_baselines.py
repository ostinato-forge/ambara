# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ambara.core.performance import (
    PERFORMANCE_BASELINE_SCHEMA_VERSION,
    check_performance_baseline,
    startup_packet_metrics,
)
from tests._performance_scenarios import (
    STARTUP_V2_PRODUCTION_DAY_BASELINE,
    startup_v2_production_day_packet,
)

_BASELINE_PATH = (
    Path(__file__).parent
    / "performance"
    / "baselines"
    / f"{STARTUP_V2_PRODUCTION_DAY_BASELINE}.json"
)


def _load_baseline() -> dict[str, Any]:
    return json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))


def test_startup_performance_baseline_schema() -> None:
    baseline = _load_baseline()

    assert baseline["schema_version"] == PERFORMANCE_BASELINE_SCHEMA_VERSION
    assert baseline["scenario"] == STARTUP_V2_PRODUCTION_DAY_BASELINE
    assert baseline["metrics"]["startup_packet_tokens_est"] > 0
    assert baseline["thresholds"]["startup_packet_tokens_est"] >= baseline["metrics"][
        "startup_packet_tokens_est"
    ]


def test_startup_packet_size_stays_within_committed_baseline() -> None:
    packet = startup_v2_production_day_packet()
    metrics = startup_packet_metrics(packet)
    failures = check_performance_baseline(
        metrics,
        _load_baseline(),
        metric_names=("startup_packet_tokens_est", "startup_packet_bytes"),
    )

    assert not failures, "; ".join(failure.render() for failure in failures)
    assert packet["more"]["entries_omitted"] > 0
    assert packet["source_omissions"]["budget"] > 0
    assert packet["source_health"]["unavailable"] == 1


def test_coverage_gate_runs_performance_baseline() -> None:
    gate = (Path(__file__).parent.parent / "scripts" / "coverage-gate.sh").read_text(
        encoding="utf-8"
    )

    assert 'scripts/perf-baseline.py --check' in gate
