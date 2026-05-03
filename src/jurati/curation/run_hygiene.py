"""CLI/Action entrypoint for weekly hygiene scan."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from jurati.core.curation import detect_contradictions, find_stale_entries
from jurati.curation.hygiene_pr import build_hygiene_pr_body
from jurati.git.repo import ensure_repo, fetch_all, load_index_from_repo


def main() -> None:
    remote = os.environ["JURATI_KNOWLEDGE_REMOTE"]
    cache_dir = os.environ.get("JURATI_CACHE_DIR", "/tmp/jurati-knowledge")
    main_branch = os.environ.get("JURATI_MAIN_BRANCH", "main")
    now = datetime.now(UTC)

    repo_path = ensure_repo(remote, cache_dir)
    fetch_all(repo_path, main_branch)
    index = load_index_from_repo(repo_path, main_branch)
    entries = list(index.entries.values())

    stale = find_stale_entries(entries, now=now, stale_after_days=90)

    contradictions: list[tuple[str, list[str]]] = []
    for entry in entries:
        conflicts = detect_contradictions(
            entry.frontmatter.title,
            [e for e in entries if e.frontmatter.id != entry.frontmatter.id],
            entry_type=entry.frontmatter.type,
        )
        if conflicts:
            contradictions.append((entry.frontmatter.id, [c.frontmatter.id for c in conflicts]))

    body = build_hygiene_pr_body(stale_entries=stale, contradictions=contradictions, now=now)
    print(body)


if __name__ == "__main__":
    main()
