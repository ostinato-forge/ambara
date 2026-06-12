# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""CLI/Action entrypoint for weekly hygiene scan."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import UTC, datetime

from ambara.core.curation import (
    detect_contradictions,
    find_stale_entries,
    suggest_revalidation_from_source_inputs,
)
from ambara.core.hygiene import summarize_lifecycle
from ambara.core.pr_signals import SourceInputLike
from ambara.curation.hygiene_pr import build_hygiene_pr_body
from ambara.git.curation import (
    default_curation_report_branch,
    materialize_curation_report,
)
from ambara.git.repo import ensure_repo, fetch_all, load_index_from_repo
from ambara.sources.config import SourceInputsConfig, source_inputs_config_from_env
from ambara.sources.runtime import fetch_source_runtime_report

_TRUE_VALUES = {"1", "true", "yes", "on"}


def main() -> None:
    remote = os.environ.get("AMBARA_KNOWLEDGE_REMOTE")
    if not remote:
        raise SystemExit("Error: AMBARA_KNOWLEDGE_REMOTE environment variable is required")
    cache_dir = os.environ.get(
        "AMBARA_CACHE_DIR", os.path.join(tempfile.gettempdir(), "ambara-knowledge")
    )
    main_branch = os.environ.get("AMBARA_MAIN_BRANCH", "main")
    now = datetime.now(UTC)

    repo_path = ensure_repo(remote, cache_dir)
    fetch_all(repo_path, main_branch)
    index = load_index_from_repo(repo_path, main_branch)
    entries = list(index.entries.values())

    stale = find_stale_entries(entries, now=now, stale_after_days=90)
    hygiene = summarize_lifecycle(index, now=now, stale_after_days=90)
    source_config = _source_config_from_env()
    source_inputs: tuple[SourceInputLike, ...] = ()
    if _source_inputs_configured(source_config):
        try:
            source_inputs = fetch_source_runtime_report(
                source_config, now=now
            ).source_report.artifacts
        except Exception:
            print(
                "Warning: source refresh failed; continuing without source advisories.",
                file=sys.stderr,
            )
    curation_advisories = suggest_revalidation_from_source_inputs(
        entries,
        source_inputs,
        now=now,
        recency_days=source_config.recency_days,
    )

    contradictions: list[tuple[str, list[str]]] = []
    for entry in entries:
        conflicts = detect_contradictions(
            entry.frontmatter.title,
            [e for e in entries if e.frontmatter.id != entry.frontmatter.id],
            entry_type=entry.frontmatter.type,
        )
        if conflicts:
            contradictions.append((entry.frontmatter.id, [c.frontmatter.id for c in conflicts]))

    body = build_hygiene_pr_body(
        stale_entries=stale,
        expired_active_entries=hygiene.expired_active,
        revalidation_entries=hygiene.revalidation,
        contradictions=contradictions,
        curation_advisories=curation_advisories,
        now=now,
    )
    print(body)

    if _env_flag("AMBARA_CURATION_WRITE"):
        has_findings = bool(
            stale
            or hygiene.expired_active
            or hygiene.revalidation
            or contradictions
            or curation_advisories
        )
        if not has_findings:
            print("\nNo curation review branch written; no findings.")
            return

        branch = os.environ.get("AMBARA_CURATION_BRANCH") or default_curation_report_branch(now)
        result = materialize_curation_report(
            repo_path,
            body,
            branch=branch,
            base=os.environ.get("AMBARA_CURATION_BASE", f"origin/{main_branch}"),
            path=os.environ.get("AMBARA_CURATION_REPORT_PATH") or None,
            now=now,
            revalidation_entry_ids=tuple(advisory.entry_id for advisory in curation_advisories),
            expired_active_entry_ids=tuple(item.id for item in hygiene.expired_active),
        )
        print("\nWrote curation review branch:")
        print(f"  branch: {result.branch}")
        print(f"  commit: {result.commit}")
        print(f"  path: {result.path}")
        if result.marked_paths:
            print("  marked for revalidation:")
            for path in result.marked_paths:
                print(f"    - {path}")
        if result.expired_paths:
            print("  marked expired:")
            for path in result.expired_paths:
                print(f"    - {path}")
        print("Next: push this branch and open a review request to merge it.")


def _source_config_from_env() -> SourceInputsConfig:
    return source_inputs_config_from_env()


def _signals_config_from_env() -> SourceInputsConfig:
    return _source_config_from_env()


def _source_inputs_configured(config: SourceInputsConfig) -> bool:
    return bool(
        config.fixture_path or config.repos or (config.jira_base_url and config.jira_projects)
    )


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


if __name__ == "__main__":
    main()
