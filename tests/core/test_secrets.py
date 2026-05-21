"""Tests for jurati.core.secrets — secret pattern detection."""

from __future__ import annotations

import re

import pytest

from jurati.core.secrets import scan_secrets


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
