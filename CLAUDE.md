# Ambara

Reviewable project context for AI coding agents: durable decisions, handoffs, and
project state as Markdown + YAML frontmatter in a git repo, served over MCP (and a
plain file adapter) with ranking, privacy/secret filtering, and reviewed write
paths.

This is a serious, innovative product, not a side project. Hold to established
engineering and software excellence bars by default. We do not invent process; we
follow the recognized standards (below) because that is what "good" looks like.

## Operating model

Build the entire scope first, the best we can, and exercise it like a real user
heavily and continuously throughout the build. Then present it and turn it open
source. Then real users. Users come after the OSS flip, not before.

- Full scope, no cuts. Constraints are expressed as dependency-ordered sequencing,
  never as dropped work.
- The detailed roadmap is `planning/v2-rock-solid-plan.md` (a local working doc,
  hardened through Nemotron adversarial review rounds; planning docs are not
  committed).
- Public versioning stays in `0.x` until the OSS flip; `1.0` is GA, reserved for
  proven daily team use after launch.

## Architecture

```
src/ambara/
├── core/         # pure domain logic — schema, content policy, accounting,
│                 #   curation, scoring, search, secrets, privacy, hygiene (zero I/O)
├── git/          # git + forge layer — repo, branch, commit, pr, forge, auth,
│                 #   config, lifecycle, import (the side-effecting review engine)
├── sources/      # source kernel — types, registry, config, manager, cache,
│                 #   health, safety, runtime, conformance (one path for all sources)
├── providers/    # concrete source providers — github, gitlab, jira, fixture
├── read_model/   # derived local SQLite read model
├── capture/ action/ curation/   # commit-capture pipeline, CI entrypoint, hygiene runners
├── server*.py    # MCP tool handlers — thin orchestration glue over core + git + sources
├── cli*.py       # Click CLI — thin command wrappers that delegate to services
└── static_html.py, import_context.py, context.py, ...
```

**Purity boundary (load-bearing).** `core/` is pure: no filesystem, no network, no
git, no time, no randomness. Current time, repo state, source data, and config
enter as explicit arguments. `git/`, `sources/runtime`, `server*`, and `cli*` own
all side effects. Core compiler/policy modules must not import source or git I/O.

**Server is glue, not logic.** `server.py` registers MCP tools and delegates into
focused `server_*` helpers; business logic lives in `core/`/`git/`/`sources/`.
Keep it that way.

## Key invariants

- Durable writes (decision, workflow, principle) are explicit and go through a
  reviewed branch/PR path. Nothing durable is written silently.
- Privacy boundary: no query text, response text, body snippets, caller identity,
  or per-entry read receipts in the value ledger or anywhere else. Aggregate
  counts only.
- Restricted/internal-sensitivity entries never appear in startup packets or the
  static HTML surface.
- Secret scanning and the content-policy gate run before any durable write or
  startup render. They are release gates, not optional hardening.
- Source text from providers is normalized through the central safety path before
  it can surface; provider OUTPUT is sanitized, provider CODE is trusted like any
  dependency.
- Receipts are honest: a branch-only result says so and never claims an opened PR.
  Token savings are conservative app-payload estimates with bounds, never a total
  cost meter.
- Every entry carries `schema_version`; same inputs produce same outputs in `core/`.

## Quality bar

The standard is "claims never outrun proof." Every public claim has a matching
passing test, and the README/support-matrix make no claim a test does not back.

- **Gates (must stay green):** `pytest -q`, `ruff check .`, `mypy src` (strict),
  `uv lock --check`, `git diff --check`, DCO. Coverage floor 85% (target 95%+ on
  `core/`).
- **Tests ship with the feature, not after.** Property-based tests (Hypothesis)
  cover domain invariants: schema validation, content-policy verdict monotonicity,
  accounting bound-containment, scope/privacy filtering. Determinism tests where
  `core/` promises same-in/same-out.
- **Exercise it like a real user, a lot.** Every meaningful slice gets an
  outside-in proof through the CLI and the artifacts an agent/human actually sees
  (installed wheel or isolated editable), failure paths included (unavailable,
  stale, unsafe, or budget-collapsed sources). Outside-in use is a primary signal,
  not a supplement to unit tests.
- **PRs include:** Summary (what changed and why), Tests (what was verified and the
  exact commands run), Docs (what was updated, per the matrix below).

### Documentation trigger matrix

| Change | Docs to update |
|--------|----------------|
| New/changed MCP tool | README "What Agents See" table + agent instructions |
| New/changed CLI command | README CLI reference |
| Claim implemented or proved | README/support matrix + a matching proof test |
| New/changed source provider | Support matrix tier + conformance fixture + `docs/source-providers.md` |
| Schema/frontmatter change | `schema_version` bump + migration note + `CHANGELOG.md` |
| Architectural decision | ADR under `docs/decisions/` |
| Dependency or CI change | `CHANGELOG.md`; `docs/agent-operating-policy.md` if workflow |

## Security & privacy policy

- subprocess: list form, never `shell=True`.
- Paths: validate user-supplied components before joining; no traversal.
- Secrets: never hardcode tokens/passwords; env or vault only. Known
  credential-shaped patterns are blocked/redacted before durable writes or render.
- YAML: `yaml.safe_load` only.
- URLs: HTTPS only, reject private addresses before fetching source data.
- gitignore: ignore `.env`, `*.key`, `*.pem`, `.remember/`, `.claude/`,
  `.ambara/read-model.sqlite3*`.
- CI: pin GitHub Actions to SHA refs (Node-24 generation), least-privilege
  permissions, trusted publishing for PyPI.

**Security-sensitive areas (focused review required):** the content-policy and
secret-scanning gates (`core/content_policy*`, `core/secret*`), source ingestion
and sanitization (`sources/safety`, `providers/*`), provider auth/token handling,
the value-ledger privacy boundary (`server_value`, `core/context_accounting`), the
reviewed write/branch/PR path (`git/`), and import path handling.

## Dev

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q && ruff check . && mypy src
```

## Conventions

- Python 3.12+. Ruff (line length 100), mypy strict, SPDX header on every source
  file (`# SPDX-License-Identifier: Apache-2.0`).
- Conventional Commits: `feat: fix: refactor: test: docs: ci: build: perf:
  security: chore:`. SemVer. Keep a Changelog (`CHANGELOG.md`).
- DCO sign-off on every commit (`git commit -s`). No Claude co-author trailer and
  no Claude Code footer/reference in commits or PR bodies.
- Tests mirror `src/` structure under `tests/`.
- Branch first, never commit straight to `main`. PRs for all changes to `main`;
  every PR reviewed before merge.
- Commit real work only: not planning docs, not incidental hygiene churn. Stage
  intentional files; never `git add .`.

## Working with AI agents

This product is agentically coded. AI contributors meet the same engineering bar
as humans.

- Inspect the repo before proposing changes; keep diffs small, reviewed, tested.
- Do not invent product claims, benchmark numbers, environment details, or roadmap
  commitments. If it is not proved, do not claim it.
- Name the verification commands actually run (not what "should" pass).
- Never commit secrets, local paths, private hostnames, or live inventory.
- Re-validate anything an external model (e.g. Nemotron red-team) asserts against
  the actual code before acting on it.

## Workflow contract

Read `docs/agent-operating-policy.md` before changing workflows, CI, release
automation, billing-sensitive infrastructure, or repo-wide automation. Key
defaults:

- Run `git status --short` first; preserve unrelated local changes.
- `ostinato-forge` may keep a `$0` Actions budget. When minutes are exhausted,
  land workflow-only fixes with `[skip ci]` and do not raise the budget or trigger
  CI unless asked.
- `concurrency.cancel-in-progress: true` on CI workflows; keep browser, e2e,
  release, and full smoke jobs manual or push-only, not per-PR.
- Prefer local validation before pushing.

## In flight

Active structural work tracked in the v2 plan: decomposing the historical
`cli.py` god-file into a `cli/` package (WS-A), and finishing the signals→sources
migration by deleting the legacy `signal_*` alias surface (WS-B). Do not add new
commands to `cli.py` or new compatibility shims.
