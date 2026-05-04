# Auth Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zero-config PR creation that works across multi-account GitHub setups by iterating through candidate auth sources until one succeeds, falling back to branch-only mode.

**Architecture:** New `git/auth.py` module handles GitHub remote URL parsing, candidate generation (env tokens, per-user `gh` tokens, active `gh` CLI), and prompt-safe subprocess helpers. `git/pr.py` is rewritten to dispatch across API/gh-CLI/branch-only strategies given a candidate list. `server.py` gains a shared `_finish_pr_write()` helper that serializes the full branch-push-PR-cleanup lifecycle under `write_lock`, used by all three PR-creating tools.

**Tech Stack:** Python 3.13+, httpx (sync), subprocess, pytest, ruff, mypy

**Spec:** `docs/superpowers/specs/2026-05-04-jurati-auth-resolver-design.md` (v4)

---

## File Structure

| File | Responsibility |
|---|---|
| `src/jurati/git/auth.py` | **New.** `parse_github_remote()`, `AuthCandidate` dataclass, `generate_candidates()`, `read_token()`, `discover_gh_users()`, prompt-safe subprocess helpers |
| `src/jurati/git/pr.py` | **Rewrite.** `PRResult` (with `kind`), `create_pr()` dispatching across candidates. `create_lightweight_pr`/`create_review_pr` removed. |
| `src/jurati/server.py` | **Modify.** `_finish_pr_write()` shared helper, `cached_pr_candidate` on `ServerState`, `_write_receipt`/`_expire_receipt` branch-only cases. Remove `_do_branch_record`, `create_lightweight_pr`/`create_review_pr` imports. |
| `pyproject.toml` | **Modify.** Add `httpx>=0.27` dependency, register `integration` pytest marker. |
| `tests/git/test_auth.py` | **New.** URL parsing, candidate generation, gh-user discovery, prompt suppression, token non-retention |
| `tests/git/test_pr.py` | **Rewrite.** Candidate-based API strategy, gh CLI strategy, branch-only, labels, timeouts, iteration |
| `tests/test_server_write.py` | **Extend.** `_finish_pr_write` orchestration, branch-only receipts |
| `tests/test_privacy.py` | **Extend.** Auth layer produces no telemetry |
| `tests/git/test_pr_integration.py` | **New optional.** Live `gh auth token` behind env gate |

---

### Task 1: Add httpx dependency and integration marker

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add httpx to dependencies and register integration marker**

```toml
# In [project] dependencies, add after "gitpython>=3.1":
    "httpx>=0.27",

# In [tool.pytest.ini_options], add:
markers = [
    "integration: live auth tests requiring gh CLI and JURATI_RUN_LIVE_AUTH_TESTS=1",
]
```

- [ ] **Step 2: Install updated dependencies**

Run: `source .venv/bin/activate && pip install -e ".[dev]"`
Expected: httpx installed, no errors

- [ ] **Step 3: Verify tests still pass**

Run: `pytest -q`
Expected: All existing tests pass (no regressions)

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat(auth): add httpx dependency and integration pytest marker"
```

---

### Task 2: parse_github_remote — URL parsing

**Files:**
- Create: `src/jurati/git/auth.py`
- Create: `tests/git/test_auth.py`

- [ ] **Step 1: Write failing tests for parse_github_remote**

```python
"""Tests for jurati.git.auth."""

from __future__ import annotations

import pytest

from jurati.git.auth import parse_github_remote


class TestParseGithubRemote:
    def test_ssh_colon_syntax(self) -> None:
        assert parse_github_remote("git@github.com:owner/repo.git") == ("owner", "repo")

    def test_https_with_dot_git(self) -> None:
        assert parse_github_remote("https://github.com/owner/repo.git") == ("owner", "repo")

    def test_https_without_dot_git(self) -> None:
        assert parse_github_remote("https://github.com/owner/repo") == ("owner", "repo")

    def test_ssh_url_syntax(self) -> None:
        assert parse_github_remote("ssh://git@github.com/owner/repo.git") == ("owner", "repo")

    def test_ssh_url_without_dot_git(self) -> None:
        assert parse_github_remote("ssh://git@github.com/owner/repo") == ("owner", "repo")

    def test_gitlab_returns_none(self) -> None:
        assert parse_github_remote("git@gitlab.com:owner/repo.git") is None

    def test_bitbucket_returns_none(self) -> None:
        assert parse_github_remote("https://bitbucket.org/owner/repo.git") is None

    def test_ghe_custom_domain_returns_none(self) -> None:
        assert parse_github_remote("git@github.mycompany.com:org/repo.git") is None

    def test_malformed_url_returns_none(self) -> None:
        assert parse_github_remote("not-a-url") is None

    def test_empty_string_returns_none(self) -> None:
        assert parse_github_remote("") is None

    def test_github_no_repo_returns_none(self) -> None:
        assert parse_github_remote("https://github.com/owner") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/git/test_auth.py -v`
Expected: ImportError — `jurati.git.auth` does not exist

- [ ] **Step 3: Implement parse_github_remote**

Create `src/jurati/git/auth.py`:

```python
"""GitHub auth candidate generation and prompt-safe subprocess helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_SSH_COLON = re.compile(r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$")
_HTTPS = re.compile(r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$")
_SSH_URL = re.compile(r"^ssh://git@github\.com/([^/]+)/([^/]+?)(?:\.git)?$")


def parse_github_remote(url: str) -> tuple[str, str] | None:
    for pattern in (_SSH_COLON, _HTTPS, _SSH_URL):
        m = pattern.match(url)
        if m:
            return (m.group(1), m.group(2))
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/git/test_auth.py -v`
Expected: All 11 tests pass

- [ ] **Step 5: Commit**

```bash
git add src/jurati/git/auth.py tests/git/test_auth.py
git commit -m "feat(auth): add parse_github_remote URL parser"
```

---

### Task 3: AuthCandidate dataclass and generate_candidates

**Files:**
- Modify: `src/jurati/git/auth.py`
- Modify: `tests/git/test_auth.py`

- [ ] **Step 1: Write failing tests for AuthCandidate and generate_candidates**

Append to `tests/git/test_auth.py`:

```python
import json
import os
from unittest.mock import patch

from jurati.git.auth import AuthCandidate, generate_candidates


class TestAuthCandidate:
    def test_frozen(self) -> None:
        c = AuthCandidate(method="branch_only", source="none")
        with pytest.raises(AttributeError):
            c.method = "api_token"  # type: ignore[misc]

    def test_no_token_field(self) -> None:
        c = AuthCandidate(method="api_token", source="env_jurati", owner="o", repo="r")
        assert not hasattr(c, "token")


class TestGenerateCandidates:
    def test_env_jurati_token_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_TOKEN", "fake-token")
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        candidates = generate_candidates("owner", "repo")
        assert candidates[0].source == "env_jurati"
        assert candidates[0].method == "api_token"

    def test_env_gh_token_second(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JURATI_KNOWLEDGE_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "fake-gh-token")
        candidates = generate_candidates("owner", "repo")
        assert candidates[0].source == "env_gh"

    def test_no_env_tokens_skips_to_gh_candidates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("JURATI_KNOWLEDGE_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("jurati.git.auth.discover_gh_users", return_value=[]):
            candidates = generate_candidates("owner", "repo")
        assert all(c.source != "env_jurati" for c in candidates)
        assert all(c.source != "env_gh" for c in candidates)

    def test_gh_users_produce_per_user_candidates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("JURATI_KNOWLEDGE_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("jurati.git.auth.discover_gh_users", return_value=["alice", "bob"]):
            candidates = generate_candidates("owner", "repo")
        user_candidates = [c for c in candidates if c.source == "gh_user_token"]
        assert len(user_candidates) == 2
        assert user_candidates[0].gh_user == "alice"
        assert user_candidates[1].gh_user == "bob"

    def test_gh_cli_pr_always_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JURATI_KNOWLEDGE_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("jurati.git.auth.discover_gh_users", return_value=[]):
            candidates = generate_candidates("owner", "repo")
        cli_candidates = [c for c in candidates if c.source == "gh_cli_pr"]
        assert len(cli_candidates) == 1

    def test_owner_repo_propagated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_TOKEN", "t")
        candidates = generate_candidates("myorg", "myrepo")
        for c in candidates:
            assert c.owner == "myorg"
            assert c.repo == "myrepo"

    def test_github_token_env_var_also_works(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("JURATI_KNOWLEDGE_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "fake-github-token")
        candidates = generate_candidates("owner", "repo")
        assert candidates[0].source == "env_gh"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/git/test_auth.py::TestAuthCandidate -v && pytest tests/git/test_auth.py::TestGenerateCandidates -v`
Expected: ImportError — `AuthCandidate` and `generate_candidates` not defined

- [ ] **Step 3: Implement AuthCandidate and generate_candidates**

Add to `src/jurati/git/auth.py`:

```python
import os
import subprocess


@dataclass(frozen=True)
class AuthCandidate:
    method: Literal["api_token", "gh_cli", "branch_only"]
    source: Literal[
        "env_jurati",
        "env_gh",
        "gh_user_token",
        "gh_cli_pr",
        "none",
    ]
    owner: str | None = None
    repo: str | None = None
    gh_user: str | None = None


def generate_candidates(owner: str, repo: str) -> list[AuthCandidate]:
    candidates: list[AuthCandidate] = []

    if os.environ.get("JURATI_KNOWLEDGE_TOKEN"):
        candidates.append(AuthCandidate(
            method="api_token", source="env_jurati", owner=owner, repo=repo,
        ))

    if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        candidates.append(AuthCandidate(
            method="api_token", source="env_gh", owner=owner, repo=repo,
        ))

    for user in discover_gh_users():
        candidates.append(AuthCandidate(
            method="api_token", source="gh_user_token",
            owner=owner, repo=repo, gh_user=user,
        ))

    candidates.append(AuthCandidate(
        method="gh_cli", source="gh_cli_pr", owner=owner, repo=repo,
    ))

    return candidates
```

- [ ] **Step 4: Add discover_gh_users stub**

Add to `src/jurati/git/auth.py` (before `generate_candidates`):

```python
def discover_gh_users() -> list[str]:
    return []
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/git/test_auth.py -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/jurati/git/auth.py tests/git/test_auth.py
git commit -m "feat(auth): add AuthCandidate dataclass and generate_candidates"
```

---

### Task 4: discover_gh_users and prompt-safe subprocess helpers

**Files:**
- Modify: `src/jurati/git/auth.py`
- Modify: `tests/git/test_auth.py`

- [ ] **Step 1: Write failing tests for discover_gh_users and read_token**

Append to `tests/git/test_auth.py`:

```python
from jurati.git.auth import discover_gh_users, read_token, _gh_subprocess_env


class TestDiscoverGhUsers:
    GH_STATUS_TWO_USERS = json.dumps({
        "hosts": {
            "github.com": [
                {"login": "alice", "state": "success", "active": True},
                {"login": "bob", "state": "success", "active": False},
            ],
        },
    })

    @patch("jurati.git.auth.subprocess.run")
    def test_parses_users_from_status_json(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        from unittest.mock import MagicMock

        result = MagicMock()
        result.returncode = 0
        result.stdout = self.GH_STATUS_TWO_USERS
        mock_run.return_value = result

        users = discover_gh_users()
        assert users == ["alice", "bob"]

    @patch("jurati.git.auth.subprocess.run")
    def test_filters_out_non_success_accounts(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        from unittest.mock import MagicMock

        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps({
            "hosts": {
                "github.com": [
                    {"login": "alice", "state": "success", "active": True},
                    {"login": "bob", "state": "expired", "active": False},
                ],
            },
        })
        mock_run.return_value = result

        users = discover_gh_users()
        assert users == ["alice"]

    @patch("jurati.git.auth.subprocess.run")
    def test_returns_empty_on_failure(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        mock_run.side_effect = subprocess.TimeoutExpired("gh", 15)
        assert discover_gh_users() == []

    @patch("jurati.git.auth.subprocess.run")
    def test_returns_empty_on_nonzero_exit(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        from unittest.mock import MagicMock

        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        mock_run.return_value = result

        assert discover_gh_users() == []

    @patch("jurati.git.auth.subprocess.run")
    def test_returns_empty_on_bad_json(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        from unittest.mock import MagicMock

        result = MagicMock()
        result.returncode = 0
        result.stdout = "not json"
        mock_run.return_value = result

        assert discover_gh_users() == []

    @patch("jurati.git.auth.subprocess.run")
    def test_uses_prompt_safe_env(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        from unittest.mock import MagicMock

        result = MagicMock()
        result.returncode = 0
        result.stdout = self.GH_STATUS_TWO_USERS
        mock_run.return_value = result

        discover_gh_users()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("stdin") == subprocess.DEVNULL
        assert call_kwargs.kwargs.get("capture_output") is True
        assert call_kwargs.kwargs.get("timeout") == 15
        env = call_kwargs.kwargs.get("env", {})
        assert env.get("GH_PROMPT_DISABLED") == "1"


class TestReadToken:
    def test_env_jurati(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_TOKEN", "my-jurati-token")
        candidate = AuthCandidate(
            method="api_token", source="env_jurati", owner="o", repo="r",
        )
        assert read_token(candidate) == "my-jurati-token"

    def test_env_gh_prefers_gh_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GH_TOKEN", "gh-token-value")
        monkeypatch.setenv("GITHUB_TOKEN", "github-token-value")
        candidate = AuthCandidate(
            method="api_token", source="env_gh", owner="o", repo="r",
        )
        assert read_token(candidate) == "gh-token-value"

    def test_env_gh_falls_back_to_github_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "github-token-value")
        candidate = AuthCandidate(
            method="api_token", source="env_gh", owner="o", repo="r",
        )
        assert read_token(candidate) == "github-token-value"

    @patch("jurati.git.auth.subprocess.run")
    def test_gh_user_token(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        from unittest.mock import MagicMock

        result = MagicMock()
        result.returncode = 0
        result.stdout = "gho_abc123\n"
        mock_run.return_value = result

        candidate = AuthCandidate(
            method="api_token", source="gh_user_token",
            owner="o", repo="r", gh_user="alice",
        )
        assert read_token(candidate) == "gho_abc123"

    @patch("jurati.git.auth.subprocess.run")
    def test_gh_user_token_uses_user_flag(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        from unittest.mock import MagicMock

        result = MagicMock()
        result.returncode = 0
        result.stdout = "gho_abc123\n"
        mock_run.return_value = result

        candidate = AuthCandidate(
            method="api_token", source="gh_user_token",
            owner="o", repo="r", gh_user="alice",
        )
        read_token(candidate)
        cmd = mock_run.call_args[0][0]
        assert "--user" in cmd
        assert "alice" in cmd

    @patch("jurati.git.auth.subprocess.run")
    def test_gh_user_token_timeout_returns_none(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        mock_run.side_effect = subprocess.TimeoutExpired("gh", 15)
        candidate = AuthCandidate(
            method="api_token", source="gh_user_token",
            owner="o", repo="r", gh_user="alice",
        )
        assert read_token(candidate) is None

    def test_non_token_candidate_returns_none(self) -> None:
        candidate = AuthCandidate(method="gh_cli", source="gh_cli_pr", owner="o", repo="r")
        assert read_token(candidate) is None


class TestPromptSafeEnv:
    def test_includes_gh_prompt_disabled(self) -> None:
        env = _gh_subprocess_env()
        assert env["GH_PROMPT_DISABLED"] == "1"

    def test_inherits_path(self) -> None:
        env = _gh_subprocess_env()
        assert "PATH" in env
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/git/test_auth.py::TestDiscoverGhUsers -v`
Expected: ImportError or assertion failures

- [ ] **Step 3: Implement the functions**

Update `src/jurati/git/auth.py` — replace the `discover_gh_users` stub and add `read_token` and `_gh_subprocess_env`:

```python
import json


def _gh_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GH_PROMPT_DISABLED"] = "1"
    return env


def discover_gh_users() -> list[str]:
    try:
        result = subprocess.run(
            ["gh", "auth", "status", "--hostname", "github.com", "--json", "hosts"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            env=_gh_subprocess_env(),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    if result.returncode != 0:
        return []

    try:
        data = json.loads(result.stdout)
        accounts = data.get("hosts", {}).get("github.com", [])
        return sorted(
            a["login"] for a in accounts
            if a.get("state") == "success" and "login" in a
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


def read_token(candidate: AuthCandidate) -> str | None:
    if candidate.source == "env_jurati":
        return os.environ.get("JURATI_KNOWLEDGE_TOKEN")

    if candidate.source == "env_gh":
        return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    if candidate.source == "gh_user_token" and candidate.gh_user:
        try:
            result = subprocess.run(
                [
                    "gh", "auth", "token",
                    "--hostname", "github.com",
                    "--user", candidate.gh_user,
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=15,
                env=_gh_subprocess_env(),
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/git/test_auth.py -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add src/jurati/git/auth.py tests/git/test_auth.py
git commit -m "feat(auth): implement discover_gh_users, read_token, and prompt-safe env"
```

---

### Task 5: Rewrite PRResult and create_pr with candidate iteration

**Files:**
- Modify: `src/jurati/git/pr.py`
- Modify: `tests/git/test_pr.py`

- [ ] **Step 1: Write failing tests for the new pr.py**

Replace `tests/git/test_pr.py` entirely:

```python
"""Tests for jurati.git.pr."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from unittest.mock import MagicMock, patch

import pytest

from jurati.git.auth import AuthCandidate
from jurati.git.pr import PRResult, create_pr


def _api_candidate(owner: str = "org", repo: str = "repo") -> AuthCandidate:
    return AuthCandidate(
        method="api_token", source="env_jurati", owner=owner, repo=repo,
    )


def _gh_user_candidate(user: str = "alice") -> AuthCandidate:
    return AuthCandidate(
        method="api_token", source="gh_user_token",
        owner="org", repo="repo", gh_user=user,
    )


def _cli_candidate(owner: str = "org", repo: str = "repo") -> AuthCandidate:
    return AuthCandidate(
        method="gh_cli", source="gh_cli_pr", owner=owner, repo=repo,
    )


class TestPRResult:
    def test_pr_kind(self) -> None:
        r = PRResult(url="https://github.com/o/r/pull/1", number=1, branch="b", kind="pr")
        assert r.kind == "pr"
        assert r.number == 1

    def test_branch_kind(self) -> None:
        r = PRResult(url=None, number=None, branch="b", kind="branch")
        assert r.kind == "branch"
        assert r.number is None
        assert r.url is None


class TestCreatePrApiStrategy:
    @patch("jurati.git.pr.read_token", return_value="tok_abc")
    @patch("jurati.git.pr.httpx")
    def test_creates_pr_via_api(self, mock_httpx, mock_read_token) -> None:  # type: ignore[no-untyped-def]
        pr_response = MagicMock()
        pr_response.status_code = 201
        pr_response.json.return_value = {
            "html_url": "https://github.com/org/repo/pull/42",
            "number": 42,
        }
        label_response = MagicMock()
        label_response.status_code = 200
        mock_httpx.post.side_effect = [pr_response, label_response]

        pr_result, winning = create_pr(
            "/repo", "feat/test", "Title", "Body",
            labels=["jurati", "low-ceremony"],
            base="main",
            candidates=[_api_candidate()],
        )
        assert pr_result.kind == "pr"
        assert pr_result.number == 42
        assert pr_result.url == "https://github.com/org/repo/pull/42"
        assert winning is not None
        assert winning.source == "env_jurati"

    @patch("jurati.git.pr.read_token", return_value="tok_abc")
    @patch("jurati.git.pr.httpx")
    def test_api_sets_timeout(self, mock_httpx, mock_read_token) -> None:  # type: ignore[no-untyped-def]
        pr_response = MagicMock()
        pr_response.status_code = 201
        pr_response.json.return_value = {
            "html_url": "https://github.com/org/repo/pull/1",
            "number": 1,
        }
        label_response = MagicMock()
        label_response.status_code = 200
        mock_httpx.post.side_effect = [pr_response, label_response]

        create_pr(
            "/repo", "feat/test", "Title", "Body",
            labels=["jurati"], base="main",
            candidates=[_api_candidate()],
        )
        call_kwargs = mock_httpx.post.call_args_list[0]
        assert call_kwargs.kwargs.get("timeout") == 30

    @patch("jurati.git.pr.read_token", return_value="tok_abc")
    @patch("jurati.git.pr.httpx")
    def test_label_failure_is_nonfatal(self, mock_httpx, mock_read_token) -> None:  # type: ignore[no-untyped-def]
        pr_response = MagicMock()
        pr_response.status_code = 201
        pr_response.json.return_value = {
            "html_url": "https://github.com/org/repo/pull/5",
            "number": 5,
        }
        mock_httpx.post.side_effect = [pr_response, Exception("label failed")]

        pr_result, _ = create_pr(
            "/repo", "feat/test", "Title", "Body",
            labels=["jurati"], base="main",
            candidates=[_api_candidate()],
        )
        assert pr_result.kind == "pr"
        assert pr_result.number == 5

    @patch("jurati.git.pr.read_token", return_value="tok_abc")
    @patch("jurati.git.pr.httpx")
    def test_malformed_api_response_falls_through(self, mock_httpx, mock_read_token) -> None:  # type: ignore[no-untyped-def]
        bad_response = MagicMock()
        bad_response.status_code = 201
        bad_response.json.side_effect = Exception("not json")
        mock_httpx.post.return_value = bad_response

        pr_result, winning = create_pr(
            "/repo", "feat/test", "Title", "Body",
            labels=[], base="main",
            candidates=[_api_candidate()],
        )
        assert pr_result.kind == "branch"
        assert winning is None


class TestCreatePrCandidateIteration:
    @patch("jurati.git.pr.read_token", return_value="tok_abc")
    @patch("jurati.git.pr.httpx")
    def test_first_failing_candidate_tries_next(self, mock_httpx, mock_read_token) -> None:  # type: ignore[no-untyped-def]
        fail_response = MagicMock()
        fail_response.status_code = 401
        fail_response.text = "Bad credentials"
        pr_response = MagicMock()
        pr_response.status_code = 201
        pr_response.json.return_value = {
            "html_url": "https://github.com/org/repo/pull/7",
            "number": 7,
        }
        mock_httpx.post.side_effect = [fail_response, pr_response]

        bob = _gh_user_candidate("bob")
        candidates = [_api_candidate(), bob]
        pr_result, winning = create_pr(
            "/repo", "feat/test", "Title", "Body",
            labels=[], base="main",
            candidates=candidates,
        )
        assert pr_result.kind == "pr"
        assert pr_result.number == 7
        assert winning is bob

    @patch("jurati.git.pr.read_token", return_value=None)
    def test_no_token_skips_api_candidate(self, mock_read_token) -> None:  # type: ignore[no-untyped-def]
        pr_result, winning = create_pr(
            "/repo", "feat/test", "Title", "Body",
            labels=[], base="main",
            candidates=[_api_candidate()],
        )
        assert pr_result.kind == "branch"
        assert winning is None


class TestCreatePrGhCliStrategy:
    @patch("jurati.git.pr.subprocess.run")
    def test_gh_cli_with_repo_flag(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        result_mock = MagicMock()
        result_mock.returncode = 0
        result_mock.stdout = "https://github.com/org/repo/pull/10\n"
        mock_run.return_value = result_mock

        pr_result, winning = create_pr(
            "/repo", "feat/test", "Title", "Body",
            labels=["jurati"], base="main",
            candidates=[_cli_candidate()],
        )
        assert pr_result.kind == "pr"
        assert pr_result.number == 10
        assert winning is not None
        assert winning.source == "gh_cli_pr"

        cmd = mock_run.call_args[0][0]
        assert "--repo" in cmd
        assert "org/repo" in cmd
        assert mock_run.call_args.kwargs.get("timeout") == 30
        assert mock_run.call_args.kwargs.get("stdin") == subprocess.DEVNULL

    @patch("jurati.git.pr.subprocess.run")
    def test_gh_cli_failure_falls_to_branch_only(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        mock_run.side_effect = subprocess.CalledProcessError(1, "gh")

        pr_result, winning = create_pr(
            "/repo", "feat/test", "Title", "Body",
            labels=[], base="main",
            candidates=[_cli_candidate()],
        )
        assert pr_result.kind == "branch"
        assert winning is None


class TestCreatePrBranchOnly:
    def test_empty_candidates_returns_branch_only(self) -> None:
        pr_result, winning = create_pr(
            "/repo", "feat/test", "Title", "Body",
            labels=[], base="main",
            candidates=[],
        )
        assert pr_result.kind == "branch"
        assert pr_result.number is None
        assert pr_result.url is None
        assert winning is None

    def test_branch_only_with_owner_repo_has_compare_url(self) -> None:
        candidate = AuthCandidate(
            method="branch_only", source="none", owner="org", repo="repo",
        )
        pr_result, winning = create_pr(
            "/repo", "feat/test", "Title", "Body",
            labels=[], base="main",
            candidates=[candidate],
        )
        assert pr_result.kind == "branch"
        assert pr_result.url is not None
        assert "compare/main...feat/test" in pr_result.url
        assert "expand=1" in pr_result.url
        assert winning is None

    def test_branch_only_without_owner_repo_has_no_url(self) -> None:
        candidate = AuthCandidate(
            method="branch_only", source="none",
        )
        pr_result, winning = create_pr(
            "/repo", "feat/test", "Title", "Body",
            labels=[], base="main",
            candidates=[candidate],
        )
        assert pr_result.kind == "branch"
        assert pr_result.url is None
        assert winning is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/git/test_pr.py -v`
Expected: Failures — old `create_pr` signature doesn't match

- [ ] **Step 3: Rewrite pr.py**

Replace `src/jurati/git/pr.py` entirely:

```python
"""PR creation with candidate-based auth dispatch."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import httpx

from jurati.git.auth import AuthCandidate, _gh_subprocess_env, read_token


@dataclass(frozen=True)
class PRResult:
    url: str | None
    number: int | None
    branch: str
    kind: Literal["pr", "branch"]


def create_pr(
    repo_path: str,
    branch: str,
    title: str,
    body: str,
    *,
    labels: list[str],
    base: str,
    candidates: Sequence[AuthCandidate],
) -> tuple[PRResult, AuthCandidate | None]:
    owner: str | None = None
    repo: str | None = None

    for candidate in candidates:
        if candidate.owner:
            owner = candidate.owner
        if candidate.repo:
            repo = candidate.repo

        if candidate.method == "api_token":
            result = _try_api(candidate, branch, title, body, labels=labels, base=base)
            if result is not None:
                return result, candidate

        elif candidate.method == "gh_cli":
            result = _try_gh_cli(
                repo_path, candidate, branch, title, body, labels=labels, base=base,
            )
            if result is not None:
                return result, candidate

    return _branch_only(branch, owner=owner, repo=repo, base=base), None


def _try_api(
    candidate: AuthCandidate,
    branch: str,
    title: str,
    body: str,
    *,
    labels: list[str],
    base: str,
) -> PRResult | None:
    token = read_token(candidate)
    if token is None:
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    try:
        resp = httpx.post(
            f"https://api.github.com/repos/{candidate.owner}/{candidate.repo}/pulls",
            headers=headers,
            json={"title": title, "body": body, "head": branch, "base": base},
            timeout=30,
        )
        if resp.status_code != 201:
            return None

        data = resp.json()
        pr_number = data["number"]
        pr_url = data["html_url"]
    except Exception:
        return None

    if labels:
        try:
            httpx.post(
                f"https://api.github.com/repos/{candidate.owner}/{candidate.repo}"
                f"/issues/{pr_number}/labels",
                headers=headers,
                json={"labels": labels},
                timeout=30,
            )
        except Exception:
            pass

    return PRResult(url=pr_url, number=pr_number, branch=branch, kind="pr")


def _try_gh_cli(
    repo_path: str,
    candidate: AuthCandidate,
    branch: str,
    title: str,
    body: str,
    *,
    labels: list[str],
    base: str,
) -> PRResult | None:
    cmd = [
        "gh", "pr", "create",
        "--repo", f"{candidate.owner}/{candidate.repo}",
        "--title", title,
        "--body", body,
        "--head", branch,
        "--base", base,
    ]
    for label in labels:
        cmd.extend(["--label", label])

    try:
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            env=_gh_subprocess_env(),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if result.returncode != 0:
        return None

    url = result.stdout.strip()
    try:
        number = int(url.rstrip("/").rsplit("/", 1)[-1])
    except (ValueError, IndexError):
        return None

    return PRResult(url=url, number=number, branch=branch, kind="pr")


def _branch_only(
    branch: str,
    *,
    owner: str | None,
    repo: str | None,
    base: str,
) -> PRResult:
    url: str | None = None
    if owner and repo:
        url = f"https://github.com/{owner}/{repo}/compare/{base}...{branch}?expand=1"
    return PRResult(url=url, number=None, branch=branch, kind="branch")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/git/test_pr.py -v`
Expected: All tests pass

- [ ] **Step 5: Run full test suite to check for breakage**

Run: `pytest -q`
Expected: Failures in `test_server_write.py` and `test_server.py` (they import removed functions). This is expected and will be fixed in Task 7.

- [ ] **Step 6: Commit**

```bash
git add src/jurati/git/pr.py tests/git/test_pr.py
git commit -m "feat(auth): rewrite pr.py with candidate-based dispatch and PRResult.kind"
```

---

### Task 6: Update receipts for branch-only mode

**Files:**
- Modify: `src/jurati/server.py` (receipts only)
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write failing tests for branch-only receipts**

Add to `tests/test_server.py` in `class TestReceipts`:

```python
    def test_branch_only_write_receipt(self) -> None:
        receipt = _write_receipt(
            entry_id="new-project",
            write_mode="branch_only",
            commit="abc123",
            branch="jurati/new-project",
        )
        assert "branch" in receipt["what_happened"].lower()
        assert receipt["branch"] == "jurati/new-project"
        assert "pr_url" not in receipt or receipt.get("pr_url") is None

    def test_branch_only_expire_receipt(self) -> None:
        receipt = _expire_receipt(
            entry_id="old-decision",
            write_mode="branch_only",
            commit="def456",
            branch="jurati/expire-old-decision",
        )
        assert "branch" in receipt["what_happened"].lower()
        assert receipt["branch"] == "jurati/expire-old-decision"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_server.py::TestReceipts -v`
Expected: Assertion failures — current receipts don't handle `branch_only`

- [ ] **Step 3: Add branch_only cases to both receipt functions**

In `src/jurati/server.py`, update `_write_receipt` — add after the `lightweight_pr` block:

```python
    if write_mode == "branch_only":
        return {
            "what_happened": f"Pushed proposed knowledge branch {branch}.",
            "visibility": (
                "The branch is reviewable; source-of-truth content changes "
                "only after a PR is opened and merged into main."
            ),
            "next_step": "Open or review the branch and merge accepted content.",
            "branch": branch,
            "review_url": pr_url,
            "commit": commit,
        }
```

In `_expire_receipt`, add before the final `return`:

```python
    if write_mode == "branch_only":
        return {
            "what_happened": f"Pushed expiry branch {branch}.",
            "visibility": (
                "The branch is reviewable; source-of-truth changes only after merge."
            ),
            "next_step": "Open or review the expiry branch and merge if accepted.",
            "branch": branch,
            "review_url": pr_url,
            "commit": commit,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_server.py::TestReceipts -v`
Expected: All pass (including both new tests)

- [ ] **Step 5: Commit**

```bash
git add src/jurati/server.py tests/test_server.py
git commit -m "feat(auth): add branch_only mode to write and expire receipts"
```

---

### Task 7: Rewrite server.py write orchestration

**Files:**
- Modify: `src/jurati/server.py`
- Modify: `tests/test_server_write.py`

This is the largest task. It replaces `_do_branch_record`, the separate PR calls, and the separate cleanup calls with a single `_finish_pr_write` helper. It also adds `cached_pr_candidate` to `ServerState`.

- [ ] **Step 1: Update ServerState and imports in server.py**

In `src/jurati/server.py`:

Replace the import block:
```python
from jurati.git.pr import create_lightweight_pr, create_review_pr
```
with:
```python
from jurati.git.auth import AuthCandidate, generate_candidates, parse_github_remote
from jurati.git.pr import PRResult, create_pr
```

Add to `ServerState`:
```python
    cached_pr_candidate: AuthCandidate | None = None
```

- [ ] **Step 2: Write the _finish_pr_write helper**

Add to `src/jurati/server.py` after `_do_active_record`:

```python
def _finish_pr_write(
    lock: threading.Lock,
    repo_path: str,
    intent: WriteIntent | ExpireIntent,
    *,
    title: str,
    body: str,
    labels: list[str],
    base: str,
    remote_url: str,
    cached_candidate: AuthCandidate | None,
    now: datetime | None = None,
) -> tuple[str, PRResult, AuthCandidate | None]:
    if intent.branch is None:
        raise ValueError("branch must not be None for PR write")
    branch = intent.branch

    parsed = parse_github_remote(remote_url)
    if parsed is not None:
        owner, repo = parsed
        candidates: list[AuthCandidate] = []
        if cached_candidate is not None:
            candidates.append(cached_candidate)
        candidates.extend(generate_candidates(owner, repo))
    else:
        candidates = []

    with lock:
        try:
            create_branch(repo_path, branch, f"origin/{base}")
            if isinstance(intent, ExpireIntent) and now is not None:
                sha = materialize_expire(repo_path, intent, now)
            else:
                sha = materialize_write(repo_path, intent)
            push_branch(repo_path, branch)

            pr_result, winning_candidate = create_pr(
                repo_path, branch, title, body,
                labels=labels, base=base, candidates=candidates,
            )

            return sha, pr_result, winning_candidate
        finally:
            try:
                cleanup_branch(repo_path, branch, base)
            except Exception:
                pass
```

- [ ] **Step 3: Rewrite record() L1 path to use _finish_pr_write**

Replace the L1 path in `record()` (lines 606–636) with:

```python
    if intent.branch is None:
        raise ValueError("branch must not be None for L1 record")

    sha, pr_result, new_cached = await anyio.to_thread.run_sync(
        lambda: _finish_pr_write(
            state.write_lock,
            state.repo_path,
            intent,
            title=f"feat(kb): add {eid}",
            body=f"Add {entry_type} entry: {title}",
            labels=["jurati", "low-ceremony"],
            base=config.main_branch,
            remote_url=config.remote_url,
            cached_candidate=state.cached_pr_candidate,
        )
    )
    if new_cached is not None:
        state.cached_pr_candidate = new_cached

    write_mode = "lightweight_pr" if pr_result.kind == "pr" else "branch_only"
    return {
        "status": "ok",
        "entry_id": eid,
        "write_mode": write_mode,
        **_write_receipt(
            entry_id=eid,
            write_mode=write_mode,
            commit=sha,
            branch=intent.branch,
            pr_url=pr_result.url,
            pr_number=pr_result.number,
        ),
    }
```

- [ ] **Step 4: Rewrite propose() to use _finish_pr_write**

Replace the branch push, PR creation, and cleanup in `propose()` (lines 687–717) with:

```python
    if intent.branch is None:
        raise ValueError("branch must not be None for propose")

    sha, pr_result, new_cached = await anyio.to_thread.run_sync(
        lambda: _finish_pr_write(
            state.write_lock,
            state.repo_path,
            intent,
            title=f"feat(kb): propose {eid}",
            body=f"Propose {entry_type} entry: {title}",
            labels=["jurati", "review-required"],
            base=config.main_branch,
            remote_url=config.remote_url,
            cached_candidate=state.cached_pr_candidate,
        )
    )
    if new_cached is not None:
        state.cached_pr_candidate = new_cached

    write_mode = "review_pr" if pr_result.kind == "pr" else "branch_only"
    return {
        "status": "ok",
        "entry_id": eid,
        "write_mode": write_mode,
        **_write_receipt(
            entry_id=eid,
            write_mode=write_mode,
            commit=sha,
            branch=intent.branch,
            pr_url=pr_result.url,
            pr_number=pr_result.number,
        ),
    }
```

- [ ] **Step 5: Rewrite expire() L1+ path to use _finish_pr_write**

Replace the branch push, PR creation, and cleanup in `expire()` (lines 752–785) with:

```python
    if intent.branch is None:
        raise ValueError("branch must not be None for non-L0 expire")

    sha, pr_result, new_cached = await anyio.to_thread.run_sync(
        lambda: _finish_pr_write(
            state.write_lock,
            state.repo_path,
            intent,
            title=f"chore(kb): expire {id}",
            body=reason or f"Expire entry: {entry.frontmatter.title}",
            labels=["jurati", "review-required"],
            base=config.main_branch,
            remote_url=config.remote_url,
            cached_candidate=state.cached_pr_candidate,
            now=now,
        )
    )
    if new_cached is not None:
        state.cached_pr_candidate = new_cached

    write_mode = intent.write_mode if pr_result.kind == "pr" else "branch_only"
    return {
        "status": "ok",
        "entry_id": id,
        "write_mode": write_mode,
        **_expire_receipt(
            entry_id=id,
            write_mode=write_mode,
            commit=sha,
            branch=intent.branch,
            pr_url=pr_result.url,
            pr_number=pr_result.number,
        ),
    }
```

- [ ] **Step 6: Remove dead code**

Remove from `server.py`:
- `_do_branch_record` function
- `_do_expire_branch` function
- Old imports: `create_lightweight_pr`, `create_review_pr`

- [ ] **Step 7: Update test_server_write.py**

Replace `tests/test_server_write.py`:

```python
"""Tests for jurati.server write orchestration."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from jurati.core.changes import ExpireIntent, WriteIntent
from jurati.core.schema import EntryStatus, EscalationLevel
from jurati.server import _do_active_record, _finish_pr_write


class TestPlanRecord:
    def test_l0_uses_active_ref(self) -> None:
        from jurati.core.changes import plan_record
        from jurati.core.schema import EntryType

        intent = plan_record(
            EntryType.ACTIVE,
            "Sprint goal",
            "Ship v1",
            entry_id="sprint-goal",
            level=EscalationLevel.L0,
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            expires_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            client="test-client",
        )
        assert intent.write_mode == "active_ref"
        assert "jurati/active/test-client/sprint-goal" in intent.branch

    def test_l1_uses_lightweight_pr(self) -> None:
        from jurati.core.changes import plan_record
        from jurati.core.schema import EntryType

        intent = plan_record(
            EntryType.PROJECT,
            "New project",
            "Project body",
            entry_id="new-project",
            level=EscalationLevel.L1,
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        )
        assert intent.write_mode == "lightweight_pr"

    def test_l2_rejected(self) -> None:
        from jurati.core.changes import plan_record
        from jurati.core.schema import EntryType

        with pytest.raises(ValueError, match="cannot create L2"):
            plan_record(
                EntryType.DECISION,
                "Decision",
                "Body",
                entry_id="dec-1",
                level=EscalationLevel.L2,
                now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            )


class TestPlanPropose:
    def test_l2_uses_review_pr(self) -> None:
        from jurati.core.changes import plan_propose
        from jurati.core.schema import EntryType

        intent = plan_propose(
            EntryType.DECISION,
            "Decision",
            "Body",
            entry_id="dec-1",
            level=EscalationLevel.L2,
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        )
        assert intent.write_mode == "review_pr"

    def test_l0_rejected(self) -> None:
        from jurati.core.changes import plan_propose
        from jurati.core.schema import EntryType

        with pytest.raises(ValueError, match="cannot create L0"):
            plan_propose(
                EntryType.ACTIVE,
                "Active",
                "Body",
                entry_id="active-1",
                level=EscalationLevel.L0,
                now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            )


class TestDoActiveRecord:
    @patch("jurati.server.cleanup_branch")
    @patch("jurati.server.push_active_ref")
    @patch("jurati.server.materialize_write", return_value="abc123")
    @patch("jurati.server.create_branch")
    def test_sequence(self, mock_create, mock_write, mock_push, mock_cleanup) -> None:
        intent = WriteIntent(
            path="active/sprint.md",
            content="content",
            branch="jurati/active/client/sprint",
            write_mode="active_ref",
            entry_id="sprint",
            level=EscalationLevel.L0,
        )
        lock = threading.Lock()
        sha = _do_active_record(lock, "/repo", intent, "main")
        assert sha == "abc123"
        mock_create.assert_called_once()
        mock_write.assert_called_once()
        mock_push.assert_called_once_with("/repo", "jurati/active/client/sprint", "abc123")
        mock_cleanup.assert_called_once()


class TestFinishPrWrite:
    @patch("jurati.server.create_pr")
    @patch("jurati.server.push_branch")
    @patch("jurati.server.materialize_write", return_value="sha123")
    @patch("jurati.server.create_branch")
    @patch("jurati.server.cleanup_branch")
    def test_serialized_lifecycle(
        self, mock_cleanup, mock_create_branch, mock_write, mock_push, mock_create_pr
    ) -> None:
        from jurati.git.auth import AuthCandidate
        from jurati.git.pr import PRResult

        winning = AuthCandidate(
            method="api_token", source="env_jurati", owner="owner", repo="repo",
        )
        mock_create_pr.return_value = (
            PRResult(
                url="https://github.com/o/r/pull/1", number=1,
                branch="jurati/proj", kind="pr",
            ),
            winning,
        )
        intent = WriteIntent(
            path="projects/proj.md",
            content="content",
            branch="jurati/proj",
            write_mode="lightweight_pr",
            entry_id="proj",
            level=EscalationLevel.L1,
        )
        lock = threading.Lock()
        sha, pr_result, cached = _finish_pr_write(
            lock, "/repo", intent,
            title="feat(kb): add proj",
            body="Add project entry: Proj",
            labels=["jurati", "low-ceremony"],
            base="main",
            remote_url="git@github.com:owner/repo.git",
            cached_candidate=None,
        )
        assert sha == "sha123"
        assert pr_result.kind == "pr"
        assert cached is winning
        mock_create_branch.assert_called_once()
        mock_write.assert_called_once()
        mock_push.assert_called_once()
        mock_create_pr.assert_called_once()
        mock_cleanup.assert_called_once()

    @patch("jurati.server.create_pr")
    @patch("jurati.server.push_branch")
    @patch("jurati.server.materialize_write", return_value="sha456")
    @patch("jurati.server.create_branch")
    @patch("jurati.server.cleanup_branch")
    def test_cleanup_runs_on_pr_failure(
        self, mock_cleanup, mock_create_branch, mock_write, mock_push, mock_create_pr
    ) -> None:
        from jurati.git.pr import PRResult

        mock_create_pr.return_value = (
            PRResult(
                url=None, number=None, branch="jurati/proj", kind="branch",
            ),
            None,
        )
        intent = WriteIntent(
            path="projects/proj.md",
            content="content",
            branch="jurati/proj",
            write_mode="lightweight_pr",
            entry_id="proj",
            level=EscalationLevel.L1,
        )
        lock = threading.Lock()
        sha, pr_result, cached = _finish_pr_write(
            lock, "/repo", intent,
            title="t", body="b", labels=[], base="main",
            remote_url="git@github.com:owner/repo.git",
            cached_candidate=None,
        )
        assert pr_result.kind == "branch"
        assert cached is None
        mock_cleanup.assert_called_once()

    @patch("jurati.server.create_pr")
    @patch("jurati.server.push_branch")
    @patch("jurati.server.materialize_expire", return_value="sha789")
    @patch("jurati.server.create_branch")
    @patch("jurati.server.cleanup_branch")
    def test_expire_intent_uses_materialize_expire(
        self, mock_cleanup, mock_create_branch, mock_expire, mock_push, mock_create_pr
    ) -> None:
        from jurati.git.pr import PRResult

        mock_create_pr.return_value = (
            PRResult(
                url="https://github.com/o/r/pull/3", number=3,
                branch="jurati/expire-old", kind="pr",
            ),
            None,
        )
        intent = ExpireIntent(
            entry_id="old-dec",
            path="decisions/old-dec.md",
            write_mode="review_pr",
            branch="jurati/expire-old",
            new_status=EntryStatus.EXPIRED,
        )
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        lock = threading.Lock()
        sha, pr_result, _ = _finish_pr_write(
            lock, "/repo", intent,
            title="chore(kb): expire old-dec",
            body="Expire entry",
            labels=["jurati", "review-required"],
            base="main",
            remote_url="git@github.com:owner/repo.git",
            cached_candidate=None,
            now=now,
        )
        assert sha == "sha789"
        mock_expire.assert_called_once_with("/repo", intent, now)

    @patch("jurati.server.create_pr")
    @patch("jurati.server.push_branch")
    @patch("jurati.server.materialize_write", return_value="sha000")
    @patch("jurati.server.create_branch")
    @patch("jurati.server.cleanup_branch")
    def test_non_github_remote_goes_branch_only(
        self, mock_cleanup, mock_create_branch, mock_write, mock_push, mock_create_pr
    ) -> None:
        from jurati.git.pr import PRResult

        mock_create_pr.return_value = (
            PRResult(
                url=None, number=None, branch="jurati/proj", kind="branch",
            ),
            None,
        )
        intent = WriteIntent(
            path="projects/proj.md",
            content="content",
            branch="jurati/proj",
            write_mode="lightweight_pr",
            entry_id="proj",
            level=EscalationLevel.L1,
        )
        lock = threading.Lock()
        sha, pr_result, _ = _finish_pr_write(
            lock, "/repo", intent,
            title="t", body="b", labels=[], base="main",
            remote_url="git@gitlab.com:owner/repo.git",
            cached_candidate=None,
        )
        assert pr_result.kind == "branch"
        mock_create_pr.assert_called_once()
        args = mock_create_pr.call_args
        assert args.kwargs["candidates"] == []
```

- [ ] **Step 8: Run full test suite**

Run: `pytest -q`
Expected: All tests pass

- [ ] **Step 9: Commit**

```bash
git add src/jurati/server.py tests/test_server_write.py
git commit -m "feat(auth): rewrite server write orchestration with _finish_pr_write"
```

---

### Task 8: Privacy regression tests for auth layer

**Files:**
- Modify: `tests/test_privacy.py`

- [ ] **Step 1: Write new privacy tests**

Append to `tests/test_privacy.py`:

```python
class TestAuthPrivacy:
    def test_auth_candidate_has_no_token_field(self) -> None:
        from jurati.git.auth import AuthCandidate

        c = AuthCandidate(method="api_token", source="env_jurati", owner="o", repo="r")
        field_names = [f.name for f in c.__dataclass_fields__.values()]
        assert "token" not in field_names

    def test_pr_result_has_no_auth_field(self) -> None:
        from jurati.git.pr import PRResult

        r = PRResult(url=None, number=None, branch="b", kind="branch")
        field_names = [f.name for f in r.__dataclass_fields__.values()]
        assert "auth_method" not in field_names
        assert "auth_user" not in field_names
        assert "auth_fallback_used" not in field_names

    def test_branch_only_receipt_has_no_auth_info(self) -> None:
        from jurati.server import _write_receipt

        receipt = _write_receipt(
            entry_id="test",
            write_mode="branch_only",
            branch="jurati/test",
            commit="abc",
        )
        receipt_str = str(receipt).lower()
        assert "auth" not in receipt_str
        assert "token" not in receipt_str
        assert "fallback" not in receipt_str

    def test_status_payload_has_no_auth_section(self) -> None:
        import threading
        from datetime import UTC, datetime

        from jurati.core.index import Index
        from jurati.git.config import JuratiConfig, SyncHealth
        from jurati.server import ServerState, _state_status_payload

        index = Index()
        index.add(_make_entry())
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        state = ServerState(
            config=JuratiConfig(
                remote_url="git@github.com:org/repo.git",
                cache_dir="/tmp/test",
                main_branch="main",
                active_ref_prefix="jurati/active",
                client_slug="test",
            ),
            repo_path="/tmp/test",
            index=index,
            last_sync=now,
            sync_health=SyncHealth(last_success=now),
            write_lock=threading.Lock(),
        )
        payload = _state_status_payload(state)
        payload_str = str(payload).lower()
        assert "auth_status" not in payload_str
        assert "pr_capability" not in payload_str
```

Note: `_make_entry` is already defined in `test_privacy.py`'s module. The new tests import server helpers directly where needed.

- [ ] **Step 2: Run privacy tests**

Run: `pytest tests/test_privacy.py -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_privacy.py
git commit -m "test(auth): add privacy regression tests for auth layer"
```

---

### Task 9: Optional integration test

**Files:**
- Create: `tests/git/test_pr_integration.py`

- [ ] **Step 1: Write the integration test**

```python
"""Optional live auth tests — only run when JURATI_RUN_LIVE_AUTH_TESTS=1."""

from __future__ import annotations

import os
import subprocess

import pytest

pytestmark = pytest.mark.integration

LIVE_AUTH = os.environ.get("JURATI_RUN_LIVE_AUTH_TESTS") == "1"
GH_AVAILABLE = True
try:
    subprocess.run(
        ["gh", "--version"],
        capture_output=True, timeout=5,
    )
except (FileNotFoundError, subprocess.TimeoutExpired):
    GH_AVAILABLE = False


@pytest.mark.skipif(not LIVE_AUTH, reason="JURATI_RUN_LIVE_AUTH_TESTS not set")
@pytest.mark.skipif(not GH_AVAILABLE, reason="gh CLI not installed")
class TestLiveGhAuthToken:
    def test_gh_auth_token_returns_nonempty(self) -> None:
        result = subprocess.run(
            ["gh", "auth", "token", "--hostname", "github.com"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "GH_PROMPT_DISABLED": "1"},
        )
        assert result.returncode == 0
        token = result.stdout.strip()
        assert len(token) >= 20, f"Token too short: {len(token)} chars"
```

- [ ] **Step 2: Verify test is skipped in normal runs**

Run: `pytest tests/git/test_pr_integration.py -v`
Expected: Test skipped with reason "JURATI_RUN_LIVE_AUTH_TESTS not set"

- [ ] **Step 3: Commit**

```bash
git add tests/git/test_pr_integration.py
git commit -m "test(auth): add optional live gh auth token integration test"
```

---

### Task 10: Lint, type-check, and final verification

**Files:** None (verification only)

- [ ] **Step 1: Run ruff**

Run: `ruff check src/jurati/git/auth.py src/jurati/git/pr.py src/jurati/server.py`
Expected: No errors (fix any that appear)

- [ ] **Step 2: Run ruff format check**

Run: `ruff format --check src/jurati/git/auth.py src/jurati/git/pr.py src/jurati/server.py`
Expected: No formatting issues

- [ ] **Step 3: Run mypy**

Run: `mypy src/jurati/git/auth.py src/jurati/git/pr.py src/jurati/server.py`
Expected: No errors (fix any type issues that appear)

- [ ] **Step 4: Run full test suite**

Run: `pytest -v`
Expected: All tests pass (no regressions from existing suite)

- [ ] **Step 5: Run test coverage for auth layer**

Run: `pytest tests/git/test_auth.py tests/git/test_pr.py tests/test_server_write.py tests/test_privacy.py -v --tb=short`
Expected: All pass with clear output

- [ ] **Step 6: Final commit if any lint/type fixes were needed**

```bash
git add -u
git commit -m "chore(auth): lint and type fixes"
```
