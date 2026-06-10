# ADR 0001: Source-artifact schema frozen (v1)

- Status: accepted
- Date: 2026-06-09

## Context

The source kernel is the single coordination path for all source families
(GitHub, GitLab, Jira, fixture), and two upcoming workstreams build directly
against the shape of its artifacts: token accounting under uncertainty (#174)
classifies artifact text spans from structural markers, and semantic curation
relevance (#175) matches artifact fields (title, labels, subject refs, subject
areas) against knowledge entries. Neither can build against a moving contract.
Freezing this surface is the exit gate that opens that work.

## Decision

The source-artifact contract in `ambara.sources.types` is frozen as **v1**:

- `SourceArtifact` and its component types `SourceProvenance` and
  `SourceOmissions`
- the provider exchange types `SourceFetchRequest`, `SourceFetchResult`,
  `SourceInstanceConfig`, `SourceBudget`, and `SourceCapabilities`
- the vocabulary enums `SourceCategory`, `BodyPolicy`, `IdentityPolicy`,
  `TextTrust`, `Sensitivity`, `AuthMode`, and the
  `SourceSubjectRefsStatus` literal

Frozen means: field names, field types, and enum member values do not change,
and nothing is added or removed, without a new ADR that supersedes this one.
The guard test `tests/sources/test_artifact_schema_freeze.py` pins the exact
surface and fails on any drift; updating that test is only legitimate in the
same change that lands the superseding ADR.

The conformance kit (`ambara.sources.conformance`) and truthful-empty refresh
semantics are proof obligations over this contract and are unaffected.

## Consequences

- #174 and #175 may start: their input shapes cannot move underneath them.
- Team Preview and Optional Preview providers implement against v1 as-is;
  provider capability growth happens inside the existing capability flags, not
  by reshaping artifacts.
- A future field addition is a deliberate event (ADR + guard-test update in
  one reviewed change), never a drive-by edit.
