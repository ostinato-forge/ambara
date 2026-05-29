# DX Scorecard

Synthetic persona scoring tracks whether each DX round improves the product.
Fifteen developer personas evaluate the README, docs, and CLI source each round.
Treat these scores as directional signals, not user research.

## Score Progression

| Persona | R1 | R2 | R3 | R4 | Adopt? | Top remaining fix |
|---------|---:|---:|---:|---:|--------|-------------------|
| Solo hobbyist | 3 | 4 | 4 | 4 | No | Split README: solo-only landing page with zero team concepts |
| Experienced Claude Code user | 5 | 6 | 6 | 6 | No | Add dry-run onboard and explain value delta over CLAUDE.md memory |
| Team lead evaluating tools | 4 | 5 | 5 | 5 | No | Add `jurati join` for team member 2-8 and Cursor onboarding |
| Junior developer told to use it | 5 | 5 | 5 | 6 | Yes | Add team-member quickstart with a provided remote URL |
| Docs-averse senior dev | 4 | 4 | 4 | 6 | Yes | Explain local git failures, especially missing git identity |
| Cursor user | 3 | 3 | 3 | 3 | No | Add `jurati onboard --client cursor` with real Cursor config |
| DevOps engineer | 5 | 5 | 5 | 5 | No | Add operations runbook with egress, rollback, incidents |
| Open source contributor | 5 | 6 | 6 | 5 | No | Add good-first-issue backlog and contributor onboarding |
| Multi-agent power user | 6 | 6 | 6 | 6 | Yes | Add explicit work claims for parallel agents |
| Non-English speaker | 4 | 6 | 6 | 6 | Yes | Add inline glossary before setup, simpler language |
| Security-conscious enterprise dev | 4 | 3 | 3 | 5 | No | Add dry-run onboarding and threat model |
| Gemini CLI user | 2 | 2 | 2 | 2 | No | Add `jurati onboard --client gemini-cli` with real config |
| Developer who just wants handoffs | 3 | 5 | 5 | 7 | Yes | Add `jurati show` and `jurati save` CLI shortcuts |
| Freelancer with many clients | 4 | 4 | 4 | 4 | No | Add isolation checks and per-project defaults |
| AI skeptic forced to try it | 5 | 5 | 5 | 4 | No | Add dry-run proof before mutating project files |

### Summary

| Round | Average | Would adopt | Key changes |
|-------|--------:|------------:|-------------|
| R1 (baseline) | 4.13 | ~3/15 | Original README and code |
| R2 | 4.60 | 5/15 | v2 contract default, local onboard, quickstart, entry example, MCP explanation |
| R3 | 4.93 | 5/15 | README restructure (daily use up, reference down), handoffs on by default |
| R4 | 4.93 | 5/15 | Security data flow doc, solo section, client table, glossary, install guide overhaul |

### What moved scores

- **Handoff-only dev**: +4 (R1:3 to R4:7). Local onboard + solo section + handoffs-on fixed the core use case.
- **Non-English speaker**: +2 (R1:4 to R4:6). Entry example and glossary helped.
- **Docs-averse senior**: +2 (R1:4 to R4:6). Install guide improvements and client table.
- **Security dev**: +1 (R1:4 to R4:5). Security data flow doc addressed the main concern.

### What didn't move

- **Cursor user (3)** and **Gemini user (2)**: Zero improvement across all rounds. No real onboarding path exists.
- **Solo hobbyist (4)**: README still feels like enterprise tooling with a solo mode bolted on.
- **Freelancer (4)**: No isolation documentation or tooling.

### Repeated Friction Themes

| Theme | Personas stuck | Fix |
|-------|----------------|-----|
| README overwhelm | Solo, docs-averse, skeptic, freelancer | Split into ~80-line landing page + separate reference docs |
| No non-Claude-Code onboarding | Cursor (3), Gemini (2), team lead | Build `--client cursor` and `--client gemini-cli` |
| No CLI inspection tools | 7 personas | Add `jurati show` and `jurati save` |
| Startup contract too big for solo | 11 personas | 2-3 line solo instruction block |
| Terminology inconsistency | 13 personas | Unify "knowledge repo" / "context repo" across all text |

### Recommended Next Round

1. Split README into focused landing page + docs/reference.md
2. Build real Cursor and Gemini CLI onboarding
3. Add `jurati show` and `jurati save` CLI commands
4. Ship a minimal 3-line solo startup instruction block
5. Unify terminology in one pass across all user-facing text
