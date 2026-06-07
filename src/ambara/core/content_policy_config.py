# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Content policy configuration — YAML schema, defaults, compilation.

Pure module. Parses policy dicts into compiled regex rules.
No I/O — callers load YAML and pass the dict here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from ambara.core.secret_patterns import DEFAULT_SECRET_BLOCK_RULES

_DEFAULT_BLOCK_RULES = DEFAULT_SECRET_BLOCK_RULES

_DEFAULT_REVIEW_RULES: dict[str, dict[str, Any]] = {
    "pii.email": {
        "pattern": r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "flags": ["ignorecase"],
    },
    "pii.us_phone": {
        "pattern": (
            r"\b(?:\+?1[-.\s]?)?(?:\([2-9]\d{2}\)|[2-9]\d{2})"
            r"[-.\s]?\d{3}[-.\s]?\d{4}\b"
        ),
        "flags": [],
    },
    "pii.ssn": {
        "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
        "flags": [],
    },
    "confidentiality.terms": {
        "pattern": (
            r"\b(?:confidential|do not share|private customer|customer data|"
            r"under nda|legal hold|personnel file|salary|compensation|"
            r"disciplinary)\b"
        ),
        "flags": ["ignorecase"],
    },
    "personnel.judgment": {
        "pattern": (
            r"\b(?:underperforming|poor performer|lazy|incompetent|"
            r"untrustworthy|should be fired|terminate\s+(?:his|her|their)\s+"
            r"employment|performance improvement plan)\b"
        ),
        "flags": ["ignorecase"],
    },
}

_DEFAULT_WARNING_RULES: dict[str, dict[str, Any]] = {
    "language.profanity": {
        "pattern": r"\b(?:fuck|shit|damn|crap)\b",
        "flags": ["ignorecase"],
    },
    "risk_phrase": {
        "pattern": (
            r"\b(?:hacky|quick and dirty|probably fine|"
            r"ship it anyway|ignore the failing tests)\b"
        ),
        "flags": ["ignorecase"],
    },
    "weak_prompt_injection": {
        "pattern": (
            r"\b(?:ignore (?:all )?(?:previous|prior) instructions|"
            r"system prompt|reveal your instructions|jailbreak)\b"
        ),
        "flags": ["ignorecase"],
    },
}


def _compile_flags(flag_list: list[str]) -> int:
    flags = 0
    for f in flag_list:
        if f.lower() == "ignorecase":
            flags |= re.IGNORECASE
    return flags


def _compile_rules(
    raw: dict[str, dict[str, Any]],
) -> dict[str, re.Pattern[str]]:
    compiled: dict[str, re.Pattern[str]] = {}
    for rule_id, spec in raw.items():
        pattern = spec.get("pattern", "")
        flags = _compile_flags(spec.get("flags", []))
        compiled[rule_id] = re.compile(pattern, flags)
    return compiled


def _policy_hash(config_dict: dict[str, Any]) -> str:
    canonical = json.dumps(config_dict, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class ContentPolicyConfig:
    """Parsed and compiled content policy configuration."""

    mode: str = "enforce"
    block_labels: list[str] = field(default_factory=lambda: ["content-safety-blocked"])
    review_labels: list[str] = field(default_factory=lambda: ["content-review-required"])
    warning_labels: list[str] = field(default_factory=lambda: ["content-warning"])
    compiled_block_rules: dict[str, re.Pattern[str]] = field(default_factory=dict)
    compiled_review_rules: dict[str, re.Pattern[str]] = field(default_factory=dict)
    compiled_warning_rules: dict[str, re.Pattern[str]] = field(default_factory=dict)
    policy_hash: str = ""

    source_title_max_chars: int = 160
    source_excerpt_max_chars: int = 360
    source_max_paths: int = 20

    @property
    def signal_title_max_chars(self) -> int:
        return self.source_title_max_chars

    @property
    def signal_excerpt_max_chars(self) -> int:
        return self.source_excerpt_max_chars

    @property
    def signal_max_paths(self) -> int:
        return self.source_max_paths


def default_config() -> ContentPolicyConfig:
    """Return the built-in default policy with all standard rules."""
    raw = {
        "mode": "enforce",
        "rules": {
            "block": _DEFAULT_BLOCK_RULES,
            "require_review": _DEFAULT_REVIEW_RULES,
            "allow_with_warning": _DEFAULT_WARNING_RULES,
        },
    }
    return parse_policy(raw)


def parse_policy(raw: dict[str, Any]) -> ContentPolicyConfig:
    """Parse a policy dict (from YAML or defaults) into compiled config."""
    mode = str(raw.get("mode", "enforce"))
    if mode not in ("enforce", "observe", "disabled"):
        mode = "enforce"

    rules = raw.get("rules", {})
    block_raw = rules.get("block", _DEFAULT_BLOCK_RULES)
    review_raw = rules.get("require_review", _DEFAULT_REVIEW_RULES)
    warning_raw = rules.get("allow_with_warning", _DEFAULT_WARNING_RULES)

    actions = raw.get("actions", {})
    block_labels = actions.get("block", {}).get("labels", ["content-safety-blocked"])
    review_labels = actions.get("require_review", {}).get("labels", ["content-review-required"])
    warning_labels = actions.get("allow_with_warning", {}).get("labels", ["content-warning"])

    rendering = raw.get("rendering", {})

    return ContentPolicyConfig(
        mode=mode,
        block_labels=block_labels,
        review_labels=review_labels,
        warning_labels=warning_labels,
        compiled_block_rules=_compile_rules(block_raw),
        compiled_review_rules=_compile_rules(review_raw),
        compiled_warning_rules=_compile_rules(warning_raw),
        policy_hash=_policy_hash(raw),
        source_title_max_chars=rendering.get(
            "source_title_max_chars",
            rendering.get("signal_title_max_chars", 160),
        ),
        source_excerpt_max_chars=rendering.get(
            "source_excerpt_max_chars",
            rendering.get("signal_excerpt_max_chars", 360),
        ),
        source_max_paths=rendering.get(
            "source_max_paths",
            rendering.get("signal_max_paths", 20),
        ),
    )
