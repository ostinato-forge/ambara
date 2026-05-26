---
doctype: ai-error-pattern
tags:
  - export-fixture
  - error
  - ci
date: 2026-05-26
modified: 2026-05-26
---

# CI Cache Loop

## Symptom

The package cache restores successfully, but the same dependency install step
runs on every workflow attempt.

## Cause

The workflow key changes on generated lockfile timestamps instead of dependency
content.

## Fix

Hash the canonical lockfile only, then rerun the workflow.
