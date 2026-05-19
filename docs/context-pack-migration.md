# Context Pack Migration

This guide is for teams that already have a shared Markdown context workflow
and want Jurati to become the reviewed agent context layer.

Jurati is not trying to import a personal vault wholesale. The goal is to move
curated, shareable team context into Jurati entries so agents can retrieve it
through the same validation, privacy, and git review path as everything else.

## What To Migrate

Good context-pack candidates:

- repository profiles and project operating context
- tool usage notes that should shape agent behavior
- recurring error patterns and recovery procedures
- durable decisions and rationale
- reusable investigation queries
- team learnings that future agents should see

Do not import:

- raw chat transcripts
- personal notes or preferences
- scratch files, local-only notes, or private drafts
- secrets, credentials, customer data, or restricted content
- query logs, read receipts, participation records, or surveillance data

## Bundle Format

A context pack is a tarball with `manifest.json` plus referenced Markdown files.

```json
{
  "schema_version": 1,
  "name": "Example Context Pack",
  "items": [
    {
      "path": "Repos/api-service.md",
      "category": "repo profile",
      "id": "api-service",
      "title": "API Service",
      "projects": ["api"],
      "tags": ["migration"]
    }
  ]
}
```

Supported categories:

| Source category | Jurati type | Default level |
|-----------------|-------------|---------------|
| `repo profile` | `project` | `L1` |
| `tool note` | `workflow` | `L2` |
| `error pattern` | `workflow` | `L2` |
| `decision` | `decision` | `L2` |
| `learning` | `project` | `L1` |
| `query` | `workflow` | `L2` |

Use explicit `type` and `level` fields only when the default mapping is wrong.
For example, a long-lived team principle can set `"type": "principle"` and
`"level": "L3"`.

## Dry-Run First

Create the tarball:

```bash
tar -czf context-pack.tar.gz -C ./context-pack .
```

Run the dry-run against the target knowledge repo:

```bash
jurati import-context --dry-run --repo ./jurati-knowledge context-pack.tar.gz
```

The dry-run prints:

- `create` for entries Jurati can generate
- `skip` for entries whose IDs already exist
- `reject` for unsafe or invalid items

Fix rejects before writing. Jurati rejects unknown categories, restricted
content, personal/local-only paths, malformed frontmatter, invalid generated
entries, unsafe paths, and unresolved `[[entry-id]]` links.

## Write For Review

Once the dry-run is clean:

```bash
jurati import-context --repo ./jurati-knowledge context-pack.tar.gz
```

Jurati requires a clean git working tree, creates a review branch named like
`jurati/import-context-example-context-pack`, writes generated entries, and
commits them together. Push that branch and open the normal knowledge-repo pull
request.

Use a custom branch if needed:

```bash
jurati import-context \
  --repo ./jurati-knowledge \
  --branch jurati/import-context-api-notes \
  context-pack.tar.gz
```

## Browse The Result

After the import PR is merged, generate the optional static browser:

```bash
jurati html ./jurati-knowledge
```

The generated `_site/` directory is local derived output. It is not the source
of truth. Jurati excludes restricted entries from the generated browser.

## Example Pack

A tiny sanitized example lives in
[`docs/examples/context-pack`](examples/context-pack). Build it with:

```bash
tar -czf /tmp/jurati-example-context-pack.tar.gz -C docs/examples/context-pack .
jurati import-context --dry-run --repo ./jurati-knowledge /tmp/jurati-example-context-pack.tar.gz
```
