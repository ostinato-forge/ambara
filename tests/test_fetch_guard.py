# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti
from __future__ import annotations

import socket

import pytest

from ambara.providers.fetch_guard import FetchNotAllowed, assert_url_allowed


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    # Resolve every host to a public IP so host/scheme rules are what's under test.
    monkeypatch.setattr(
        "ambara.providers.fetch_guard.socket.getaddrinfo",
        lambda host, *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/x",
        "https://api.github.com/repos/o/r/pulls",
        "https://gitlab.com/api/v4/projects/1/merge_requests",
        "https://your-org.atlassian.net/rest/api/3/search",
    ],
)
def test_allowlisted_https_hosts_pass(url: str) -> None:
    assert_url_allowed(url)  # does not raise


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/x",
        "https://evil.example.com/x",
        "https://gitlab.internal.corp/x",
        "https://notatlassian.net.evil.com/x",
    ],
)
def test_rejected_hosts_raise(url: str) -> None:
    with pytest.raises(FetchNotAllowed):
        assert_url_allowed(url)


def test_allowlisted_host_resolving_private_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ambara.providers.fetch_guard.socket.getaddrinfo",
        lambda host, *a, **k: [(2, 1, 6, "", ("10.0.0.5", 0))],
    )
    with pytest.raises(FetchNotAllowed):
        assert_url_allowed("https://gitlab.com/api/v4/x")


def test_dns_failure_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(host, *a, **k):  # type: ignore[no-untyped-def]
        raise socket.gaierror("nxdomain")

    monkeypatch.setattr("ambara.providers.fetch_guard.socket.getaddrinfo", _boom)
    with pytest.raises(FetchNotAllowed):
        assert_url_allowed("https://github.com/x")


def test_empty_resolution_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ambara.providers.fetch_guard.socket.getaddrinfo",
        lambda host, *a, **k: [],
    )
    with pytest.raises(FetchNotAllowed):
        assert_url_allowed("https://github.com/x")
