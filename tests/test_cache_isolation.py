"""Cache isolation tests — different remotes use different paths."""

from __future__ import annotations

from pathlib import Path

from jurati.git.repo import repo_cache_path


class TestCacheIsolation:
    def test_different_remotes_different_dirs(self) -> None:
        p1 = repo_cache_path("https://github.com/org/repo-a.git", "/cache")
        p2 = repo_cache_path("https://github.com/org/repo-b.git", "/cache")
        assert p1 != p2

    def test_url_hash_based(self) -> None:
        path = repo_cache_path("https://github.com/org/repo.git", "/cache")
        cache_name = Path(path).name
        assert len(cache_name) == 16
        assert all(c in "0123456789abcdef" for c in cache_name)
