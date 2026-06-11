# ADR 0002: Source auth-broker contract frozen (v1)

- Status: accepted
- Date: 2026-06-11

## Context

Team Preview sources need OAuth or service-account authentication, while the
current solo/dev path uses environment tokens. Source configuration must keep
storing selectors and references only; raw credentials must not enter source
config, source artifacts, cache records, startup packets, or static output.

## Decision

Ambara freezes a provider-facing auth-broker seam in
`ambara.sources.auth`:

- `SourceAuthRef` names auth material by reference (`env`, `keyring`, or
  `managed`) and rejects raw credential-shaped names.
- `SourceAuthBroker.resolve(ref, *, config, provider)` returns provider auth
  material at runtime. The broker is trusted runtime code; providers receive
  only the resolved value on `SourceFetchRequest.auth`.
- `EnvSourceAuthBroker` is the local/dev implementation. It resolves only
  `env` refs and returns `None` for unsupported broker kinds.
- Existing explicit token overrides still win, preserving current CLI and
  compatibility behavior.
- Built-in source providers consume broker-resolved auth through the existing
  `SourceFetchRequest.auth` path; no source-artifact schema change is required.

## Consequences

- Team Preview sources can depend on a stable auth seam before OAuth or managed
  service-account implementations exist.
- Third-party provider packages still run as trusted Python code when enabled;
  the broker contract prevents raw credentials from being persisted by Ambara's
  source config, but it does not sandbox provider code.
- Future managed brokers or keyring resolvers extend the runtime implementation,
  not the frozen source-artifact contract.
