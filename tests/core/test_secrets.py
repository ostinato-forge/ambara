# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for ambara.core.secrets — secret pattern detection."""

from __future__ import annotations

import re

import pytest

from ambara.core.secrets import scan_secrets


def _synthetic_secret(*parts: str) -> str:
    """Build token-shaped fixtures without storing literal secrets in git."""
    return "".join(parts)


class TestSecretPatterns:
    @pytest.mark.parametrize(
        "text",
        [
            "sk-abc123def456xyz",
            "pk-abcdef123456xyz",
            "api_key_abcdef123456",
            "api-key-abcdef123456",
            "apikey_abcdef123456",
        ],
    )
    def test_detects_api_key_patterns(self, text: str) -> None:
        assert scan_secrets(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "ghp_ABCDEFghijkl1234567890abcdefghij",
            "ghp_abcdefghijklmnopqrstuvwxyz123456",
        ],
    )
    def test_detects_github_classic_tokens(self, text: str) -> None:
        assert scan_secrets(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "gho_ABCDEFghijkl1234567890abcdefghij",
            "gho_abcdefghijklmnopqrstuvwxyz123456",
        ],
    )
    def test_detects_github_oauth_tokens(self, text: str) -> None:
        assert scan_secrets(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            _synthetic_secret("glpat", "-ABCDEF1234567890abcd"),
            _synthetic_secret("gloas", "-ABCDEF1234567890abcd"),
            _synthetic_secret("gldt", "-ABCDEF1234567890abcd"),
            _synthetic_secret("glrt", "-ABCDEF1234567890abcd"),
            _synthetic_secret("glrtr", "-ABCDEF1234567890abcd"),
            _synthetic_secret("glcbt", "-ABCDEF1234567890abcd"),
            _synthetic_secret("glptt", "-0123456789abcdef0123456789abcdef01234567"),
            _synthetic_secret("glft", "-ABCDEF1234567890abcd"),
            _synthetic_secret("glimt", "-ABCDEF1234567890abcd"),
            _synthetic_secret("glagent", "-ABCDEF1234567890abcd"),
            _synthetic_secret("glwt", "-ABCDEF1234567890abcd"),
            _synthetic_secret("glsoat", "-ABCDEF1234567890abcd"),
            _synthetic_secret("glffct", "-ABCDEF1234567890abcd"),
            _synthetic_secret("GITLAB_TOKEN=glpat", "-ABCDEF1234567890abcd"),
        ],
    )
    def test_detects_gitlab_tokens(self, text: str) -> None:
        assert scan_secrets(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            _synthetic_secret("xoxb", "-123456789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx"),
            _synthetic_secret("xoxp", "-123456789012-123456789012-abcdefghijkl"),
            _synthetic_secret("xapp", "-1-A1234567890-abcdef1234567890abcdef"),
            _synthetic_secret("xwfp", "-abcdef1234567890abcdef"),
            _synthetic_secret("xoxe", ".xoxb-1-AbCdEfGhIjKlMnOpQrStUvWx"),
            _synthetic_secret("xoxe", "-1-AbCdEfGhIjKlMnOpQrStUvWx"),
        ],
    )
    def test_detects_slack_tokens(self, text: str) -> None:
        assert scan_secrets(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "password=hunter2",
            "password: hunter2",
            "PASSWORD = secretvalue",
        ],
    )
    def test_detects_password_assignments(self, text: str) -> None:
        assert scan_secrets(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "token = abcdefghijklmnop1234",
            "token=abcdefghijklmnop1234",
            "TOKEN: abcdefghijklmnop1234",
        ],
    )
    def test_detects_token_assignments(self, text: str) -> None:
        assert scan_secrets(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "secret = abcdefgh",
            "secret=12345678",
            "SECRET: mysecret1",
        ],
    )
    def test_detects_secret_assignments(self, text: str) -> None:
        assert scan_secrets(text) is True

    def test_detects_private_key_header(self) -> None:
        assert scan_secrets("-----BEGIN PRIVATE KEY-----") is True
        assert scan_secrets("-----BEGIN RSA PRIVATE KEY-----") is True

    @pytest.mark.parametrize(
        "text",
        [
            "postgresql://user:pass@host/db",
            "mysql://admin:secret@localhost:3306/app",
            "redis://default:pw@cache.internal:6379",
        ],
    )
    def test_detects_uri_credentials(self, text: str) -> None:
        assert scan_secrets(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "AKIAIOSFODNN7EXAMPLE",
            "ASIAIOSFODNN7EXAMPLE",
            "sk_live_abcdefghijklmnopqrstuvwx",
            "AIzaSyB_abcdefghijklmnopqrstuvwxyz12345",
            "github_pat_" + "A" * 22 + "_" + "B" * 59,
        ],
    )
    def test_detects_policy_backed_secret_patterns(self, text: str) -> None:
        assert scan_secrets(text) is True


class TestNonSecrets:
    @pytest.mark.parametrize(
        "text",
        [
            "This is a normal sentence about authentication.",
            "The password policy requires 12 characters.",
            "See the API documentation for details.",
            "token count: 5",
            "secret sauce recipe",
            "postgresql pool at 20 max connections",
            "https://example.com/path",
        ],
    )
    def test_normal_prose_not_flagged(self, text: str) -> None:
        assert scan_secrets(text) is False


class TestExtraPatterns:
    def test_custom_pattern_detected(self) -> None:
        custom = [re.compile(r"AKID[A-Z0-9]{16,}")]
        assert scan_secrets("AKIDEXAMPLEKEYVALUE1", extra_patterns=custom) is True

    def test_custom_pattern_no_false_positive(self) -> None:
        custom = [re.compile(r"AKID[A-Z0-9]{16,}")]
        assert scan_secrets("normal text", extra_patterns=custom) is False

    def test_none_extra_patterns(self) -> None:
        assert scan_secrets("ghp_ABCDEFghijkl1234567890abcdefghij", extra_patterns=None) is True
