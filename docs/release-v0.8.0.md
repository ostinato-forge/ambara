# Ambara v0.8.0 Release Notes

These notes describe the tagged Ambara v0.8.0 public-preview release. Keep
them aligned with the verified artifact, release proof, and actual support
surface.

## Release Shape

Ambara v0.8.0 is the public-preview hardening release. It trims the launch
surface to the parts that now have local proof:

- CLI, MCP, and file-adapter client paths, without a rich IDE panel claim.
- Local and Docker/Podman install proof, without fleet deployment claims.
- Source Preview for GitHub, GitLab, Jira, fixture JSON, and fixture-backed
  Linear and Confluence providers.
- Conservative local value accounting and quieter source-derived curation
  advisories.

## Highlights

- **Fixture-backed preview sources** - Linear issues and Confluence pages now
  register as built-in source providers for no-network public-preview fixtures.
  They flow through `SourceManager`, source conformance, central safety,
  `source-smoke`, installed proof, and Docker/Podman proof. Live Linear or
  Confluence API ingestion is not claimed in this release.
- **Docker/Podman install smoke** - the repository now includes a root
  `Dockerfile`, `.dockerignore`, and `scripts/docker-install-smoke.sh`. The
  image runs the Ambara CLI as a non-root user, executes the generated demo
  proof under `/workspace`, and smokes fixture-backed preview sources.
- **Source-aware curation relevance** - completed-artifact revalidation
  advisories now score structured evidence from labels, paths, subject areas,
  projects, tags, and titles, expose confidence, and suppress weak one-term
  matches.
- **Conservative value accounting** - local value-ledger events record
  conservative low/high token ranges alongside the existing point estimate.
- **Release proof tightening** - installed-wheel proof now exercises
  unavailable/stale/safety/noisy source paths, fixture-backed Linear and
  Confluence source smoke, startup source guidance, and
  Claude Code/Codex/Cursor/Gemini file-adapter smokes.

## Verified Before Release

- `pytest -q`
- `ruff check .`
- `mypy src`
- `uv lock --check`
- `git diff --check`
- `bash -n scripts/installed-user-path-smoke.sh scripts/docker-install-smoke.sh`
- changed-file pre-commit hooks
- installed-wheel smoke from `docs/release-proof.md`
- Docker/Podman smoke from `docs/release-proof.md` when a container engine and
  base image cache are available

## Known Limits

- Linear and Confluence are fixture-backed public-preview providers only. They
  prove source shape, policy, safety, and rendering; they do not fetch live
  workplace APIs.
- Docker/Podman support is a local CLI image and smoke path, not Compose,
  Kubernetes, swarm, fleet rollout, or managed deployment orchestration.
- IDE/client support remains CLI/MCP/file-adapter proof. Rich IDE-native panels
  remain outside this release.
- Notion, Slack, Sentry, Figma, and broad workplace search remain deferred.
