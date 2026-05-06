# Context Packs Build Plan

## Purpose

Jurati should absorb the useful parts of the AI Brain/Obsidian workflow as
first-class context packs. The standalone prototype proved the affordances:
typed Markdown, validation, wiki links, backlinks, import/export, search, and a
static browser. Jurati already owns the durable architecture: schema validation,
MCP tools, privacy filtering, PR-based writes, active refs, and ranked search.

The plan is to build the useful affordances into Jurati and retire the separate
prototype.

## Roadmap Issues

- [#25 Roadmap: build Jurati context packs for shared agent context](https://github.com/ostinato-forge/jurati/issues/25)
- [#26 Roadmap: add entry graph and backlink validation](https://github.com/ostinato-forge/jurati/issues/26)
- [#27 Roadmap: import context packs into Jurati knowledge repos](https://github.com/ostinato-forge/jurati/issues/27)
- [#28 Roadmap: document context-pack migration and adoption](https://github.com/ostinato-forge/jurati/issues/28)
- [#29 Roadmap: add a derived SQLite/FTS read model](https://github.com/ostinato-forge/jurati/issues/29)
- [#30 Roadmap: generate a static context browser](https://github.com/ostinato-forge/jurati/issues/30)

## Target Architecture

```text
Jurati Markdown repo = reviewed team context
Jurati MCP tools = retrieval and write contract
Generated graph/index = machine query layer
Static HTML = human browsing layer
PRs = durable review path
Context packs = import and migration format
```

Jurati can replace an Obsidian-backed team context workflow. It should not
become an Obsidian clone or a general personal notes application.

## Product Boundaries

Jurati context packs are for:

- repository profiles and project operating context
- tool notes that affect agent behavior
- error patterns and recovery procedures
- durable decisions and principles
- reusable workflows and investigation queries
- reviewed learnings worth sharing across agents

They are not for:

- raw chat transcripts
- personal workflow preferences
- secrets, credentials, or private customer data
- query logs, read receipts, or participation tracking
- unreviewed bulk note dumps

## Phase 0: Architecture Pass

Status: implemented in the architecture pass.

Work:

- Rename public claims from memory-centric wording to shared agent/team context.
- Add `docs/context-not-memory.md`.
- Clarify that Markdown + YAML is the human-reviewable source format.
- Clarify that runtime indexes are derived query structures.
- Keep "memory" only as casual shorthand, not the architecture claim.

Exit criteria:

- README and adoption docs lead with context, not memory.
- MCP/CLI explanation payloads use the context framing.
- Tests prevent the old primary claim from returning to product surfaces.

## Phase 1: Entry Graph And Backlinks

Status: initial implementation in progress.

Build a pure `jurati.core.graph` module.

Work:

- Parse `[[entry-id]]` and `[[entry-id|label]]` links from entry bodies.
- Resolve links against Jurati entry IDs.
- Support aliases only if they become explicit schema fields.
- Report outgoing links, backlinks, and unresolved links.
- Keep graph logic in `core/` with no git/provider imports.
- Extend validation so unresolved links fail `jurati validate`.
- Include links and backlinks in `read()` output.

Exit criteria:

- `tests/core/test_graph.py` covers parsing, resolution, backlinks, and broken links.
- `tests/test_cli.py` proves unresolved links fail `jurati validate`.
- `tests/test_server.py` proves `read()` returns link/backlink metadata.
- `tests/test_server.py` proves backlinks do not disclose restricted source entries.
- Existing privacy tests still prove restricted entries are excluded from broad retrieval.

## Phase 2: Context Pack Import

Status: dry-run planner and review-branch writes in progress.

Add `jurati import-context <bundle> --dry-run`.

Work:

- Accept a tarball with a manifest plus Markdown notes.
- Validate all imported content before writing.
- Map old AI Brain categories into Jurati types:

| Source category | Jurati type | Default level | Notes |
|-----------------|-------------|---------------|-------|
| repo profile | project | L1 | Repository operating context |
| tool note | workflow | L2 | Tool usage and guardrails |
| error pattern | workflow | L2 | Recovery or troubleshooting workflow |
| decision | decision | L2 | Preserve rationale where available |
| learning | project or principle | L1 or L3 | Require explicit mapping or default to project |
| query | workflow | L2 | Reusable investigation workflow |

- Require a dry-run summary before write use in docs.
- Skip or reject personal/local-only files.
- Preserve original source metadata in frontmatter or a body section.
- Write through a branch/PR path for durable imports, not silent main mutation.

Initial bundle format:

```json
{
  "schema_version": 1,
  "name": "Team Pack",
  "items": [
    {
      "path": "Repos/api.md",
      "category": "repo profile",
      "id": "api-service",
      "title": "API Service",
      "projects": ["api"],
      "tags": ["migration"]
    }
  ]
}
```

The tarball must contain `manifest.json` and the referenced Markdown files.
The dry-run reads the bundle, maps items into Jurati entries, validates the
generated entries, checks links against the target knowledge repo, and prints
create/skip/reject actions without writing files.

When run without `--dry-run`, the import requires a clean git working tree,
creates a review branch such as `jurati/import-context-team-pack`, writes the
generated entries, and commits them as one import commit. The branch can then be
pushed and reviewed through the normal pull request path.

Exit criteria:

- `import-context --dry-run` shows create/skip/reject actions.
- Invalid frontmatter, unknown categories, and restricted content are rejected.
- Imported entries pass `jurati validate`.
- Import writes are reviewable through the existing git/PR boundary.

## Phase 3: Static Context Browser

Status: in progress.

Add `jurati html <knowledge-repo>`.

Work:

- Generate `_site/index.html` from a local knowledge repo.
- List entries by type, status, project, and updated time.
- Render entry bodies with safe HTML escaping.
- Render `[[entry-id]]` links as page links.
- Show backlinks on entry pages.
- Make broken links visually obvious.
- Exclude restricted entries from generated pages and backlinks.

Exit criteria:

- HTML generation is deterministic.
- Generated output is local/derived and not required source material.
- Browser output never bypasses restricted-entry rules.
- Tests cover link rendering, backlink rendering, and escaping.

## Phase 4: Derived Query Store

Add a persisted read model only when runtime needs justify it.

Work:

- Create a local SQLite store under `.jurati/` or the cache directory.
- Treat SQLite as rebuildable from the git knowledge repo.
- Add FTS5 for text search if BM25/in-memory ranking becomes insufficient.
- Consider vector or graph projections only after concrete retrieval gaps appear.
- Keep git as the source ledger and PRs as the review path.

Exit criteria:

- SQLite can be rebuilt from the knowledge repo with one command.
- Query results preserve existing visibility, sensitivity, and expiry rules.
- Tests prove restricted entries are absent from broad indexes.
- The MCP API does not expose implementation details of the read model.

## Phase 5: Adoption And Cleanup

Work:

- Update README, adoption guide, and client instructions for context packs.
- Add migration instructions for teams currently using Obsidian/AI Brain notes.
- Remove the standalone `internal-ai-brain` spike from the workspace.
- Keep any useful sample bundles as fixtures only if they are small and sanitized.

Exit criteria:

- Jurati docs describe one product path.
- No active docs tell users to install or use the standalone spike.
- The spike has been deleted.
- Full tests and lint pass.

## Implementation Order

1. Land the architecture pass and context-pack plan.
2. Build `jurati.core.graph` and validation integration.
3. Add link/backlink metadata to `read()`.
4. Build `import-context --dry-run`.
5. Add PR-backed import writes.
6. Add static HTML generation.
7. Reassess whether SQLite/FTS is needed.

This order makes relationships and validation real before importing any bulk
content, and keeps human browsing as a derived surface rather than the product
center.
