# Jurati

[![Development Status: 4 - Beta](https://img.shields.io/badge/Development%20Status-4%20--%20Beta-yellow)](https://pypi.org/classifiers/)

AI coding agents forget everything between sessions. Jurati fixes that.

## Get Started

```bash
pip install jurati
cd your-project
jurati onboard --yes
```

Restart your coding agent. Say "save where I left off" when you're done.
Next session, the agent already knows what happened.

## What You Say

You don't learn an API. You just talk to your agent:

```text
"Save where I left off."
→ Saved. Next session picks it up.

"We decided to use gRPC for internal services. Record that."
→ Saved as a team decision.

"What did we decide about the auth migration?"
→ Agent checks and tells you.
```

## How It Works

You save handoffs and decisions through your coding agent. Jurati stores them
as Markdown files in a git repo, indexes them, and serves the relevant ones
back to the agent at the start of each session. You don't need to manage
any of that.

For solo use, the context repo stays local. For teams, point it at a shared
git remote and decisions go through PR review.

## Team Setup

```bash
jurati onboard --remote git@github.com:your-org/team-context.git
```

Team members use the same command with the same remote URL.

## Privacy

Jurati does not log what agents read, track who's online, or create activity
feeds. It only stores what you explicitly ask it to save.

## More

| | |
|-|-|
| [Reference](docs/reference.md) | Architecture, tools, entry types, configuration, CLI |
| [Install and Troubleshooting](docs/install-troubleshooting.md) | Setup details and common fixes |
| [Security Data Flow](docs/security-data-flow.md) | What Jurati reads, writes, stores, and sends |
| [Contributing](CONTRIBUTING.md) | Development setup, testing, code style |
| [DX Scorecard](docs/dx-scorecard.md) | Persona-based DX tracking |

Apache 2.0 — see [LICENSE](LICENSE).

This is a personal project. It does not represent the views, policies, or
endorsement of my employer.
