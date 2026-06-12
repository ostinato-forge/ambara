# Writing A Source Provider

Ambara Source Preview uses a source-kernel contract. Providers
translate external APIs into bounded `SourceArtifact` objects; Ambara core owns
central safety, identity minimization, body policy, token budgets, provenance,
cache health, and startup rendering.

Current built-in source providers:

- `github` for GitHub pull-request review artifacts
- `gitlab` for GitLab merge-request review artifacts
- `jira` for Jira issue artifacts
- `linear` for fixture-backed Linear issue preview artifacts
- `confluence` for fixture-backed Confluence page preview artifacts
- `fixture` for local JSON demos, tests, and no-network source proof

Linear and Confluence are public-preview, fixture-backed source providers. They
register by default and flow through source smoke, conformance, central safety,
and context-time coordination/curation.
They do not make live workspace API calls in this preview slice.

## Source Support Matrix

| Tier | Source surface | Support promise |
| --- | --- | --- |
| First-class Source Preview | `github`, `gitlab`, `jira`, `fixture` | Ships in core, registers by default, flows through `SourceManager`, central safety, per-source health, source doctor/smoke, conformance tests, startup/status rendering, and installed proof. |
| Fixture-backed Public Preview | `linear`, `confluence` | Registers by default and supports no-network source-smoke/conformance fixtures for Linear issues and Confluence pages; live API fetch is not claimed in this tier. |
| Preview contract | `ambara.sources.types.SourceProvider` plus conformance helpers | Stable enough for no-network provider development and fixture smoke; provider packages must still prove source-specific boundaries before public support claims. |
| Deferred | Notion, Slack, Teams, Sentry, Google Docs/Drive, Figma, customer/ops systems | Not Source Preview support. These require separate product claims, bounded selectors, privacy proof, and source-specific fixtures before support claims. |

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

Provider ids are normalized to lowercase hyphenated names.

## Source Auth Broker

Source config stores auth references, never raw credentials. Providers receive
runtime auth material through `SourceFetchRequest.auth`, resolved by the
provider-facing broker contract in `ambara.sources.auth`.

- `SourceAuthRef` names material by reference (`env`, `keyring`, or `managed`).
- `SourceAuthBroker.resolve(ref, *, config, provider)` is the stable runtime
  seam for OAuth/service-account implementations.
- `EnvSourceAuthBroker` is the local/dev broker and resolves env-backed refs
  such as `AMBARA_SOURCE_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, `GL_TOKEN`,
  `GITLAB_TOKEN`, or `JIRA_API_TOKEN`.
- Third-party providers are still trusted in-process code when enabled; central
  safety constrains provider output, not provider package behavior.

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

Unknown providers fail clearly instead of falling back to GitHub.
