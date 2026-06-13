# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti
"""Outbound fetch allowlist for source providers (SSRF guard).

Launch posture is all-SaaS: only the known source hosts are reachable, over
HTTPS, and a best-effort pre-flight check rejects hosts that resolve to
non-public addresses. This is NOT a connect-time DNS-rebind defense -- the HTTP
client re-resolves when it connects, so a rebind TOCTOU remains; for the
all-SaaS allowlist (github.com / gitlab.com / *.atlassian.net) that residual
risk is accepted. Real connect-time IP pinning is deferred until self-hosted
support lands.

`.atlassian.net` is an OPEN suffix: any Atlassian tenant matches it. Matching
grants TLS reachability for an operator-configured base URL, NOT trust in the
content -- provider response bodies are sanitized downstream by sources.safety,
and providers disable redirect-following. Host/scheme checks are pure; the DNS
lookup is the only I/O, so this lives in the provider layer, never in core/.
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
    if not infos:
        return False
    for info in infos:
        raw = str(info[4][0]).split("%")[0]  # strip IPv6 zone id (e.g. fe80::1%eth0)
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return False  # fail closed on anything we can't parse
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped  # unwrap ::ffff:10.0.0.5 style addresses
        if not ip.is_global:  # rejects private/loopback/link-local/reserved/multicast/unspecified
            return False
    return True


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
