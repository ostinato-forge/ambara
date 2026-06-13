# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti
"""Outbound fetch allowlist for source providers (SSRF guard).

Launch posture is all-SaaS: only the known source hosts are reachable, over
HTTPS, and only when they resolve to public addresses (DNS-rebind defense).
Self-hosted support will later add an operator-configured allowlist; until then
arbitrary HTTPS is refused. Host/scheme checks are pure; the DNS lookup is the
only I/O, so this lives in the provider layer, never in core/.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_HOSTS = frozenset({"github.com", "api.github.com", "gitlab.com"})
ALLOWED_HOST_SUFFIXES = (".atlassian.net",)


class FetchNotAllowed(Exception):  # noqa: N818 - public API name is intentionally action-based
    """Raised when a fetch target is outside the launch allowlist."""


def _host_allowed(host: str) -> bool:
    host = host.lower()
    return host in ALLOWED_HOSTS or any(host.endswith(s) for s in ALLOWED_HOST_SUFFIXES)


def _resolves_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]))
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    return bool(infos)


def assert_url_allowed(url: str) -> None:
    """Raise FetchNotAllowed unless url is HTTPS, allowlisted, and resolves public."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise FetchNotAllowed(f"non-HTTPS fetch target rejected: {url!r}")
    host = parsed.hostname or ""
    if not _host_allowed(host):
        raise FetchNotAllowed(f"host not on launch allowlist: {host!r}")
    if not _resolves_public(host):
        raise FetchNotAllowed(f"host resolves to a non-public address: {host!r}")
