# Ambara v0.5.0 Release Notes

These notes are the source text for the first public Ambara release and launch
announcement. Keep them aligned with the verified artifact, not future plans.

## GitHub Release Notes Draft

Ambara v0.5.0 is the first public release of Ambara: reviewable project context
for AI coding agents.

Ambara gives agents a compact startup packet backed by a git knowledge repo, so
the next session can start from reviewed decisions, workflows, handoffs, and
project status before reading local code or asking the developer to re-explain
the work.

### Highlights

- MCP server with startup, context, read, search, query, record, propose,
  expire, hygiene, explain, status, and validation tools.
- CLI setup with `ambara onboard`, `ambara doctor`, `ambara startup`,
  `ambara record`, `ambara propose`, imports, static HTML export, posture
  checks, value receipts, and the local demo.
- `ambara demo` creates a no-network proof project and a `run-proof.sh` script
  that exercises startup, selective read, active record, proposal branches,
  docs import, ambient capture, posture checks, value accounting, and
  restricted-entry filtering.
- Git-backed governance for durable context: decisions, workflows, and
  principles go through review instead of silent mutation.
- Privacy boundary by design: no query logging, read receipts, participation
  tracking, presence inference, or telemetry collector.
- Local app-payload value receipts: Ambara reports compact payload size,
  deferred full bodies, suppressed repeated context, and estimated savings
  versus full eligible context.
- Apache 2.0 licensing with DCO sign-off enforcement and SPDX headers.

### Verified Before Publish

- Source tests, lint, type checks, and lock check pass.
- Wheel and source distribution build.
- The built wheel installs into a clean Python 3.12 environment.
- Installed CLI smoke passes.
- Installed `ambara demo` plus `run-proof.sh` passes.
- Pull request CI passes for Python 3.12 and 3.13, CodeQL, and DCO.
- The tag release workflow installs and smokes the built wheel before PyPI
  publish.

### Known Limits

- Ambara is not a secrets manager, observability product, agent runtime, or
  total LLM cost meter.
- Value receipts estimate Ambara app payload only, not total client billing or
  model-provider cache behavior.
- Claude Code setup and the plain file adapter are the first-class release
  paths. Other MCP clients should work through the protocol, but
  client-specific support is only claimed after that client is smoked.
- PyPI publishing requires trusted publisher setup before the `v0.5.0` tag is
  pushed.

## Short Launch Copy

AI coding agents forget the project the moment the session ends. Ambara gives
them reviewable project context backed by git.

Install it, run `ambara onboard`, and Ambara wires your project to a shared
knowledge repo. Agents start with a compact context packet, read full entries
only when needed, and write durable decisions through review instead of hidden
memory.

Try it locally with no network:

```bash
pip install ambara
ambara demo
cd ambara-demo
./run-proof.sh
```

Ambara is for project facts that should survive agent sessions, tool changes,
and team handoffs: decisions, workflows, status, constraints, and short-lived
handoffs. It does not log who read what, infer presence, or track developer
activity.

## Post-Publish Verification

After the tag workflow publishes:

```bash
python3.12 -m venv /tmp/ambara-pypi-smoke
/tmp/ambara-pypi-smoke/bin/python -m pip install ambara
/tmp/ambara-pypi-smoke/bin/ambara --version
/tmp/ambara-pypi-smoke/bin/ambara demo --path /tmp/ambara-pypi-demo --force
PATH="/tmp/ambara-pypi-smoke/bin:$PATH" /tmp/ambara-pypi-demo/run-proof.sh
```

Only create the GitHub release after the PyPI-installed proof passes.
