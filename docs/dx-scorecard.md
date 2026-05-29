# DX Scorecard

Synthetic persona scoring tracks whether each DX round improves the current
artifact. Treat these scores as directional signals, not user research.

## Round 1: Local-First Onboarding And Security Review Packet

Date: 2026-05-29

Changes evaluated:

- README local-first setup with `jurati onboard --local --yes`
- solo handoffs-only positioning
- clearer team setup and client support expectations
- `jurati status`
- security/data-flow review packet
- active-handoff and restricted-entry docs alignment
- `jurati startup --format markdown` alias

### Scores

| Persona | Prior | Current | Delta | Adopt now? | Next fix |
|---------|------:|--------:|------:|------------|----------|
| Solo hobbyist | 5.0 | 7.5 | +2.5 | Yes | Add a solo handoff smoke test that proves save and recall. |
| Experienced Claude Code user | 6.0 | 8.0 | +2.0 | Yes | Add previewable, read-only-first onboarding for existing repos. |
| Team lead evaluating tools | 6.0 | 8.0 | +2.0 | Yes | Add first-class Cursor onboarding and verification. |
| Junior developer told to use it | 5.0 | 7.0 | +2.0 | Yes | Add a team-member quickstart around a provided remote URL. |
| Docs-averse senior dev | 5.0 | 7.0 | +2.0 | Yes | Explain local git setup failures, especially missing git identity. |
| Cursor user, no Claude Code | 4.0 | 6.0 | +2.0 | No | Add Cursor-first setup, config, and doctor verification. |
| DevOps engineer | 6.0 | 8.0 | +2.0 | Yes | Add an operations runbook with egress, rollback, and incidents. |
| Open source contributor | 8.0 | 8.5 | +0.5 | Yes | Keep public-docs tests aligned with new docs and improve first-issue lanes. |
| Multi-agent power user | 6.0 | 7.0 | +1.0 | Yes | Add first-class work claims for parallel agents. |
| Non-English speaker | 6.0 | 8.0 | +2.0 | Yes | Add a README Plain Words glossary before setup. |
| Security-conscious enterprise dev | 5.0 | 7.0 | +2.0 | No | Add dry-run/read-only onboarding for security review. |
| Gemini CLI user | 5.0 | 7.0 | +2.0 | Yes | Add Gemini CLI setup docs and client-specific verification. |
| Developer who just wants handoffs | 7.0 | 7.5 | +0.5 | Yes | Add a copy-paste solo handoff proof for save and pickup. |
| Freelancer with many clients | 6.2 | 7.0 | +0.8 | No | Add isolation checks and project-local defaults for client work. |
| AI skeptic forced to try it | 6.4 | 6.8 | +0.4 | No | Add a dry-run/skeptic proof before mutating project files. |

### Summary

- Average score moved from 5.77 to 7.35: +1.58.
- Adopt-now count moved from 3/15 to 11/15.
- Largest gains came from solo, team, security, and client-support clarity.
- Remaining non-adopters are Cursor-only, enterprise-security, freelancer/client-isolation, and AI-skeptic personas.

### Repeated Friction Themes

| Theme | Personas | Product implication |
|-------|----------|---------------------|
| First-class non-Claude setup | Cursor, Gemini, team lead, multi-agent | Add client-specific docs/installers and doctor checks. |
| Preview/read-only/dry-run onboarding | Claude power user, security, AI skeptic, DevOps | Let users see file diffs, permissions, writes, and egress before mutation. |
| Handoff proof | solo hobbyist, docs-averse, handoff-only, skeptic | Add an end-to-end local smoke test or transcript for save and recall. |
| Operational runbook | DevOps, security, team lead | Consolidate rollout, rollback, egress, credentials, and incident response. |
| Client/confidentiality isolation | freelancer, security, team lead | Add isolation checks and stronger warnings around global config and shared remotes. |
| Coordination beyond memory | multi-agent power user | Add explicit work claims with TTL and path conflict warnings. |

### Recommended Next Round

1. Add dry-run/read-only onboarding.
2. Add Cursor-first setup and verification.
3. Add a solo handoff smoke test.
4. Add an operations runbook.
5. Add client-isolation checks.
