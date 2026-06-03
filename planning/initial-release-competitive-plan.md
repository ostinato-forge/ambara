# Ambara Initial Release Competitive Plan

Status: release-shaping plan; build scope superseded by `complete-build-plan.md`
Updated: 2026-06-03

## Release Thesis

Ship Ambara as reviewable project context for AI coding agents, not as another
generic memory bucket.

The market already has plenty of "persistent memory for agents" products. The
release should lean into the places where Ambara is meaningfully different:

- Context lives in a normal git repo, so teams get review, history, rollback,
  and provenance without trusting a new opaque memory store.
- Durable knowledge is explicitly promoted through `record()` and `propose()`
  instead of silently auto-capturing everything a developer does.
- Agents receive compact startup packets first, then use `read()` or
  `read_many()` only when they directly rely on source text.
- Privacy and content safety are product gates, not enterprise add-ons.
- Value is shown as restraint: small payloads, deferred bodies, suppressed
  noise, and local app-payload savings receipts.

The best initial product is therefore:

> A governed context layer that makes coding agents start from reviewed team
> knowledge, spend fewer tokens rediscovering it, and leave an auditable trail
> only when the developer explicitly asks them to.

## Competitive Read

### memctl

What they teach us:

- Users understand "one project brain across agents" quickly.
- Setup needs to feel like one command that writes the right MCP config.
- Session handoff and conflict prevention are easy to understand as practical
  value, not abstract memory theory.
- Their discontinuation note is useful signal: built-in memories now cover
  part of the generic-memory space, so Ambara should not compete there head-on.

Ambara response:

- Keep the "shared context across agents" story, but lead with reviewed git
  governance and explicit capture.
- Add a short release demo around two sessions: first agent records a handoff,
  second agent starts with `startup()` and continues correctly.
- Keep session activity private. Do not add activity logs or read receipts for
  the first release.

Useful source areas:

- `src/ambara/server.py`: `startup`, `record`, `propose`, `sync`
- `src/ambara/server_read.py`: startup/context packet shape
- `src/ambara/server_write.py`: write-path corrections and advisories
- `tests/test_mcp_smoke.py`: local end-to-end fixture to turn into demo proof

### ContextStream

What they teach us:

- "Persistent memory, semantic search, and knowledge graphs" is the broad
  category language users expect.
- A setup wizard, dry run, generated rules, and multi-client MCP instructions
  reduce adoption friction.
- A compact toolset or router mode is a good response to MCP tool overload.
- Their "decisions, timeline, summary" surface is easier to browse than raw
  memory CRUD.

Ambara response:

- Keep Ambara's tool list, but make `startup()` the recommended first tool in
  every doc and client setup.
- Add a release doc section titled "Why `startup()` first" with concrete output.
- Add one visible "browse your context" path using `ambara html` so users can
  inspect what agents are seeing without learning MCP.
- Defer knowledge-graph claims. Ambara has links and indexing, but the release
  should not imply ContextStream-style code graph impact analysis yet.

Useful source areas:

- `src/ambara/cli_install.py`: generated startup contract and MCP config
- `src/ambara/cli.py`: `onboard`, `doctor --check-startup`, `html`
- `src/ambara/static_html.py`: browser output
- `tests/test_cli.py`: onboarding and startup diagnostics

### GitHub Copilot Memory

What they teach us:

- Platform-native memory is the biggest adoption threat.
- Repo-level facts and personal preferences are the default mental model.
- Automatic validation and 28-day expiry are strong stale-context answers.
- Cross-surface reuse inside one platform will be hard to beat on convenience.

Ambara response:

- Do not claim to replace Copilot Memory. Position Ambara as the reviewable
  source of truth that works across Copilot, Claude Code, Cursor, Codex, and
  file-based agents.
- Make expiry and curation prominent. "Ambara does not keep stale facts forever"
  should be part of the first README pass.
- Add a release checklist item that startup packets say when context is stale
  or unavailable, and agents must stop rather than proceed from local-only
  assumptions.

Useful source areas:

- `src/ambara/core/context_compiler.py`: verdict and planning actions
- `src/ambara/core/hygiene.py`: lifecycle summaries
- `src/ambara/server_curation.py`: quiet curation advisories
- `src/ambara/cli.py`: `doctor --check-startup`, disabled/unavailable flows

### OpenMemory / Mem0

What they teach us:

- Typed memories, project matching, browse/manage, and access visibility are
  simple product concepts.
- Auto-capture is attractive, but it creates a trust and privacy surface Ambara
  should avoid at launch.

Ambara response:

- Use Ambara entry types as the typed-memory story: active, project, decision,
  workflow, principle.
- Make the static context browser good enough for browsing and inspection.
- Keep capture explicit. If ambient commit capture is mentioned, frame it as an
  optional hook for pending local drafts, not silent durable memory.

Useful source areas:

- `src/ambara/core/schema.py`: entry types, levels, visibility, sensitivity
- `src/ambara/capture/*`: pending ambient capture pipeline
- `src/ambara/action/*`: GitHub Action capture entrypoint
- `src/ambara/static_html.py`: browse/manage surface

### Memstate

What they teach us:

- Structured, versioned memory and conflict detection are strong claims.
- Public benchmark methodology makes memory quality more credible.
- "Compressed first, drill into full content later" matches Ambara's current
  architecture and should be explained better.

Ambara response:

- Do not build their keypath store before release. Ambara's structured
  Markdown frontmatter is enough for v0.5.0.
- Add one public, reproducible golden scenario:
  `two-agent-handoff-saves-rediscovery`.
- Publish release proof as a local script or documented command sequence:
  onboard, save, startup, selective read, value summary, privacy smoke.
- Treat conflict detection as near-term follow-up: write advisories already
  find duplicates and stale proposals; expose that more clearly before adding
  a new model.

Useful source areas:

- `tests/test_context_token_efficiency.py`: context compression and coverage
- `src/ambara/core/context_accounting.py`: value accounting
- `src/ambara/server_value.py`: local ledger and feedback
- `src/ambara/core/changes.py`: write planning and duplicate advisories

### Cursor, Windsurf, Claude Code Built-Ins

What they teach us:

- Built-in memories and rules are now expected. Users will ask why they need
  Ambara at all.
- Rules and AGENTS.md-style repo instructions are reliable because they are
  version-controlled and team-visible.
- Agent-specific memory is useful but siloed.

Ambara response:

- Use built-ins as distribution, not competition.
- Ambara should install or generate the rule/instruction file that tells the
  agent to call Ambara first.
- First-class release support should be honest:
  - Claude Code: first-class startup contract.
  - Plain file adapter: first-class for any agent.
  - Generic MCP clients: supported by protocol.
  - Cursor/Windsurf/Copilot-specific setup: document after manual smoke, not
    before.

Useful source areas:

- `src/ambara/cli_install.py`: CLAUDE.md and MCP config generation
- `src/ambara/cli.py`: file adapter startup command
- `bin/ambara-mcp.sh`: MCP launch helper

### Pieces

What they teach us:

- Personal workflow memory and on-device privacy are easy to market.
- Broad automatic capture is compelling for individuals.
- Their product is bigger than Ambara should be for first release.

Ambara response:

- Do not chase OS-level workflow capture.
- Emphasize "explicit, reviewed, project-owned context" over "remembers
  everything you do."
- Make privacy contrast precise: Ambara does not track read patterns, query
  text, presence, terminal history, browser history, or editor activity.

Useful source areas:

- `README.md`: Privacy section
- `SECURITY.md`: release safety stance
- `tests/test_privacy.py`: no-telemetry regression tests
- `src/ambara/core/privacy.py` and `src/ambara/core/content_policy.py`

## Product Choices For The First Public Release

### 1. Ship Ambara, Not A Compatibility Story

Recommendation: release as `ambara` for v0.5.0.

Do not split packages, keep an old public namespace, or carry a temporary
wrapper into the first release. The product name is Ambara, the package is
`ambara`, the CLI is `ambara`, and generated config uses `AMBARA_*`.

Release rule:

- README, PyPI metadata, quickstart, changelog, and demos say Ambara.
- Old-name compatibility is not part of the initial product promise.
- `docs/package-split-plan.md` remains deferred / maybe-never seam notes, not
  release scope.

### 2. Lead with governed context, not memory

Homepage/README headline should stay close to:

> Reviewable project context for AI coding agents.

Supporting copy can still say agents forget things, but the differentiated
claim is that Ambara makes remembered context reviewable, scoped, lifecycle
managed, and privacy safe.

### 3. Make `startup()` the hero workflow

The initial product should be judged by whether a fresh agent can start safely:

1. `sync()` refreshes local context.
2. `startup(goal=...)` returns compact context, value receipt, availability,
   coordination, and next action.
3. Agent follows read hints with selective `read()` or `read_many()`.
4. Agent records only explicit handoffs or proposes durable decisions.

This beats generic search because it gives the agent an operational contract.

### 4. Make value receipts visible

The economics story is unusually good and should be in the release:

- Startup packets show packet token estimate and estimated saved tokens.
- Full bodies are deferred by default.
- `ambara value` shows local aggregate savings.
- `ambara value --explain` states that numbers are app-payload estimates, not
  total model provider billing.

Do not overclaim exact dollar savings. Lead with avoided rediscovery and smaller
context payloads.

### 5. Make privacy and review part of the product demo

The release demo should prove:

- Raw query text is not stored.
- Restricted entries do not appear in broad context.
- Durable decisions and workflows go through PR review.
- Active handoffs expire.
- Stale or unavailable context changes the startup verdict.

That is the Ambara wedge.

## Near-Release Build Plan

### P0: Release Truth Freeze

Goal: one coherent public product story.

Tasks:

- Decide the first public name: `ambara` for v0.5.0.
- Audit README, changelog, package metadata, CLI help, and docs for name drift.
- Either hide the Ambara alias from public docs or label it experimental.
- Remove or rewrite any claim that says "tested with" a client we have not
  manually smoked.
- Add a short "How Ambara compares to built-in agent memories" README section.

Exit criteria:

- A new user sees one product name, one install command, and one first workflow.
- No public doc implies automatic capture, telemetry, or platform-native memory.

### P1: Setup And Startup Proof

Goal: make first-run success boring.

Tasks:

- Run `ambara onboard --yes` in a fresh local fixture.
- Run `ambara doctor --check-startup`.
- Run MCP smoke for `startup`, `read_many`, `record`, `propose`, and `hygiene`.
- Add or update docs with the exact expected startup packet fields:
  `v`, `availability`, `verdict`, `action`, `entries`, `read_hints`, `value`.
- Add a "plain file adapter" smoke for agents without MCP.

Exit criteria:

- A release candidate can be installed, initialized, and verified from scratch
  without reading internal docs.
- Startup failure paths are documented as intentional safety behavior.

### P2: Public Demo Proof

Goal: show the product in one repeatable story.

Tasks:

- Create a small example knowledge repo with:
  - one reviewed decision,
  - one active handoff,
  - one stale entry,
  - one restricted entry,
  - one duplicate/stale proposal warning.
- Add a documented command script or walkthrough:
  - install,
  - onboard,
  - startup,
  - selective read,
  - record active handoff,
  - propose durable decision,
  - view `ambara value`,
  - generate `ambara html`.
- Include expected excerpts of output, not screenshots only.

Exit criteria:

- A skeptical developer can run the demo locally and see why Ambara is different
  from an agent memory setting.

### P3: Value And Privacy Release Gate

Goal: make the strongest differentiators regression-tested.

Tasks:

- Run value-accounting tests and privacy tests.
- Run active-context privacy smoke if available.
- Verify `ambara value --explain` says app-payload-only and aggregate-only.
- Verify no value ledger event includes query text, response bodies, caller
  identity, or durable per-entry read receipts.
- Verify content safety blocks obvious credentials before write paths reach git.

Exit criteria:

- Release notes can truthfully say Ambara is privacy-first because tests enforce
  that boundary.

### P4: Release Packaging

Goal: publish a product people can actually install.

Tasks:

- Build wheel and source distribution.
- Install from built artifact into a clean virtual environment.
- Run `ambara --version`, `ambara --help`, `ambara explain`, and
  `ambara doctor`.
- Confirm Python version support and classifiers are accurate.
- Confirm release workflow, changelog, tag, and PyPI metadata are ready.

Exit criteria:

- The release artifact, not only the source checkout, passes basic CLI and
  startup checks.

## Follow-Up After v0.5.0

Build scope is superseded by `complete-build-plan.md`. That plan moves demo
proof, static HTML inspection, public golden scenarios, verified client setup
docs, and conflict/advisory proof into release scope.

Do not put these in the first release:

- Package family split, which is deferred and may never be needed.
- Cloud service.
- OS-level automatic capture.
- Code graph impact analysis.
- Full benchmark suite beyond the release proof fixtures.
- Multi-user hosted dashboard.

Good v0.5.x follow-ups after the first release:

- More client-specific smoke docs after manual verification.
- Export helpers for AGENTS.md and client rule files.
- More fixture scenarios based on real user reports.

## Readiness Standard

Current confidence: 7/10 for a useful public v0.5.0.

Confidence rises to 8.5/10 when:

- Naming is frozen for first release.
- Fresh install and startup proof pass from a built artifact.
- One local demo walkthrough is reproducible.
- Privacy and value gates are green.
- README says what Ambara does better than built-in memories without claiming
  the entire memory category.

That is enough to release soon.

## Sources Used For The Competitive Read

- memctl: https://memctl.com/ and https://memctl.com/docs/concepts
- ContextStream: https://contextstream.io/docs and https://contextstream.io/docs/mcp
- GitHub Copilot Memory: https://docs.github.com/en/enterprise-cloud@latest/copilot/concepts/agents/copilot-memory
- OpenMemory / Mem0: https://mem0.ai/openmemory
- Memstate: https://memstate.ai/ and https://memstate.ai/docs
- Cursor memories: https://docs.cursor.com/en/context/memories
- Windsurf / Devin Desktop memories: https://docs.windsurf.com/windsurf/cascade/memories
- Claude Code memory: https://docs.claude.com/en/docs/claude-code/memory
- Pieces: https://docs.pieces.app/ and https://pieces.app/use-cases/software-engineers
