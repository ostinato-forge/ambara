# Pre-Release Quality Plan

## Purpose

Jurati is not blocked on a missing version number. It is blocked on confidence:
the system needs to prove that it can behave like dependable shared agent
context under ordinary, messy work before anyone outside the project is asked
to rely on it.

This plan defines the pre-release quality bar. It is intentionally stricter
than "tests pass" and narrower than "add more features." The goal is to make
Jurati trustworthy enough that a first external user can install it, connect an
agent, do normal work, and feel that the agent came prepared without learning
Jurati internals.

## Current Baseline

The core product shape is already built:

- MCP tools for context, query, search, read, validate, record, propose, and
  expire.
- Git-backed knowledge repos with reviewable markdown entries.
- Escalation boundaries for active, project, workflow, decision, and principle
  entries.
- Privacy boundaries that exclude restricted entries from broad retrieval and
  avoid read receipts, query logs, and participation tracking.
- Labeled PR coordination signals with provider-neutral guidance.
- Ambient capture from `jurati:` commit messages.
- Context pack import, graph/backlink validation, static HTML generation, and a
  derived SQLite read model.
- Guided onboarding plus lower-level quickstart, MCP config, Claude
  instructions, doctor checks, and startup validation.

The current risk is not whether these pieces exist. The risk is whether they
hold together as one dependable workflow when agents, git remotes, MCP clients,
and people behave imperfectly.

## Release Candidate Definition

Jurati reaches a release-candidate quality bar when all of the following are
true:

- The
  [Security, Privacy, And Content Safety Gate](security-privacy-content-safety.md)
  has no open P0 findings in the current audit.
- A new user can create a knowledge repo, install Jurati into a project repo,
  connect an agent, and pass startup checks from the installed package.
- The agent calls `sync()` and `context()` before local repo exploration in the
  first-user trial.
- The agent can follow up with `query()` or `search()` when startup context
  points at a specific decision, workflow, or project.
- A person can label a useful PR or speak normally to an agent, and the next
  agent sees the relevant context without manual digging.
- Durable writes go through the intended review path and developer-facing
  confirmations stay work-focused.
- Restricted entries never appear in broad context, search, static HTML,
  derived read models, or external access modes.
- Setup failure modes have clear, human-safe remediation. No guidance asks the
  user to understand raw MCP protocol messages.
- The docs describe one coherent product contract: shared agent context backed
  by reviewable git source, not surveillance and not a general notes product.

## Non-Goals Before First Release

- Do not broaden Jurati into a general note-taking, CRM, or project-management
  app.
- Do not add broad activity mining, chat scraping, editor telemetry, read
  receipts, or absence signals.
- Do not require developers to run Jurati commands during normal work.
- Do not depend on a single MCP client behaving perfectly.
- Do not add vector search, hosted services, dashboards, or new providers until
  a dogfood failure proves the need.

## Quality Gates

### Static Gates

Run before every release-candidate branch or PR:

```bash
python -m pytest
python -m ruff check .
python -m mypy src
git diff --check
```

Expected result:

- All unit and smoke tests pass.
- The live GitHub-auth integration test may remain skipped unless explicitly
  enabled.
- New docs do not reintroduce memory-centric product claims on public surfaces.
- New source code preserves the `core/`, `git/`, `providers/`, `server.py`, and
  `cli.py` ownership boundaries.

### Installed-Package Gate

Run from a clean wheel install, not the source checkout:

```bash
scripts/pre-release-installed-package-smoke.sh --keep
```

Expected result:

- The script builds a wheelhouse, installs Jurati into a clean virtual
  environment, and records local command evidence.
- The installed CLI is sufficient for guided onboarding, project setup, doctor,
  and serve preflight checks.
- Generated instructions and settings are usable without source-checkout paths.
- The installed package does not rely on local development artifacts.

### First-User Trial Gate

Use a disposable project repo and a disposable knowledge repo. The person should
act like a normal developer, not like a Jurati maintainer.

Scenario:

1. Run `jurati onboard` from the disposable project repo.
2. Answer the prompts for the knowledge repo remote, local knowledge repo path,
   project repo path, and starter pack.
3. Push the generated knowledge repo.
4. Run `jurati doctor --check-startup`.
5. Ask an agent to start a normal task in the project repo.
6. Observe whether the first meaningful agent action is `sync()` followed by
   `context()`.
7. Add a labeled PR signal that should affect the task.
8. Ask a second agent to continue or review related work.
9. Confirm that the second agent sees the coordination signal before acting.
10. Ask the agent to save a handoff and record a durable decision using normal
   human language.
11. Confirm that developer-facing responses do not expose entry IDs, ref paths,
    branch plumbing, or knowledge repo chores.

Expected result:

- The person can complete the trial without learning tool internals.
- The agent's useful behavior is visibly better than local-only git context.
- Any failure becomes a bug, doc fix, or scoped follow-up issue.

## Dogfood Program

Before first release, run Jurati against at least two real workstreams:

- One single-repo workstream where the value is decision and workflow recall.
- One multi-repo workstream where the value is coordination across PRs,
  active context, and handoff.

Each dogfood run should capture:

- repo names and knowledge repo used
- client and MCP config shape
- exact first agent actions
- whether `sync()` and `context()` happened before local exploration
- relevant context surfaced
- context missed
- any fallback to GitHub, grep, git log, or local-only reasoning
- any implementation detail leaked to the person
- privacy or permission prompts
- final outcome and confidence rating

Dogfood evidence should be summarized in a repo doc or issue comment, not left
only in chat.

## Adversarial Scenarios

Each scenario should have either an automated test, a scripted smoke, or a
documented manual run.

| Scenario | Expected behavior |
|----------|-------------------|
| Duplicate Jurati global and project MCP config | Doctor detects the collision and gives a safe cleanup path. |
| Duplicate non-Jurati MCP config | Doctor reports it but does not block Jurati readiness. |
| Missing `JURATI_KNOWLEDGE_REMOTE` | Doctor explains setup state; `serve --check` fails clearly. |
| Unwritable `JURATI_CACHE_DIR` | Doctor explains how to set a writable cache directory. |
| Unavailable GitHub auth | Read-only paths still work; write paths degrade to clear branch or auth guidance. |
| Stale active context | Expired active entries stay out of default context and search. |
| Conflicting decisions | Validation or curation surfaces the contradiction for human review. |
| Restricted entry linked by public entry | Broad retrieval and backlinks do not reveal restricted content. |
| Bad context pack tarball layout | Import reports clear reject/skip/create actions without writing. |
| Context pack with secrets | Import rejects the risky item before branch creation. |
| Labeled PR with unavailable changed paths | Guidance asks the agent to clarify rather than invent path overlap. |
| Unlabeled relevant PR | Jurati ignores it and states the narrow privacy boundary. |
| Agent asks user to run raw MCP JSON | Treat as a DX bug; docs and tool guidance must prevent it. |
| Agent exposes entry IDs or ref paths | Treat as a DX bug unless the user explicitly asked for debugging details. |
| Agent skips startup context | Treat as a reliability bug in client instructions, setup, or trial design. |

## Privacy Acceptance Criteria

The release candidate must preserve these invariants:

- Query text is not logged.
- Reads do not create receipts or participation metrics.
- Agent identity is not included in broad response payloads.
- Restricted entries are excluded from context, query, search, static HTML,
  read-model queries, and external access modes.
- L0 active context is opt-in and expires by design.
- Labeled PR coordination only reads configured repos and explicit labels.
- Unlabeled PRs, comments, chats, editor activity, read activity, and absence
  signals are not mined.
- Cross-system access uses explicit visibility and access modes.

## Content-Safety Acceptance Criteria

The release candidate must preserve these invariants:

- Secret-like content is rejected before durable writes, active writes, or
  imports reach git.
- Import dry-runs reject default content-policy block and review matches before
  creating review branches.
- Rejection messages include policy rule IDs and safe next steps, not raw
  unsafe content or matched secret text.
- Scanner and policy evidence records outcomes, versions, and rule IDs only;
  raw rejected content is never written as audit data.
- Regex-based policy remains described as a baseline, not enterprise-grade DLP,
  until pluggable scanner evidence exists.

## Documentation Acceptance Criteria

The docs are ready when a new user can answer:

- What does Jurati read?
- What does Jurati write?
- What is the source of truth?
- What does the agent see before work starts?
- What does a teammate see?
- What is never observed or inferred?
- What happens when setup is broken?
- What does the person do during normal work?

The answer should be discoverable from README, adoption guide, client docs, and
release notes without reading source code or old design-history documents.

## Next Implementation Slices

### Slice 1: Clean Repo And Trial Script

Goal: make the next work reproducible.

Work:

- Resolve or intentionally park the current local blog/PDF artifact.
- Add a disposable first-user trial script or checklist.
- Capture the required environment variables and cleanup steps.
- Run the trial once from the current checkout.

Exit criteria:

- The repo has a clean working tree except deliberate trial artifacts.
- A future contributor can rerun the first-user trial without reconstructing it
  from chat.

### Slice 2: Installed-Package Smoke

Goal: prove Jurati works outside the source checkout.

Work:

- Build a wheel.
- Install into a clean virtual environment.
- Run guided onboarding, doctor, validate, and serve checks from the installed
  CLI. Keep lower-level quickstart, install-claude-md, and mcp-config behavior
  covered by targeted regression tests.
- Fix any source-checkout assumptions.

Exit criteria:

- Installed-package smoke passes from a clean environment.
- The release checklist matches the command evidence.

### Slice 3: Dogfood One Real Repo

Goal: test ordinary work, not a scripted demo.

Work:

- Choose one active repo and one knowledge repo.
- Install Jurati using the normal user path.
- Run the repeatable dogfood harness once to prove setup and MCP handler order.
- Start a real task and record first agent behavior.
- Capture any missed context, leakage, setup friction, or extra prompt burden.

Exit criteria:

- Evidence shows whether Jurati improved the first planning step.
- Any failures are filed as focused issues.

### Slice 4: Multi-Repo Coordination Trial

Goal: prove the strongest product claim.

Work:

- Use two related repos with a real or simulated dependency.
- Create a labeled PR signal in one repo.
- Start or continue work in the dependent repo.
- Confirm that Jurati surfaces the coordination signal before local-only
  reasoning.

Exit criteria:

- The agent avoids a plausible coordination mistake because Jurati context was
  available.
- The person does not need to manage knowledge repo mechanics.

### Slice 5: Release Readiness Review

Goal: decide whether the project is ready for a first external user.

Work:

- Review all open issues against this quality plan.
- Run static and installed-package gates.
- Run single-repo, multi-repo, and adversarial pre-release smokes.
- Summarize dogfood and adversarial evidence.
- Identify release blockers, deferrable polish, and post-release roadmap items.

Exit criteria:

- The project has a clear yes/no release-readiness decision grounded in command
  output and dogfood evidence.

## Decision Rule

Do not declare Jurati ready because the feature list is impressive. Declare it
ready only when repeated use shows that the agent starts with the right context,
the person is not dragged into Jurati mechanics, and the privacy boundary holds
when things go wrong.
