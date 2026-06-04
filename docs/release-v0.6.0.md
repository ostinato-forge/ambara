# Ambara v0.6.0 Release Notes

These notes are the source text for the Ambara v0.6.0 release. Keep them
aligned with the verified artifact, release proof, and actual support surface.

## Release Shape

Ambara v0.6.0 is a multi-forge foundation release with first-class GitLab
support.

v0.5.1 tightened trust and truth inside the existing GitHub-shaped product.
v0.6.0 widens the real support surface without pretending every forge now works
equally well.

The release truth is:

- GitHub remains first-class
- GitLab becomes first-class
- review/write/signal flows are forge-aware instead of GitHub-shaped
- other git hosts remain compatible through branch-only flow, not first-class

## Highlights

- **First-class GitLab review lifecycle** — Ambara can create GitLab merge
  requests for durable writes, inspect stale GitLab review artifacts during
  hygiene, and generate truthful GitLab review links for branch-only fallback.
- **Generalized review signals** — GitHub pull requests and GitLab merge
  requests now feed the same coordination model, so review signals are no
  longer typed as a GitHub-only concept at the product edge.
- **CI truth across forges** — the capture entrypoint now supports GitHub
  Actions, GitLab CI, and direct generic CI invocation, with docs that match
  those supported paths.
- **Ambient value evidence** — startup packets now surface a local 7-day token
  savings rollup from aggregate-only value events. Currency is shown only when
  a managed deployment supplies its own token price; Ambara does not invent a
  universal dollar estimate.
- **Expanded secret scanning** — write/import/capture policy now blocks common
  GitLab and Slack token families before public release.
- **Support-surface honesty** — onboarding, CLI output, release proof, and
  troubleshooting docs now say exactly what is first-class and what still
  starts branch-only.

## Why This Matters

Ambara's promise is broader than GitHub.

The human user wants durable, reviewable context that survives the agent and
can be inspected directly. If that experience is fully real only on GitHub,
the product reads narrower than the actual idea.

GitLab is the right next surface because it expands the reachable user base,
fits self-hosted teams, and is close enough to GitHub's review model to force
the right abstraction boundaries without turning this release into a six-forge
sprawl.

## Verified Before Release

- forge-aware auth and review lifecycle tests pass for GitHub and GitLab
- GitLab review signal adapter tests pass beside the existing GitHub signal
  path
- GitHub Action and GitLab CI capture paths pass their focused coverage
- Python 3.12, 3.13, and 3.14 are in CI and release test matrices
- the local demo proof includes GitHub and GitLab review evidence in a
  no-network flow
- startup/value tests prove local aggregate token-savings rollups appear
  without end-user pricing configuration
- public docs and CLI copy match the actual support matrix

## Known Limits

- GitHub and GitLab are first-class in v0.6.0; other git hosts may still fall
  back to truthful branch-only flow
- Jira remains a supported coordination signal source, but this release does
  not generalize every provider family beyond review signals
- Ambara still depends on agent steerability for its best interactive
  experience, even though the CLI, static HTML, file adapter, and Git-backed
  receipts reduce that dependency
