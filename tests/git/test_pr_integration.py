"""Optional live auth tests — only run when AMBARA_RUN_LIVE_AUTH_TESTS=1."""

from __future__ import annotations

import os
import subprocess

import pytest

pytestmark = pytest.mark.integration

LIVE_AUTH = os.environ.get("AMBARA_RUN_LIVE_AUTH_TESTS") == "1"
GH_AVAILABLE = True
try:
    subprocess.run(
        ["gh", "--version"],
        capture_output=True,
        timeout=5,
    )
except (FileNotFoundError, subprocess.TimeoutExpired):
    GH_AVAILABLE = False


@pytest.mark.skipif(not LIVE_AUTH, reason="AMBARA_RUN_LIVE_AUTH_TESTS not set")
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
