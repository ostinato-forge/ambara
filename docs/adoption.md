# Jurati Adoption Guide

This guide is for training teams, engineering teams, and mixed human-agent
teams that need shared context without adding another heavyweight system.

## The Adoption Promise

A new user should be able to answer these questions in minutes:

- What is Jurati?
- What repo does it read?
- What does it write?
- What will my agent see?
- What will my teammates see?
- What privacy boundary does it enforce?

If those answers are not obvious, the product is not done.

## The Simple Mental Model

Jurati is a shared notebook backed by git.

Agents read it before acting. People and agents write to it only when they
explicitly choose to share something. Durable changes use normal git review.
Short-lived active context uses active refs and expires from normal results.

## Daily Workflow

### Start Work

The user or agent asks:

```text
query(topic="what I am about to work on")
```

Jurati should reveal:

- active project context
- relevant prior decisions
- team workflow expectations
- long-lived principles

For a training developer, this might be lesson status, lab validation workflow,
or course review rules. For an engineer, it might be release policy, service
ownership, incident history, or architecture rationale.

### During Work

The user records only explicit shareable context:

```text
record(type="active", title="Current focus", content="...")
```

This is for current focus, blockers, handoffs, and investigations. It is not
telemetry. It is not inferred from activity. It is intentional broadcast.

### Before Review

The user checks the team workflow:

```text
query(topic="review checklist", type="workflow")
```

The result should reduce review noise: fewer missed commands, fewer hidden team
preferences, fewer repeated explanations.

### After A Decision

The user proposes durable knowledge:

```text
propose(type="decision", title="...", content="...")
```

Jurati opens a branch and pull request. That makes the write visible,
attributable, and reviewable.

## What Must Stay Clear In The UX

Every command and doc path should make these boundaries visible:

- The software repo is `jurati`.
- The shared content repo is the knowledge repo.
- Reads come from a local cache after sync.
- Writes happen only through explicit tools.
- L0 active context is not durable source-of-truth content.
- L1/L2/L3 durable content reaches the source-of-truth branch by PR.
- Query text and read behavior are not persisted as telemetry.

## First Team Rollout

1. Pick the git remote that will hold the knowledge repo.
2. Run `jurati quickstart ./jurati-knowledge --remote <git-url>`.
   Use `--pack training` or `--pack engineering` when a department-shaped starter
   repo would make the first review easier.
3. Read the generated README and starter entries.
4. Push the generated repo to the remote.
5. Paste the JSON from `quickstart` into one MCP client.
6. Run `jurati mcp-config --remote <git-url>` later if you need to regenerate it.
7. Run `jurati doctor`.
8. Run `jurati serve --check`.
9. Ask the agent to call `explain()` so the user can see the boundaries.
10. Ask the agent to call `status()` so the user can see the connected repo,
    cache path, sync health, and entry counts.
11. Ask the agent to query Jurati before starting work.
12. Capture one real workflow or decision as a PR.
13. Once a week or before a release, ask the agent to call `hygiene()` and clean
    up expired active context or stale proposed entries.

Stop there. Adoption succeeds when the first team sees useful context appear in
normal work without ceremony.

## Department-Neutral Examples

Training:

- lesson migration notes
- lab validation gotchas
- peer review expectations
- course release checklist
- recurring style or assessment decisions

Engineering:

- service ownership context
- release and rollback workflow
- architecture decisions
- incident follow-up notes
- coding standards and review expectations

Both:

- current project state
- active blockers
- handoff notes
- durable decisions
- "how we work here" preferences
