# Agent Operating Policy

This repository is actively built with multiple coding agents, including Claude Code and Codex. Treat these rules as the shared operating contract for agent work.

## Before Editing

- Run `git status --short` before making changes.
- Preserve unrelated local changes, even when they are in files near your task.
- Do not use `git add .`. Stage only the files that belong to the current change.
- If another agent appears to be working in the same file or feature area, keep your change narrow and call out the overlap in your handoff.

## GitHub Actions Budget

The `ostinato-forge` organization may keep a `$0` GitHub Actions budget with "stop usage when budget limit is reached" enabled. When Actions minutes are exhausted, do not raise the budget or trigger CI unless the user explicitly asks.

When landing workflow-only fixes during an exhausted budget window:

- Use a commit message ending with `[skip ci]`.
- Prefer direct workflow-only commits over broad mixed commits.
- Do not push speculative workflow changes just to see what happens.

## Workflow Defaults

For CI workflows, prefer:

- `concurrency.cancel-in-progress: true`.
- Conservative `paths-ignore` for docs-only changes when branch protection allows it.
- Browser, end-to-end, release, and full smoke jobs on `workflow_dispatch`, `push` to `main`, or explicit release events rather than every pull request.
- Matrix jobs only where the matrix result matters; run expensive build or smoke steps on one representative version.
- Pinned action SHAs unless the repo has intentionally chosen version tags.

## Validation

Prefer local checks before pushing. For workflow edits, validate at least:

- YAML parsing for changed workflow files.
- `git diff --check`.
- Any repo-specific lint or test command that is cheap and relevant.

If `actionlint` is available, run it on changed workflow files. If it is not installed, say so in the handoff.

## Handoff

End with:

- What changed.
- What was validated.
- What was not run and why.
- Whether unrelated local changes were present.
- Whether pushing would trigger Actions or should use `[skip ci]`.
