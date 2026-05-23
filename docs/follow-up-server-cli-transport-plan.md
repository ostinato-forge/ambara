# Server, CLI, and Transport Follow-Up Plan

This plan tracks the two review findings that are worth fixing, but should not be
mixed into behavior hardening changes:

- Split the large `server.py` and `cli.py` modules into smaller units.
- Revisit the custom stdio transport and blocking-work shim without regressing
  the known MCP startup behavior.

## Goals

- Preserve the current MCP tool contract, CLI command names, and user-facing
  output.
- Keep `core/` pure and deterministic.
- Keep git, network, and filesystem effects outside `core/`.
- Land changes in small PRs with no product behavior drift.

## Non-Goals

- Do not redesign the MCP protocol surface.
- Do not change onboarding defaults.
- Do not remove the custom transport until replacement behavior is verified
  against the same smoke scenarios that motivated it.

## Phase 1: Server Module Split

Create a `src/jurati/server/` package and move code without changing behavior:

- `server/state.py`: `ServerState`, `SyncHealth`, lifespan setup, state helpers.
- `server/transport.py`: `run_stdio()`, custom stdio transport, queue polling.
- `server/rendering.py`: entry formatting, search formatting, context payloads.
- `server/receipts.py`: write/expire receipts, agent guidance, write-path errors.
- `server/tools_read.py`: `explain`, `status`, `hygiene`, `query`, `context`,
  `search`, `read`, `list_entries`, `validate`, `sync`.
- `server/tools_write.py`: `record`, `propose`, `expire`, PR write orchestration.
- Keep `src/jurati/server.py` as a compatibility facade that exports `mcp` and
  `run_stdio` until imports are migrated.

Validation:

- `uv run pytest tests/test_server.py tests/test_server_write.py tests/test_mcp_smoke.py -q -p no:cacheprovider`
- `uv run ruff check .`
- `uv run mypy src`

## Phase 2: CLI Module Split

Create a `src/jurati/cli/` package and move commands by ownership:

- `cli/main.py`: Click group and command registration.
- `cli/scaffold.py`: starter templates, scaffold creation, validation helpers.
- `cli/onboard.py`: quickstart, onboard, MCP config generation/writes.
- `cli/doctor.py`: diagnostics, startup probe, config collision checks.
- `cli/hooks.py`: hook installation, capture, active, flush commands.
- `cli/read_model.py`: read-model rebuild/query commands.
- Keep `src/jurati/cli.py` as the console-script facade exporting `main`.

Validation:

- `uv run pytest tests/test_cli.py -q -p no:cacheprovider`
- Run `jurati --help`, `jurati doctor --help`, and `jurati onboard --help` from
  an editable install.

## Phase 3: Transport Replacement Spike

Before changing transport internals, capture the current behavior with tests:

- A stdio smoke test that initializes the MCP server and calls `explain()`.
- A startup-check test that exercises `serve --check`.
- A regression test for the historical stdin hang in this environment.

Then evaluate replacement options:

1. Keep the custom reader thread, but replace `_poll_queue()` with an AnyIO
   event signaled from the worker thread.
2. Use a dedicated `ThreadPoolExecutor` for blocking git work instead of one
   ad hoc daemon thread per call.
3. Re-test the upstream MCP/AnyIO stdio transport. Remove the custom transport
   only if the historical hang cannot be reproduced.

Acceptance criteria:

- `tests/test_mcp_smoke.py` passes repeatedly.
- `jurati serve --check` still reports the same preflight behavior.
- A real Claude Code startup using the generated `.mcp.json` connects and can
  call `sync()` and `context()`.
- No query logging, read receipts, or new telemetry are introduced.

## Suggested PR Order

1. Server module split only.
2. CLI module split only.
3. Transport test harness.
4. Transport implementation cleanup.
