# Ambara Release Proof

This is the release proof path for Ambara. The source-checkout gates and
fixture-backed product proof are local and use no live workplace/source APIs.
The installed-wheel smoke builds a local Ambara wheel, but a clean dependency
install may resolve third-party Python packages from the package index unless
the dependency cache or wheelhouse is already populated. The Docker/Podman
smoke builds a local CLI image from this checkout and may pull the Python base
image and Python dependencies unless they are already cached.

## Source Checkout

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
env UV_CACHE_DIR=/tmp/ambara-uv-cache uv lock --check
```

## Built Artifact

For the full installed user-path smoke, run:

```bash
scripts/installed-user-path-smoke.sh
```

That script builds a wheel, installs it into a clean venv, runs the local demo
proof, smokes source doctor/safety/unavailable/stale-source paths, verifies
fixture-backed Linear and Confluence preview sources, checks source-derived
startup guidance and noisy-source budget omissions, and simulates Claude Code,
Codex, Cursor, and Gemini through the file-adapter path.

For the local container install smoke, run:

```bash
scripts/docker-install-smoke.sh
```

That script builds the local Dockerfile with Docker or Podman, runs the
installed CLI as the non-root `ambara` user, verifies clean `serve --check`
failure without a remote, runs the generated demo proof inside `/workspace`,
and smokes fixture-backed Linear and Confluence preview sources. This proves a
single-node local container install path only; it is not a Compose, Kubernetes,
swarm, fleet, or managed-deployment proof.

Manual equivalent:

```bash
uv build --out-dir /tmp/ambara-dist
python3.12 -m venv /tmp/ambara-install-smoke
/tmp/ambara-install-smoke/bin/python -m pip install \
  /tmp/ambara-dist/ambara-0.7.0-py3-none-any.whl
/tmp/ambara-install-smoke/bin/ambara --version
/tmp/ambara-install-smoke/bin/ambara --help
/tmp/ambara-install-smoke/bin/ambara explain
/tmp/ambara-install-smoke/bin/ambara doctor
```

`ambara serve --check` should fail cleanly when no remote is configured:

```bash
/tmp/ambara-install-smoke/bin/ambara serve --check
```

## Local Product Proof

```bash
/tmp/ambara-install-smoke/bin/ambara demo --path /tmp/ambara-demo --force
PATH="/tmp/ambara-install-smoke/bin:$PATH" /tmp/ambara-demo/run-proof.sh
/tmp/ambara-install-smoke/bin/ambara sources doctor \
  --provider fixture \
  --fixture /tmp/ambara-demo/signals.json \
  --repo org/api \
  --json
/tmp/ambara-install-smoke/bin/ambara source-smoke \
  --provider fixture \
  --fixture /tmp/ambara-demo/signals.json \
  --repo org/api \
  --json
for client in claude-code codex cursor gemini; do
  /tmp/ambara-install-smoke/bin/ambara client-smoke \
    --client "$client" \
    --remote /tmp/ambara-demo/knowledge \
    --project-path "/tmp/ambara-client-smoke-$client" \
    --json
done
```

The proof script validates the generated knowledge repo, checks startup,
inspects source freshness, smokes fixture source safety, compiles compact JSON
and Markdown context, proves restricted entries stay out of startup and static
HTML, reads one selected body, records active context, proposes durable context
on a review branch, imports docs through a review branch, queues and flushes
ambient capture, runs posture checks, writes a local value receipt, and runs a
Codex file-adapter smoke. The client-smoke loop verifies the file-adapter
contract for each named agent surface against the installed artifact.
The generated demo and proof script use source-native source selector env vars
(`AMBARA_SOURCE_REPOS` and `AMBARA_SOURCE_FIXTURE`); legacy
`AMBARA_PR_SIGNAL_*` env vars remain compatibility aliases.

The tag-triggered release workflow repeats the installed-wheel smoke before
publish in the `artifact smoke` job.

## v0.5.1 Trust And Safety Proof

The v0.5.1 follow-up release adds product-trust checks that matter to the human
user, not only source health:

```bash
pytest -q tests/test_server.py tests/capture/test_pipeline.py tests/action/test_capture_action.py
pytest -q tests/test_privacy_coordination.py tests/test_context_token_efficiency.py tests/core/test_context_compiler.py
```

These checks prove:

- branch-only fallback says that no pull request was created
- GitHub Action capture bootstraps the knowledge repo from the declared remote
  and token inputs
- commit capture and action capture apply the content-policy gate, not only
  regex secret scanning
- coordination, curation, and snapshot surfaces share one signal refresh path

If the release notes claim any of those behaviors, the tests above must remain
green from the source checkout before release.

## v0.6.0 Multi-Forge Proof

The v0.6.0 line widens Ambara's first-class review surface from GitHub-only to
GitHub plus GitLab. The proof path should verify that claim locally, without
network access:

```bash
pytest -q tests/test_cli.py tests/action/test_capture_action.py
pytest -q tests/providers/test_fixture_signals.py tests/providers/test_gitlab_mrs.py
pytest -q tests/git/test_auth.py tests/git/test_pr.py
```

These checks prove:

- the local demo fixture includes both GitHub and GitLab review signals
- the generated `run-proof.sh` path verifies that the local demo fixture keeps
  GitLab review evidence wired into the no-network proof flow
- CI capture can derive source context from GitHub Actions or GitLab CI
- fixture-backed and live GitLab review signals flow through the same
  coordination model as GitHub review signals
- GitLab merge request creation, stale-review listing, and branch-only review
  URLs all work through the forge-aware write path

If Ambara claims that GitHub and GitLab are first-class review backends, the
checks above must remain green before release.

## v0.7.0 Cross-Agent Proof

The v0.7.0 line makes Ambara's cross-agent and provider-extension claims
testable. The proof path should verify the normal-day claim locally, without
network access:

```bash
pytest -q tests/test_prod_day_simulation.py
pytest -q tests/test_cli.py::TestAdoptionHelpers::test_client_smoke_writes_file_adapter_context
pytest -q tests/providers/test_registry.py tests/providers/test_fixture_signals.py
pytest -q tests/core/test_architecture.py tests/test_architecture_language.py
```

These checks prove:

- a deterministic 100-user / 100-agent workday shares context across Codex,
  Claude Code, Cursor, and Gemini surfaces
- GitHub, GitLab, and Jira signals feed the same startup coordination model
- startup packets remain compact and do not leak restricted bodies
- `ambara client-smoke` verifies the file-adapter path for every named client
- built-in and entry-point signal providers resolve through the same registry
- entry-point signal providers cannot silently shadow built-ins
- 0.7.0 public docs and release proof stay inside the tested support surface

If Ambara claims cross-agent or third-party signal-provider support, the checks
above must remain green before release.

## Source Preview Proof

The Source Preview line proves the source kernel plus fixture-backed Linear and
Confluence preview providers before adding live Team Preview workspace APIs or
post-preview sources such as Notion. The source/provider proof must stay
fixture-backed by default, with no live workplace/source API calls, and should
verify health, safety, conformance, compactness, and cross-agent handoff
behavior:

```bash
pytest -q tests/sources/test_source_kernel.py tests/sources/test_source_conformance.py
pytest -q tests/test_cli_sources.py tests/test_server_health.py
pytest -q tests/test_cli_file_adapter.py tests/test_startup_v2_rendering.py
pytest -q tests/test_server_coordination.py tests/test_server_curation.py
pytest -q tests/providers/test_registry.py tests/providers/test_fixture_signals.py
pytest -q tests/test_prod_day_simulation.py
scripts/installed-user-path-smoke.sh
```

These checks prove:

- GitHub, GitLab, Jira, and fixture/local JSON flow through the source manager
  before legacy signal consumers see them
- built-in providers cannot be silently shadowed by entry points
- source artifacts carry provenance, text trust, body policy, identity policy,
  sensitivity, omissions, and per-source subject-ref status
- `ambara sources doctor` reports source freshness, including stale source
  health, without printing source contents
- `ambara source-smoke` shows sanitized artifacts and fails unavailable sources
  instead of treating them as no relevant context
- `ambara startup` refreshes configured source inputs, surfaces source-derived
  coordination guidance, and reports compact source health and aggregate source
  omission counts without exposing source identities or provider diagnostics
- server snapshot/status output carries per-source health for the real runtime
  path, including unavailable-without-baseline behavior
- server snapshot, coordination, and curation helpers prefer source artifacts
  when `state.source_report` is available, while preserving legacy signal
  compatibility as fallback
- lifespan, sync, context, coordination, and curation default to source-report
  refresh; aggregate legacy signal fetchers are explicit compatibility
  injections and are guarded against returning as server wiring
- source-report assembly lives under `ambara.sources.runtime`; provider
  signal aggregation remains a compatibility facade
- snapshot status exposes source health as `source_refresh` while preserving
  `signal_refresh` compatibility for existing clients
- default source refresh writes `state.source_report` and source artifacts
  without backfilling converted artifacts into the legacy global signal cache
- a single source path: context snapshots and server read paths read source
  artifacts directly, with no legacy signal-cache fallback
- snapshot coverage reports source artifact counts while preserving the
  compatibility `signals_considered` field
- server state stores `source_health` natively while preserving
  `signal_health` as a compatibility alias
- runtime refresh callers use `refresh_source_inputs()` driving the source
  report path
- snapshot status exposes source-cache aggregate metadata and source-backed
  `signal_cache_*` compatibility aliases
- source runtime reports store `legacy_signals` natively for compatibility
  conversion while accepting `signals` as a compatibility alias, and default
  server refresh health uses source artifact counts
- server runtime input selection uses source-input helpers
- hygiene curation uses source-derived advisory inputs and reports source
  refresh failures explicitly
- source-aware curation callers use `suggest_revalidation_from_source_inputs()`
  while preserving `suggest_revalidation_from_signals()` compatibility
- source-aware coordination callers use `classify_source_inputs()` while
  preserving `classify_signals()` compatibility
- source-aware scope filtering uses `filter_source_inputs()` while preserving
  `filter_signals()` compatibility
- source-aware runtime safety uses source-text sanitizer names while preserving
  legacy signal sanitizer compatibility
- server scope filtering uses `source_config_for_mute()` while preserving
  `signal_config_for_mute()` compatibility
- production-day simulation classifies source artifacts directly and covers
  sanitized unsafe source text plus partial source outage reporting
- source-aware runtime callers use `fetch_source_runtime_report()` while
  `fetch_source_signal_report()` remains a compatibility wrapper
- source-aware runtime callers use `source_inputs_configured()` while
  `signals_configured()` remains a compatibility wrapper, and curation paths no
  longer define private `_signals_configured` helpers
- source-aware runtime annotations use `LegacySignalFetcher` while
  `SignalFetcher` remains a compatibility alias
- compiler/startup freshness uses source-input baseline helpers while legacy
  signal baseline helpers remain compatibility aliases
- context snapshots store `source_advisories` natively and source-aware curation
  renderers use source-input advisory aliases while legacy advisory names remain
  compatibility surfaces
- source-aware runtime include flags use source-input names internally while
  legacy `include_signals` helper arguments remain compatibility surfaces
- the context tool accepts source-native `include_source_inputs` while
  preserving legacy `include_pr_signals`, and conflicting include flags return
  a clear error instead of guessing whether to spend tokens or surface source
  evidence
- local mute/unmute commands accept source-native `--source-input` while
  preserving legacy `--signal-source`, and human summaries print
  `source_inputs` while the compatibility config key remains readable
- scope mute policy accepts source-input naming and server-side source config
  filtering uses source-input aliases while preserving legacy `signal_sources`
  serialization
- context snapshots store `muted_source_inputs_hidden` natively while preserving
  the legacy `muted_signals_hidden` payload key
- content-policy rendering limits use source-native names while preserving
  legacy signal-limit config keys and properties
- context coverage and value accounting expose source-native source-input and
  source-excerpt omission counts while preserving legacy signal coverage and
  accounting keys
- hygiene curation uses source config naming for env-derived source setup while
  preserving the legacy signal config helper as a wrapper
- coordination and curation user-facing summaries and privacy boundaries name
  source inputs instead of review signals while preserving legacy compatibility
  payload keys
- legacy `PRSignalsConfig` selectors and source env parsing are source-config
  owned while `git.config` keeps a compatibility import for existing callers,
  `SourceInputsConfig` is the canonical source selector shape, runtime modules
  use the source-owned import path, and `AmbaraConfig` exposes a source-native
  `source_inputs` alias for legacy `pr_signals`
- core source-aware helpers use a `SourceInputLike` alias while preserving
  `SignalLike` as a compatibility alias for legacy providers and callers
- pure classifier and curation internals use source-input helper/constant names
  while preserving legacy compatibility wrappers
- normalized classifier guidance refers to source inputs instead of legacy
  signals
- source refresh aggregate health is derived from per-source inspection records
  instead of hand-maintained source-report error scans
- the legacy aggregate signal facade reuses source-report errors while
  preserving one-release compatibility wording
- README support-matrix and source-text safety language names Source Preview
  surfaces without implying broader workplace-search support
- public claim tests keep README, source-provider docs, and release proof from
  advertising unbuilt Team Preview or deferred sources as Source Preview support
- external legacy `ambara.signal_providers` entry points emit a deprecation
  warning when adapted into the source registry, while built-ins remain quiet
- central source safety redacts credential-shaped text, flattens
  provider-rendered markdown/control syntax, removes unsafe refs, keeps external
  text untrusted, and preserves token budgets
- source inspection round-trips per-source cursor/ETag/TTL metadata through the
  source manager and cache, and TTL expiry marks source status/startup health as
  stale before the fixed refresh interval
- partial source refresh errors degrade source health with generic
  startup/status wording while preserving bounded artifacts and hiding raw
  provider diagnostics
- source doctor/smoke CLI payloads preserve diagnostic counts/status while
  redacting raw provider error details by default
- legacy source-config shims use the v1 default source budget, so configured
  fixture/forge/work-tracker inputs cap noisy artifacts before startup
  rendering
- source rate-limit hints degrade source health with a generic status/CLI
  boolean while preserving prior baseline artifacts
- hard provider refresh exceptions become generic source-health failures at
  source inspection, status, and compatibility-facade boundaries
- hygiene/curation source refresh warnings stay generic while preserving
  failure-safe curation behavior
- startup and compiler fallback guidance names configured source inputs instead
  of legacy coordination signals, and missing fixture sources do not print raw
  provider diagnostics before the JSON startup packet
- installed user-path smoke verifies source-derived startup guidance,
  stale/unavailable source doctor and smoke failure paths, unsafe source
  redaction, noisy source budget omission counts, compact startup output, and
  cross-agent file-adapter output without leaking raw fixture paths, provider
  diagnostics, source identities, or budget-omitted source items
- the provider conformance helper validates source-provider shape through a
  no-network `SourceManager` smoke
- `docs/source-providers.md` lists first-class, preview-contract,
  protocol-compatible, planned Team Preview, and deferred source tiers
- installed-wheel proof still runs demo, source doctor/smoke, adversarial
  safety fixture, fixture-backed Linear/Confluence preview source smoke, noisy
  source budget fixture, startup artifact inspection, and
  Claude Code/Codex/Cursor/Gemini file-adapter smokes
- Docker/Podman proof builds the local CLI image, runs it as a non-root user,
  executes the demo proof under `/workspace`, and smokes fixture-backed Linear
  and Confluence preview sources without claiming fleet deployment

Source Preview must not publicly claim live Linear/Confluence API ingestion,
Notion, Slack, Teams, Sentry, Figma, broad workplace search, or
arbitrary privacy-safe third-party providers until the matching provider and
proof gates land.

## Governance Proof

```bash
scripts/check-dco.sh origin/main..HEAD
uv run pytest tests/test_license_headers.py -q
```

The release also requires the GitHub DCO workflow to pass on the release PR.

## Publish Gate

For future release tags, do not push the release tag until PyPI trusted
publishing is confirmed for:

- project/name: `ambara`
- owner/repo: `ostinato-forge/ambara`
- workflow: `.github/workflows/release.yml`
- environment: `pypi`

See [PyPI Trusted Publisher Setup](pypi-trusted-publisher.md) for the exact
PyPI values, the difference between ordinary and pending publishers, and the
rerun path if a tagged release fails before publisher setup is complete.

If a tagged release already failed on the publish step, do not retag. Fix the
publisher on PyPI and rerun the release workflow for that tag.

After the tag workflow publishes, repeat the local product proof from a clean
`pip install ambara` environment.

## Release Tag Hygiene

Before any preview or release tag, inspect local and remote tags for unrelated
historical artifacts. Keep the tag list monotonic and do not reintroduce a tag
that sorts above the current release.
