# syntax=docker/dockerfile:1
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="Ambara" \
      org.opencontainers.image.description="Local Ambara public-preview CLI image" \
      org.opencontainers.image.source="https://github.com/ostinato-forge/ambara" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    AMBARA_CACHE_DIR=/home/ambara/.cache/ambara

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 ambara \
    && useradd --system --uid 10001 --gid ambara \
        --create-home --home-dir /home/ambara ambara

WORKDIR /opt/ambara
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && python -m pip check \
    && rm -rf /opt/ambara

USER ambara
WORKDIR /workspace

ENTRYPOINT ["ambara"]
CMD ["--help"]
