# Dogfood Gate Runs

Tracking issue: https://github.com/ostinato-forge/jurati/issues/90

This file records durable evidence for the team-loop dogfood gate. Disposable
command logs and generated repos can remain in `/tmp`, but each gate run should
leave a short repo-owned summary here.

## 2026-05-25: Gate Kickoff

Status: repeatable harnesses passed with active refs disabled; real connected
agent run still required.

Scope:

- Active repo source: `/home/eparenti/claude/repos/jurati`
- Single-repo evidence: `/tmp/jurati-single-repo-dogfood.9Wkrl4/evidence.md`
- Single-repo tool sequence:
  `/tmp/jurati-single-repo-dogfood.9Wkrl4/first-agent-tool-sequence.jsonl`
- Multi-repo evidence: `/tmp/jurati-multi-repo-dogfood.KGSjyr/evidence.md`
- Multi-repo tool sequence:
  `/tmp/jurati-multi-repo-dogfood.KGSjyr/multi-repo-tool-sequence.jsonl`
- Multi-repo PR signal fixture:
  `/tmp/jurati-multi-repo-dogfood.KGSjyr/pr-signals.json`

What passed:

- `jurati validate` accepted all seeded knowledge entries.
- `install-claude-md` installed the startup contract and Claude permissions.
- `mcp-config --write-project` wrote hash-named project MCP servers.
- `doctor --check-startup` reported:
  - `CLAUDE.md startup contract: yes`
  - `.claude/settings.json: yes`
  - `read-only tools auto-approved: yes`
  - ready for `jurati serve`
- `serve --check` passed for the generated project repos.
- The scripted handler sequence called `sync()`, then `context()`, then
  `query()` before any local-only exploration.
- The scripted handler sequence recorded `active_refs_enabled: false`.
- The single-repo run surfaced these context titles:
  - `Jurati Workstream 3 status`
  - `Pre-release dogfood loop`
  - `Pre-release confidence before features`
- The multi-repo run surfaced an upstream PR signal from
  `ostinato-dogfood/auth-api` while working in `ostinato-dogfood/web-app`.
- Goal-only multi-repo context returned a `revise` coordination effect.
- Path-specific multi-repo context returned a `pause` coordination effect for
  `contracts/auth/session.json`.
- The multi-repo privacy boundary stated that only configured repos and
  configured-label PRs are checked, and that comments, chats, editor activity,
  and read activity are not mined.

Findings:

- The older pre-release dogfood harness still used `active_refs_enabled=True`
  inside the in-process handler fixture. The gate kickoff corrected this so the
  first pass now proves the privacy-default path with active refs disabled.
- The Codex sandbox used for normal shell commands hangs on
  `anyio.to_thread.run_sync`. A tiny outside-sandbox smoke passed immediately,
  and the dogfood harnesses passed outside the sandbox. Treat this as a local
  execution-environment caveat, not a Jurati product failure.

Remaining gate work:

- Run a real connected-agent pass from the generated single-repo project and
  confirm the agent calls `sync()` and `context()` before local exploration.
- Run a real connected-agent pass from the generated downstream repo and confirm
  the agent notices the upstream auth-contract signal before editing.
- Decide whether the first pass justifies a second run with active refs enabled
  by explicit repo policy.
- Convert any real-client failures into focused Phase 1, 2, 3, or 4 issues.
