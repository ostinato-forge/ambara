# Ambara v0.5.1 Release Notes

These notes are the source text for the Ambara v0.5.1 follow-up release.
Keep them aligned with the verified artifact and the actual proof path.

## Release Shape

Ambara v0.5.1 is a trust-and-reliability release.

v0.5.0 established the product and public release bar. v0.5.1 tightens the
parts of that promise that most affect the human user:

- write receipts say what actually happened
- GitHub Action capture is bootstrapped from declared remote/token inputs
- capture paths share the content-policy contract used by interactive writes
- signal refresh behavior is consolidated across coordination, curation, and
  snapshot surfaces

This release does not widen Ambara's boundary. It makes the existing product
more trustworthy.

## Highlights

- **Honest branch-only receipts** — when Ambara can only save to a review
  branch, the response now says that no pull request was created instead of
  sounding equivalent to PR-backed review.
- **Real Action bootstrap** — the GitHub Action prepares the local knowledge
  repo from `AMBARA_KNOWLEDGE_REMOTE`, applies authenticated GitHub remotes
  when a token is supplied, and fetches the configured main branch before
  capture.
- **Content-policy parity for capture** — commit capture now evaluates the
  content-policy gate in addition to secret scanning. Review-triggering content
  escalates out of low-ceremony flow; blocked content is rejected.
- **Shared signal refresh path** — coordination, curation, and compiler-mode
  snapshot flows now share one cache/health refresh helper instead of maintaining
  separate copies of the same logic.

## Why This Matters

Ambara's user is the human developer or team. The agent is the operating
surface Ambara has to steer.

That means trust is not only about storage or retrieval quality. It is also
about whether Ambara tells the truth about write outcomes, applies the same
safety rules on every documented path, and gives the human a product they can
verify directly through demo/proof surfaces.

v0.5.1 improves those properties without turning Ambara into a broader product.

## Verified Before Release

- targeted receipt, capture, and action tests pass
- coordination/curation/snapshot refresh regression tests pass
- Ruff and mypy pass on the touched server, capture, and action modules
- the existing local demo and release proof still pass

## Known Limits

- branch-only fallback is now explicit, but it is still a fallback; it is not a
  created pull request
- GitHub Action auth wiring is GitHub-focused, not a generic git credential
  abstraction
- Ambara still depends on agent steerability for its best interactive
  experience, even though the CLI, static HTML, and file surfaces reduce that
  dependency
