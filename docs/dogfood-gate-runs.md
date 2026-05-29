# Team Loop Test Gate Runs

Tracking issues:

- https://github.com/ostinato-forge/jurati/issues/90
- https://github.com/ostinato-forge/jurati/issues/91

This file records durable evidence for the team-loop test gate. Disposable
command logs and generated repos can remain in `/tmp`, but each gate run should
leave a short repo-owned summary here.

## 2026-05-29: Fresh-Clone Teammate Adoption Smoke

Status: repo-discovered teammate adoption gate passed. This closes the
remaining #91 evidence gap: a fresh clone can verify repo-owned setup with one
documented command and no personal remote env.

Scope:

- Source-tree script: `scripts/pre-release-teammate-clone-smoke.sh`
- Source-tree command:
  `JURATI_BIN=.venv/bin/jurati scripts/pre-release-teammate-clone-smoke.sh --keep`
- Source-tree evidence: `/tmp/jurati-teammate-clone.tpqNry/evidence.md`
- Installed-package script: `scripts/pre-release-installed-package-smoke.sh`
- Installed-package command:
  `PYTHON_BIN=python3 scripts/pre-release-installed-package-smoke.sh --keep`
- Installed-package evidence: `/tmp/jurati-installed-smoke.vbrX3L/evidence.md`
- Installed-package fresh-clone evidence:
  `/tmp/jurati-installed-smoke.vbrX3L/teammate-clone-smoke/evidence.md`

What passed:

- The first user ran guided onboarding with a local knowledge remote and
  project repo.
- The project committed only repo-owned setup:
  - `.jurati/config.yaml`
  - `CLAUDE.md`
  - `.claude/settings.json`
  - `.mcp.json`
- A simulated teammate cloned the project into an isolated working tree.
- The teammate shell used an isolated `HOME`, an isolated cache, and an empty
  `JURATI_KNOWLEDGE_REMOTE`.
- The one documented command passed from the fresh clone:
  `jurati doctor --team --check-startup --strict`
- Doctor discovered the knowledge remote from `.jurati/config.yaml`, reported
  project MCP config present, startup contract present, read-only tools
  approved, team ready, and ready for `jurati serve`.
- `serve --check` also discovered the repo-owned remote without a personal
  remote env var.
- The installed-package smoke built a wheel, installed it into a clean virtual
  environment, ran the existing first-user trial, and then ran the fresh-clone
  teammate smoke with the installed `jurati` binary.
- The team-readiness privacy boundary now says:
  `repo readiness only; no teammate install/presence tracking`.

Finding fixed during the run:

- The first source-tree smoke found a harness bug where a relative
  `JURATI_BIN=.venv/bin/jurati` broke after the script changed into a generated
  project directory. The script now resolves relative executable paths to
  absolute paths before entering generated repos.
- The second source-tree smoke found that a disposable bare project remote with
  default `master` HEAD produced a clone with no checkout. The harness now
  initializes bare remotes with `main`, matching the project branch.

Gate decision:

- The #91 acceptance criteria are covered by source-tree and installed-package
  evidence.
- Future adoption work should start from new setup friction found in real use,
  not keep #91 open.

## 2026-05-29: Active Context Connected-Agent Gate

Status: connected-agent active-context gate passed. This closes the remaining
#90 evidence gap after the earlier active-refs-disabled single-repo and
multi-repo passes.

Scope:

- Active repo source: `/home/eparenti/claude/repos/jurati`
- Script: `scripts/pre-release-active-context-connected-agent.sh`
- Command: `PYTHON_BIN=.venv/bin/python scripts/pre-release-active-context-connected-agent.sh --keep`
- Gate directory: `/tmp/jurati-active-context-gate.X4y4JF`
- Evidence: `/tmp/jurati-active-context-gate.X4y4JF/evidence.md`
- Claude stream: `/tmp/jurati-active-context-gate.X4y4JF/claude-stream.jsonl`
- Score: `/tmp/jurati-active-context-gate.X4y4JF/claude-score.json`
- Connected-agent session: `ffe7dd3a-cd1a-4213-b36f-4bc5c2ae0480`

What passed:

- The disposable project opted into active refs through repo-owned
  `.jurati/config.yaml` policy:
  - `active_refs.enabled: true`
  - `active_refs.ttl_hours: 6`
- `doctor --check-startup --team` reported:
  - project MCP config present
  - startup contract present
  - read and write tools auto-approved
  - active refs policy enabled
  - active refs TTL 6h
  - team ready
- `serve --check` passed against the generated project-local MCP config.
- A simulated teammate seeded active context before the connected-agent run.
- The CLI startup packet included the seeded active handoff with
  `availability=fresh` and `action=proceed`.
- Claude Code connected to the project-local MCP server and used this tool
  sequence:
  1. `startup`
  2. `record`
- The connected agent recorded a new active handoff, producing a second active
  ref in the disposable knowledge remote.
- The visible developer-facing reply was:
  `Handoff saved: Alice confirmed 900-second refresh window and server-driven rotation for checkout sessions, Bob handles release docs.`
- The scorer found no visible leaks of entry IDs, ref paths, branch names,
  expiry mechanics, raw MCP JSON, tool names, or knowledge-repo chores.
- Claude Code reported total cost `$0.1947747`.

Finding fixed during the run:

- The first connected-agent attempt functionally succeeded but visibly
  pre-announced the startup/tool workflow. The gate treated that as a terminal
  trust failure, not a harmless wording issue.
- The compact Claude template now explicitly requires startup and write tools
  to run silently and says the first visible reply should be the final
  work-focused answer.
- The connected-agent scorer now fails on visible mentions of startup, record,
  tool calls, entry IDs, refs, branches, expiry mechanics, raw JSON, or
  knowledge-repo chores.

Gate decision:

- The active-refs-disabled connected-agent passes, import/curation pass,
  scripted privacy smoke, and this active-refs-enabled connected-agent pass now
  cover the #90 acceptance criteria.
- Future active-coordination depth should continue under #93, not keep #90
  open.

## 2026-05-26: Active Context Privacy Gate

Status: focused scripted privacy gate passed; connected-agent active-context
run remains required before closing #90.

Scope:

- Active repo source: `/home/eparenti/claude/repos/jurati`
- Script: `scripts/pre-release-active-context-privacy-smoke.sh`
- Command: `uv run bash scripts/pre-release-active-context-privacy-smoke.sh`

What passed:

- Active context writes are rejected when repo policy has not opted in.
- Active refs are not overlaid into the index when active refs are disabled.
- Active refs are overlaid only when active refs are explicitly enabled.
- Repo-owned active-ref enablement and TTL flow into generated project MCP
  config.
- Invalid repo TTL policy is rejected.
- Active writes default expiry from repo TTL and reject expiry beyond policy.
- Active writes reject content that requires content-policy review and do not
  echo the unsafe source text.
- Startup context excludes expired active entries and restricted active entries.

Finding:

- This proves the code-level active-context privacy contract. The remaining #90
  gap is a connected-agent pass with active refs enabled by repo policy, scored
  on both behavior and terminal trust: no entry IDs, ref paths, branch names,
  expiry mechanics, raw MCP JSON, or knowledge-repo chores in normal user
  output.

## 2026-05-26: Import And Curation Gate

Status: scripted import/curation harness passed; connected-agent startup and
planning pass completed with active refs disabled.

Scope:

- Active repo source: `/home/eparenti/claude/repos/jurati`
- Multi-repo evidence: `/tmp/jurati-multi-repo-dogfood.v3JeIN/evidence.md`
- Import output: `/tmp/jurati-multi-repo-dogfood.v3JeIN/import-output.txt`
- Curation output: `/tmp/jurati-multi-repo-dogfood.v3JeIN/curation-output.txt`
- Tool sequence evidence:
  `/tmp/jurati-multi-repo-dogfood.v3JeIN/multi-repo-tool-sequence.jsonl`
- PR signal fixture: `/tmp/jurati-multi-repo-dogfood.v3JeIN/pr-signals.json`
- Connected-agent evidence: Claude Code session
  `b7f43360-ed1e-4e75-ad31-926ef441228b`
- Connected-agent MCP server: `jurati-235c7204`

What passed:

- Existing upstream ADR-style docs imported through `import-docs --mode adr`
  with a dry run and review branch:
  `jurati/import-docs-auth-contract`.
- Existing downstream team docs imported through `import-docs --mode docs`
  with a dry run and review branch:
  `jurati/import-docs-web-context`.
- Simulated human review accepted the imported entries as active knowledge
  before the downstream agent started.
- `jurati validate` accepted all 3 imported knowledge entries.
- `install-claude-md` installed the startup contract and Claude permissions.
- `mcp-config --write-project` wrote a hash-named project MCP server using the
  exact Jurati binary under test.
- `doctor --check-startup` reported:
  - `sync(): ok (3 entries indexed)`
  - `context(): ok (0 active, 3 recent entries available)`
  - `Ready for jurati serve: yes`
- `serve --check` passed for the generated downstream repo.
- Weekly hygiene with `JURATI_CURATION_WRITE=true` wrote review branch
  `jurati/curation/dogfood-import-loop` and marked imported durable entries
  for revalidation:
  - `decisions/shared-auth-contract-is-owned-upstream.md`
  - `projects/multi-repo-auth-coordination-workflow.md`
  - `projects/web-app-auth-session-work.md`
- The scripted handler sequence called `sync()`, then goal-only `context()`,
  then path-specific `context()`, then `query()`.
- The scripted handler sequence recorded `active_refs_enabled: false`.
- Goal-only startup context surfaced the imported entries:
  - `Shared auth contract is owned upstream`
  - `Web app auth session work`
  - `Multi-repo auth coordination workflow`
- Goal-only startup context returned curation advisories for all 3 imported
  entries after merged upstream PR `#8`.
- Path-specific context returned `pause` guidance for
  `contracts/auth/session.json` and cited `ostinato-dogfood/auth-api`.
- A real Claude Code connected-agent pass completed successfully:
  - First tool uses: `mcp__jurati-235c7204__sync`, then
    `mcp__jurati-235c7204__context`.
  - Stream evidence did not show local file, git, or shell tool use before
    Jurati context.
  - Context surfaced imported knowledge, two upstream PR signals, and the
    curation advisory block.
  - The agent identified the intended stale-contract blocker: the local web
    app still had `refreshWindowSeconds: 300`, while upstream context said the
    merged contract moved to `900` and added `rotationPolicy: server-driven`.
  - Total reported Claude Code cost: `$0.2316111`.

Findings:

- Import-seeded context is enough to orient the downstream agent before local
  exploration.
- The curation loop is useful in-session: the merged upstream signal caused the
  agent to treat imported durable entries as needing verification before use.
- The connected agent tried to inspect the sibling `auth-api` repo after the
  required Jurati startup calls and received one workspace-boundary permission
  denial. That is not a Jurati startup-order failure, but it is useful product
  evidence: multi-repo pilots should either add sibling repos to the client
  workspace explicitly or expect the agent to ask the developer for the
  upstream contract source.
- The in-sandbox scripted handler attempt again hung in the local Codex
  execution environment, while the same harness passed outside the sandbox.
  Continue treating this as an execution-environment caveat, not a Jurati
  product failure.

Remaining gate work:

- Decide whether the active-refs-disabled evidence is enough to defer the
  explicit active-refs-enabled policy run.
- Decide whether multi-repo connected-agent instructions should document
  sibling repo access with `--add-dir` for pilots that expect local upstream
  inspection.

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
