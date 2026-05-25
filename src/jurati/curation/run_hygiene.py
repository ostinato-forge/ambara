"""CLI/Action entrypoint for weekly hygiene scan."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from jurati.core.curation import (
    detect_contradictions,
    find_stale_entries,
    suggest_revalidation_from_signals,
)
from jurati.core.hygiene import summarize_lifecycle
from jurati.curation.hygiene_pr import build_hygiene_pr_body
from jurati.git.config import PRSignalsConfig
from jurati.git.repo import ensure_repo, fetch_all, load_index_from_repo
from jurati.providers.signals import fetch_all_signals


def main() -> None:
    remote = os.environ.get("JURATI_KNOWLEDGE_REMOTE")
    if not remote:
        raise SystemExit("Error: JURATI_KNOWLEDGE_REMOTE environment variable is required")
    cache_dir = os.environ.get("JURATI_CACHE_DIR", "/tmp/jurati-knowledge")
    main_branch = os.environ.get("JURATI_MAIN_BRANCH", "main")
    now = datetime.now(UTC)

    repo_path = ensure_repo(remote, cache_dir)
    fetch_all(repo_path, main_branch)
    index = load_index_from_repo(repo_path, main_branch)
    entries = list(index.entries.values())

    stale = find_stale_entries(entries, now=now, stale_after_days=90)
    hygiene = summarize_lifecycle(index, now=now, stale_after_days=90)
    signal_config = _signals_config_from_env()
    signals = fetch_all_signals(signal_config) if _signals_configured(signal_config) else []
    curation_advisories = suggest_revalidation_from_signals(
        entries,
        signals,
        now=now,
        recency_days=signal_config.recency_days,
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
        revalidation_entries=hygiene.revalidation,
        contradictions=contradictions,
        curation_advisories=curation_advisories,
        now=now,
    )
    print(body)


def _signals_config_from_env() -> PRSignalsConfig:
    repos = tuple(
        repo.strip()
        for repo in os.environ.get("JURATI_PR_SIGNAL_REPOS", "").split(",")
        if repo.strip()
    )
    jira_projects = tuple(
        project.strip()
        for project in os.environ.get("JURATI_JIRA_PROJECTS", "").split(",")
        if project.strip()
    )
    return PRSignalsConfig(
        provider=os.environ.get("JURATI_SIGNAL_PROVIDER", "github"),
        repos=repos,
        fixture_path=os.environ.get("JURATI_PR_SIGNAL_FIXTURE") or None,
        jira_base_url=os.environ.get("JURATI_JIRA_BASE_URL") or None,
        jira_projects=jira_projects,
    )


def _signals_configured(config: PRSignalsConfig) -> bool:
    return bool(
        config.fixture_path or config.repos or (config.jira_base_url and config.jira_projects)
    )


if __name__ == "__main__":
    main()
