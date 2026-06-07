# Ambara v0.7.0 Release Notes

These notes describe the tagged Ambara v0.7.0 release. Keep them aligned with
the verified artifact, release proof, and actual support surface.

## Release Shape

Ambara v0.7.0 is the cross-agent proof release. It keeps the v0.6.0 multi-forge
foundation, then makes three public claims testable:

- Ambara surfaces value ambiently, without end-user pricing configuration.
- Ambara can be extended with third-party signal providers.
- Ambara's file-adapter path works across named agent clients.

## Highlights

- **Ambient token value** — startup packets now include a local 7-day token
  savings rollup by default. Currency remains managed deployment metadata only;
  Ambara does not invent a universal dollar estimate.
- **Signal provider registry** — GitHub, GitLab, and Jira remain built-in
  signal providers, while third-party packages can register additional
  providers via the `ambara.signal_providers` Python entry-point group.
- **Client smoke harness** — `ambara client-smoke` verifies the plain
  file-adapter path for `claude-code`, `codex`, `cursor`, and `gemini` against
  a local/no-network knowledge repo.
- **Production-day simulation** — the test suite now includes a deterministic
  100-user / 100-agent workday with GitHub, GitLab, and Jira signals feeding the
  same shared context layer.
- **Release truth tightening** — Python 3.14 is included in CI and release
  test matrices, public docs explain the automatic local value ledger, and
  token scanning covers current GitLab and Slack token families.

## Verified Before Release

- `pytest -q tests/test_prod_day_simulation.py`
- `pytest -q tests/test_cli.py::TestAdoptionHelpers::test_client_smoke_writes_file_adapter_context`
- `pytest -q tests/providers/test_registry.py tests/providers/test_fixture_signals.py`
- `pytest -q`
- `ruff check .`
- `mypy src`
- installed-wheel smoke from `docs/release-proof.md`

## Known Limits

- `client-smoke` proves Ambara's file-adapter contract, not real UI automation
  inside each external client.
- Third-party signal providers are discovered and invoked through entry points,
  but their own network/auth behavior remains the provider package's
  responsibility.
- Currency estimates remain intentionally absent unless a managed deployment
  supplies its own token price.
