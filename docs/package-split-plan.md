# Ambara Package Split Plan

Status: deferred / maybe never
Updated: 2026-06-03

## Current Decision

Do not build a package family for the initial Ambara release.

The public product is one distribution, one import package, one CLI, and one
MCP server: `ambara`.

The package split may never be needed. Extraction should be reconsidered only
if real users or downstream importers create concrete pressure for a smaller
reusable library. Until then, the repo ships the whole product as `ambara`.

The canonical build plan is `planning/complete-build-plan.md`.

## Historical Notes

Earlier planning explored possible packages such as context, provider, and
posture packages. Those seams may still be useful internal architecture
guidance, but they are not release scope and should not create public
compatibility commitments.

Current guidance:

- Keep `src/ambara/core/` deterministic and I/O-light.
- Keep provider-specific code behind `src/ambara/providers/`.
- Keep git and PR mutation in `src/ambara/git/`.
- Keep posture checks inside the main Ambara product.
- Keep capture and GitHub Action behavior as Ambara workflow surfaces.

If extraction is revisited later, start with current usage and import pressure,
not the old speculative package family.
