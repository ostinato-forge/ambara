# Ambara Package Split Plan

Status: draft for review
Updated: 2026-06-02

## Goal

Split the existing product into the Ambara package family without losing the current product
truth:

- Ambara becomes the user-facing CLI and MCP server.
- Existing users keep the legacy CLI and import path for one release window.
- The first extraction should make real seams clearer, not create packaging
  theater.
- The new security startup work should fit the family cleanly and keep its
  claim narrow.

This plan is intentionally additive. We should extract packages only where the
current code already has a stable boundary.

## Current Codebase Seams

The repo already exposes five natural boundaries:

1. `core/`
   Pure deterministic context, search, privacy, validation, startup-packet, and
   coordination logic.
2. `providers/`
   Adapter protocol plus source-specific coordination fetchers such as GitHub
   and Jira.
3. `git/`
   Repo sync, branch, commit, PR, config, and lifecycle I/O.
4. `capture/` and `action/`
   Commit-capture pipeline and GitHub Action entrypoint.
5. `server*.py`, `cli*.py`, and top-level orchestration
   The current user-facing shell that will become Ambara.

These seams are stronger than a speculative split like "core / plugins /
everything else" because they already match the architecture rules in
`CONTRIBUTING.md`.

## Naming Recommendation

Use package names that describe the user-visible job, not internal anxiety.

Recommended family:

- `ambara-context`
  The extracted context engine and shared types.
- `ambara-github`
  GitHub coordination provider.
- `ambara-jira`
  Jira coordination provider.
- `ambara-posture`
  Agent-safe-start guardrail checks.
- `ambara`
  Meta product shell: CLI, MCP server, default install, compatibility surface.

Avoid:

- `ambara-guardrails`
  Sounds like Ambara itself is unsafe and needs to be restrained.
- `ambara-core`
  Too generic; it does not tell users what capability moved.
- `ambara-security`
  Too broad for the actual product claim.

`ambara-posture` is the best fit for the June 2 startup/security work because
the feature language is already "agent-safe-start guardrails" and "posture",
not "security suite".

## Target Package Model

### 1. `ambara-context`

Purpose:
The reusable context substrate. This is the package other tools should depend on
when they want Ambara's context model without the full MCP shell.

Owns:

- `core/` modules
- read-model code
- context packet compilation and rendering helpers that are pure or near-pure
- shared protocol types that do not require GitHub/Jira/network I/O

Likely modules to move first:

- `src/ambara/core/*`
- `src/ambara/read_model/*`
- selective pure helpers from `server_read.py`, `server_snapshot.py`,
  `server_content_policy.py`, and `cli_render.py`

Should not own:

- MCP transport
- Click CLI entrypoints
- repo cloning/fetching/branching
- provider fetchers
- GitHub Action glue

Dependency rule:
Every other Ambara package may depend on `ambara-context`. `ambara-context`
depends on no other Ambara package.

### 2. `ambara-github`

Purpose:
GitHub-specific coordination ingestion and GitHub-facing repo workflow helpers.

Owns:

- GitHub PR signal provider
- GitHub auth helpers that are only about GitHub
- GitHub PR creation/check helpers if they remain product-level dependencies

Likely modules:

- `src/ambara/providers/github_prs.py`
- GitHub-specific portions of `src/ambara/git/auth.py`
- GitHub-specific portions of `src/ambara/git/pr.py`

Open question:
Keep repo-PR mutation in `ambara` for one phase, or move it here. The safest
first split is to move read-side GitHub provider code first and leave PR write
flows in the main package until the boundary is cleaner.

Dependency rule:
`ambara-github` may depend on `ambara-context`. It should not depend on
`ambara-jira` or `ambara-posture`.

### 3. `ambara-jira`

Purpose:
Jira coordination ingestion, config parsing, and Jira-to-`CoordinationSignal`
mapping.

Owns:

- Jira provider implementation
- Jira-specific config validation and request helpers

Likely modules:

- `src/ambara/providers/jira_issues.py`
- Jira-specific slices of config validation if they remain provider-owned

Dependency rule:
`ambara-jira` may depend on `ambara-context`. It should not depend on
`ambara-github` or `ambara-posture`.

### 4. `ambara-posture`

Purpose:
Agent-safe-start guardrail checks for local repos.

Owns:

- `ambara.posture`
- any future deterministic local helper code for `.gitignore`, tracked risky
  filenames, and bounded secret smoke

Why separate:

- The feature has a narrow value proposition and could be useful in non-MCP
  flows.
- The package name stays honest about scope.
- It keeps "agent-safe-start" work from bloating `ambara-context` with
  repo-readiness semantics.

Dependency rule:
`ambara-posture` may depend on `ambara-context`, especially for secret-pattern
reuse and stable types. It should not depend on provider packages.

### 5. `ambara`

Purpose:
The product shell people install by default.

Owns:

- main CLI
- MCP server and transports
- onboarding/install helpers
- top-level config loading and compatibility logic
- default install bundle

Role in the family:

- depends on `ambara-context`
- depends on `ambara-github` by default
- may depend on `ambara-jira` as an extra or default bundle
- may depend on `ambara-posture` for `ambara posture-check`

This package remains the canonical user-facing surface even after the split.

## What Not To Split Yet

Do not extract these in the first wave:

- `git/` as a standalone package
- `capture/` as a standalone package
- `action/` as a standalone package
- value-ledger modules
- privacy/content-safety modules as their own distribution

Why:

- `git/` is still entangled with the CLI/server shell and repo config.
- `capture/` and `action/` are workflow surfaces, not yet reusable products.
- value receipts are product-level UX, not a stable external library boundary.
- privacy/content-safety are foundational to context handling and belong with
  `ambara-context` until proven otherwise.

## Dependency Graph

Recommended direction:

- `ambara-context` -> no internal Ambara dependencies
- `ambara-github` -> `ambara-context`
- `ambara-jira` -> `ambara-context`
- `ambara-posture` -> `ambara-context`
- `ambara` -> `ambara-context`, `ambara-github`

Allowed later if needed:

- `ambara` -> `ambara-jira`
- `ambara` -> `ambara-posture`

Forbidden:

- `ambara-context` -> any other Ambara package
- provider package -> another provider package
- `ambara-posture` -> provider packages

## Installation Model

The split should feel simple to users.

Recommended install surfaces:

- `pip install ambara`
  Full default product.
- `pip install ambara-context`
  Context substrate only.
- `pip install ambara-github`
  GitHub provider for custom shells.
- `pip install ambara-jira`
  Jira provider for custom shells.
- `pip install ambara-posture`
  Agent-safe-start guardrail checks only.

If we want one-repo packaging first, the main `ambara` package can expose extras
before extraction:

- `ambara[github]`
- `ambara[jira]`
- `ambara[posture]`

That gives us a low-risk migration path:

1. enforce boundaries in one repo
2. add extras and internal package seams
3. extract distributions only after import boundaries are stable

## Recommended Migration Order

### Phase 0: Boundary Hardening In Place

Do this before any new distribution exists.

- add architecture tests for provider isolation
- add architecture tests for posture isolation
- reduce `server.py`/`cli.py` dependency sprawl where needed
- separate pure helpers from orchestration helpers more aggressively

Exit criteria:

- imports show clear one-way boundaries
- no package name has to be invented to cover messy code

### Phase 1: Land Posture Inside The Monolith

This is the June 2 security startup work.

- implement the posture engine in the existing codebase
- add `ambara posture-check`
- keep the legacy command working during the compatibility window
- keep it inside `ambara` first

Why first:

- the feature already has a written scope
- it proves whether `ambara-posture` is real or premature
- it exercises the package-family naming without forcing extraction yet

Exit criteria:

- users like the command
- the product language remains narrow and quiet
- the code boundary is clean enough to move

### Phase 2: Extract `ambara-context` Internally

Still one repo, but create a package boundary as if extraction were imminent.

- move pure modules under a dedicated import root or compatibility layer
- reduce direct imports from CLI/server into deep internal modules
- create a single stable API surface for context compilation and query types

Exit criteria:

- at least one internal consumer can use the stable context API without
  importing half the repo

### Phase 3: Extract Provider Packages

Start with GitHub, then Jira.

- keep the `SignalProvider` protocol in `ambara-context`
- move provider implementations behind install-time dependencies
- make provider registration explicit rather than hard-coded

Exit criteria:

- provider install/remove does not change core context behavior
- missing-provider errors are clean and actionable

### Phase 4: Extract `ambara-posture`

Only after Phase 1 proved it deserves its own life.

- move posture engine to its own distribution
- keep `ambara posture-check` as the primary wrapper if `ambara-posture` is present
- decide whether `ambara` depends on `ambara-posture` by default

Exit criteria:

- no UX regression for users who just install `ambara`

## Compatibility Policy

During the split:

- the `ambara` CLI becomes the main entrypoint
- the legacy CLI remains during the compatibility window
- the MCP server moves under the Ambara surface
- current env vars stay `AMBARA_*`
- current imports should keep working through compatibility shims until a major
  version boundary

Do not force users to understand the package family on day one.

## Open Questions

1. Should `ambara-jira` remain part of the default `ambara` install, or become
   an optional extra?
2. Does GitHub PR mutation belong with `ambara-github`, or is it part of the
   main product shell?
3. Should `ambara-context` eventually become the external substrate, or should
   we keep that role inside the main `ambara` package longer?
4. If `ambara-posture` proves useful, should its CLI remain only `ambara
   posture-check`, or also expose a direct `ambara-posture` executable?

## Recommendation

The safest next move is:

1. Build the posture MVP inside `ambara`.
2. Harden internal boundaries.
3. Introduce extras and stable APIs.
4. Extract `ambara-context` first.
5. Extract provider packages second.
6. Extract `ambara-posture` only after the startup-check UX proves itself.

That path keeps the plan honest, gives the June 2 work a clear home, and avoids
splitting packages before the seams are ready.
