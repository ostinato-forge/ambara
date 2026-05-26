---
doctype: ai-repo-profile
tags:
  - export-fixture
  - repo-profile
  - api
date: 2026-05-26
modified: 2026-05-26
---

# api-service

## Purpose

Small API service used by the example team to test reviewable knowledge imports.
It owns token refresh, deployment metadata, and the public health endpoint.

## Common Tasks

- Run local validation before review.
- Check [[deploy-cli]] before changing deployment metadata.
- Revalidate [[server-driven-tokens]] before changing token refresh behavior.

## Gotchas

- The service uses generated clients, so schema changes need a follow-up commit.
- Test fixtures should use synthetic hostnames, credentials, and records.
