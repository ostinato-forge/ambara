# Dogfood Gate Runs

Tracking issue: https://github.com/ostinato-forge/jurati/issues/90

This file records durable evidence for the team-loop dogfood gate. Disposable
command logs and generated repos can remain in `/tmp`, but each gate run should
leave a short repo-owned summary here.

## 2026-05-25: Gate Kickoff

Status: repeatable harnesses and active-refs-disabled connected-agent passes
passed; active-refs-enabled policy run still requires an explicit repo policy
decision.

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
- Single-repo connected-agent stream:
  `/tmp/jurati-single-repo-dogfood.9Wkrl4/connected-agent-stream.jsonl`
- Multi-repo connected-agent stream:
  `/tmp/jurati-multi-repo-dogfood.KGSjyr/connected-agent-stream.jsonl`

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
- A real Claude Code single-repo connected-agent pass completed successfully:
  - Session: `28d46868-31aa-463c-ae51-2731ea746ca1`
  - MCP server: `jurati-e2635254`
  - First tool uses: `mcp__jurati-e2635254__sync`, then
    `mcp__jurati-e2635254__context`
  - Stream evidence did not show local file, git, or shell tool use before
    Jurati context.
  - Final response said the agent followed `sync -> context -> planning`
    rather than local git/file exploration.
  - Total reported Claude Code cost: `$0.1583493`
- A real Claude Code multi-repo connected-agent pass completed successfully:
  - Session: `8e2f015e-963f-4ffb-8324-772bba4a47f4`
  - MCP server: `jurati-3d021062`
  - First tool uses: `mcp__jurati-3d021062__sync`, then
    `mcp__jurati-3d021062__context`
  - Stream evidence did not show local file, git, or shell tool use before
    Jurati context.
  - The context surfaced auth-api PR `#7` before local work.
  - The agent said upstream auth-api work should alter the frontend plan,
    accounting for `refreshWindowSeconds` changing from `300` to `900` and
    the incoming `rotationPolicy: server-driven` field.
  - Total reported Claude Code cost: `$0.163263`

Findings:

- The older pre-release dogfood harness still used `active_refs_enabled=True`
  inside the in-process handler fixture. The gate kickoff corrected this so the
  first pass now proves the privacy-default path with active refs disabled.
- The Codex sandbox used for normal shell commands hangs on
  `anyio.to_thread.run_sync`. A tiny outside-sandbox smoke passed immediately,
  and the dogfood harnesses passed outside the sandbox. Treat this as a local
  execution-environment caveat, not a Jurati product failure.
- The connected-agent commands used `--strict-mcp-config`, project-only setting
  sources, and `--allowedTools` limited to Jurati `sync`, `context`, and
  `query`. This isolated the startup-order and coordination behavior. A later
  broader run can test the same behavior with normal local read/shell tools
  explicitly allowed.

Remaining gate work:

- Decide whether the first pass justifies a second run with active refs enabled
  by explicit repo policy.
- Decide whether the gate needs a broader connected-agent pass with normal local
  read/shell tools explicitly allowed, now that the isolated startup-order pass
  is green.
- Convert any real-client failures into focused Phase 1, 2, 3, or 4 issues.
