# Writing A Source Provider

Ambara Source Preview uses a source-kernel contract. Providers
translate external APIs into bounded `SourceArtifact` objects; Ambara core owns
central safety, identity minimization, body policy, token budgets, provenance,
cache health, and startup rendering.

Current built-in source providers:

- `github` for GitHub pull-request review artifacts
- `gitlab` for GitLab merge-request review artifacts
- `jira` for Jira issue artifacts
- `fixture` for local JSON demos, tests, and no-network source proof

Linear, Notion, and Confluence are v1-track Team Preview scope, but they are
not Source Preview built-ins yet.

## Source Support Matrix

| Tier | Source surface | Support promise |
| --- | --- | --- |
| First-class Source Preview | `github`, `gitlab`, `jira`, `fixture` | Ships in core, registers by default, flows through `SourceManager`, central safety, per-source health, source doctor/smoke, conformance tests, startup/status rendering, and installed proof. |
| Preview contract | `ambara.sources.types.SourceProvider` plus conformance helpers | Stable enough for no-network provider development and fixture smoke; provider packages must still prove source-specific boundaries before public support claims. |
| Protocol-compatible | v0.7 `ambara.signal_providers` entry points returning legacy signals | Adapted into source artifacts for one release train; cannot silently shadow built-ins; new provider work should target the source contract. |
| Planned Team Preview | Linear, Notion, Confluence | Product scope after Source Preview kernel proof; not built-in and not publicly claimed as supported yet. |
| Deferred | Slack, Teams, Sentry, Google Docs/Drive, Figma, customer/ops systems | Not Source Preview support. These require separate product claims, bounded selectors, privacy proof, and source-specific fixtures before support claims. |

## Source Provider Contract

A source provider implements `ambara.sources.types.SourceProvider`:

```python
from ambara.sources.types import SourceFetchRequest, SourceFetchResult


class ExampleProvider:
    provider_id = "example"
    display_name = "Example"
    categories = frozenset(...)
    capabilities = ...

    def fetch(self, request: SourceFetchRequest) -> SourceFetchResult:
        return SourceFetchResult(artifacts=())
```

Every provider must declare:

- supported categories
- supported auth modes
- supported selectors
- supported body policies
- whether full bodies can be fetched
- cursor/ETag/rate-limit behavior when applicable
- fixture/no-network behavior when applicable

Provider ids are normalized to lowercase hyphenated names. Core built-ins
cannot be silently shadowed by entry points.

## Provider Responsibilities

Providers should do the smallest safe translation from external API shape to
source artifact shape:

- Respect configured allowlists such as repos, projects, labels, pages, spaces,
  tags, or explicit handoff markers.
- Return metadata and short excerpts, not raw workspace dumps.
- Populate provenance fields and stable artifact ids.
- Preserve source freshness and partial-error information when available.
- Avoid fetching comments, user fields, bodies, or event payloads unless the
  source policy explicitly allows them.

Providers should not render markdown for startup packets and should not decide
what is safe to show the agent. Ambara core re-sanitizes provider output before
cache, startup, status, and CLI rendering.

## Core-Owned Enforcement

All source output passes through central enforcement:

- credential-shaped text is redacted
- unsafe refs and artifact URLs are removed
- identity defaults to omitted
- body policy is enforced before rendering
- excerpts are capped by source budget
- external text remains untrusted evidence, never instruction
- unavailable sources stay visible as unavailable or stale

This is intentional. Provider packages are translators, not privacy bypasses.

## Conformance Tests

Use the no-network conformance helpers before claiming provider support:

```python
from ambara.sources.conformance import (
    check_source_provider_contract,
    smoke_source_provider_contract,
)

static_report = check_source_provider_contract(provider)
smoke_report = smoke_source_provider_contract(provider, config, now=now)
assert static_report.ok
assert smoke_report.ok
```

The smoke path fetches through `SourceManager`, so it verifies central safety
and policy enforcement in addition to provider shape.

## Local Verification

For built-in or fixture-backed sources:

```bash
ambara sources doctor \
  --provider fixture \
  --fixture ./signals.json \
  --repo org/api

ambara source-smoke \
  --provider fixture \
  --fixture ./signals.json \
  --repo org/api \
  --json
```

`sources doctor` reports configured source freshness without printing source
contents. `source-smoke` prints sanitized artifact details and exits non-zero
when the source is unavailable.

## Legacy Signal Entry Points

The v0.7 compatibility entry point remains:

```toml
[project.entry-points."ambara.signal_providers"]
linear = "ambara_linear:provider"
```

Legacy providers return `PRSignal` or `CoordinationSignal` objects and are
adapted into source artifacts before central policy enforcement. This path is
kept for one release train while the source-provider package contract
stabilizes. Using an installed legacy entry point emits a deprecation warning.
New provider work should target the source contract above.

Unknown legacy providers fail clearly instead of falling back to GitHub.
