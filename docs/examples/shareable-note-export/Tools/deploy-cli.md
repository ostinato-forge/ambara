---
doctype: ai-tool-note
tags:
  - export-fixture
  - tool
  - deploy
aliases: Deploy Tool
date: 2026-05-26
modified: 2026-05-26
---

# deploy-cli

## Purpose

Example deployment helper used by the team before opening a deployment PR.

## Commands

```bash
deploy-cli plan --service api-service
deploy-cli apply --service api-service --environment staging
```

## Quirks

- Always run `deploy-cli plan` before `apply`.
- Use synthetic service names in tests.
