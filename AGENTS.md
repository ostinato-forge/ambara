# Agent Instructions

The full operating contract for this repo lives in **`CLAUDE.md`** (architecture,
purity boundary, key invariants, quality bar, security policy, conventions). Read
it first. This file restates the hardest non-negotiables so any agent that only
reads `AGENTS.md` still gets them:

- This is a serious product. Claims never outrun proof: every public claim has a
  matching passing test, and the README/support-matrix claim nothing a test does
  not back.
- Build full scope, no cuts; sequence hard work, never drop it. Roadmap is
  `planning/v2-rock-solid-plan.md` (local, not committed).
- `core/` is pure (zero I/O); side effects live in `git/`, `sources/runtime`,
  `server*`, `cli*`. Do not import source/git I/O into `core/`.
- Branch first, never commit to `main`; PR + review for all changes. Conventional
  Commits, DCO sign-off (`git commit -s`), SPDX headers, mypy strict + ruff +
  pytest green. No Claude attribution in commits or PR bodies.
- Commit real work only, not planning docs or hygiene churn. Stage intentional
  files; never `git add .`. Preserve unrelated local changes.
- Do not add new commands to `cli.py` or new `signal_*` compatibility shims (both
  are being removed).
- Read `docs/agent-operating-policy.md` before any CI/workflow/release change. On
  an exhausted `$0` Actions budget, land workflow-only fixes with `[skip ci]`.
- Never commit secrets, local paths, or private hostnames. Name the verification
  commands you actually ran.
