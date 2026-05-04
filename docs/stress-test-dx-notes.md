# Stress Test DX Notes

Issues observed during multi-agent stress testing. These inform Jurati improvements.

## Round 0 — Setup

1. **MCP server requires manual `/mcp` connect** — `.mcp.json` is present in the repo but the agent doesn't auto-connect the jurati server. User had to run `/mcp` first.

2. **Agent doesn't know to use jurati tools without prompting** — asking "call status()" wasn't enough. User had to say "jurati mcp — call status()" to direct the agent to the right toolset.

## Round 1 — Baseline Context (Alice)

3. **Agent can't discover jurati tool names** — Alice's agent tried `claude mcp list-tools jurati` (not a valid command), failed, and never retried. It doesn't know the MCP tool name format (e.g., `mcp__jurati__query`).

4. **Agent falls back to git log instead of jurati** — Without being able to call jurati tools, the agent used `git log`, `git branch`, and local file reads. This is exactly the "without jurati" baseline — it only sees what's in the local repo.

5. **Wrong conclusion from local-only context** — The agent concluded "you should be clear to refactor without stepping on anyone's toes" — when Bob's PR on test-web-frontend is literally blocked waiting on Alice's auth changes. This is the coordination failure jurati is supposed to prevent.

6. **`.remember` hook errors** — Every bash command triggers a non-blocking error: `.remember/logs/hook-errors.log: No such file or directory`. Noisy but not blocking.

### Root cause analysis (Round 1, attempt 1)
The agent has jurati MCP tools available (status() worked when prompted explicitly) but doesn't proactively discover or use them when asked a general question about team knowledge. The tool names aren't intuitive enough for the agent to guess, and there's no CLAUDE.md or system prompt in the test repo telling the agent to use jurati.

## Round 1 — Baseline Context, attempt 2 (with CLAUDE.md)

7. **Agent ignores CLAUDE.md "call context() first" instruction** — CLAUDE.md explicitly says "Before starting any task, call context()" but Alice's agent still used local git branches/diffs instead. It found the alice/auth-refactor branch locally and gave reasonable advice from that, but missed all jurati-sourced context.

8. **No knowledge entries surfaced** — jwt-auth-strategy, secure-by-default, auth-refactor project, cross-repo-coordination workflow — none appeared. These would have given the agent richer context about team decisions.

9. **No cross-repo PR signals** — Bob's test-web-frontend#1 PR (blocked, waiting on auth refactor) was not mentioned. The agent has no idea a downstream consumer is waiting.

10. **Local git context gives partial picture** — The agent correctly identified the open branch and its changes, but concluded "coordinate with Alice" without knowing the broader dependency chain. Jurati would have shown that this is part of a multi-repo auth migration with a defined coordination workflow.

11. **MCP tool calls prompt for user approval** — `context()` is a read-only operation but Claude Code still asks "Do you want to proceed?" This breaks the ambient experience — if the agent has to ask permission before checking team context, developers will either deny it (friction) or always-allow it (security training to ignore prompts). Read-only jurati tools should be auto-approved. The CLAUDE.md should include an allowlist or the `.mcp.json` should declare tool permissions.

12. **Bob's agent followed CLAUDE.md, Alice's didn't** — Same CLAUDE.md content, different agent behavior. Bob's agent called `context(goal="Update login flow...", repo="ostinato-forge/test-web-frontend")` as its first action. Alice's agent went straight to git/file exploration. Non-deterministic compliance with CLAUDE.md instructions is a reliability problem.

## Round 1 — Baseline Context, attempt 2 (Bob — SUCCESS)

Bob's agent followed CLAUDE.md and called `context()` first. Results:

**What surfaced correctly:**
- auth-refactor project entry with explicit "Bob should not start frontend auth changes" warning
- Both coordinated PRs: test-api-service#1 (Alice's auth refactor, open) and test-web-frontend#1 (Bob's placeholder, open)
- Proposed migrate-to-oauth2-pkce decision flagged as a constraint ("do not begin migration work yet")
- Agent correctly recommended waiting for API PR, offered non-blocked prep work
- Cross-repo dependency chain was fully visible

**What still had friction:**
- `.remember` hook errors on every tool call (noisy, non-blocking)
- Agent used `gh pr view` to get PR details after context() — the PR signal summaries from context() were enough to identify the PRs but agent wanted full details
- Explore subagent spent 33 tool uses / 1 min exploring local code structure (could have been skipped if context() was trusted more)

**Conclusion:** When the agent follows CLAUDE.md and calls context(), the full coordination picture appears. The problem is reliability of that first step.

## Round 2 — Active Context Recording (Alice)

13. **Global vs project MCP config conflict kills server** — Server name `jurati` defined in both global (`~/.local/bin/jurati serve`) and project (`.mcp.json` → `jurati-mcp.sh`) scopes. Claude Code warns about conflicting endpoints and OAuth token scope, then the server fails to connect. Fix: removed global entry with `claude mcp remove jurati -s user`.

14. **Agent can't discover tools when MCP server fails** — Alice's agent tried `listMcpResources`, got nothing, then gave up and suggested the user call record() manually via shell pipe. The agent correctly identified what to record and gave reasonable fallback advice, but the core value (ambient context sharing) broke.

15. **Agent suggested raw JSON pipe to MCP server** — When tools weren't available, the agent suggested `echo '{"method": "tools/call"...}' | jurati-mcp.sh`. Creative but terrible DX. Users should never see MCP protocol details.

## Round 2 — Active Context Recording (Alice, after MCP fix — SUCCESS)

16. **record() type self-correction works** — Agent tried type="decision" first, jurati rejected it (L2 requires propose()), agent self-corrected to type="active" (L0). The escalation model error messages are clear enough for the agent to recover.

17. **Took 4 record() calls total** — 1 failed (wrong type), then 3 more to succeed. Not clear why 3 additional calls were needed — may be retries due to parameter adjustments. Should investigate the tool response to understand what the agent was correcting.

18. **Approval prompt on record()** — write operations reasonably need approval, but it adds friction. Could auto-allow after first approval per session.

19. **Entry recorded and cross-tagged** — Entry 1a1a7b62c5eb created on jurati/active/dev-alice/ ref, tagged for both test-api-service and test-web-frontend. Expires May 11.

## Round 2 — Active Context Check (Bob — FAILURE)

20. **Bob's agent didn't call jurati at all** — went straight to `gh api` to check PR status. 6 GitHub API calls, zero jurati tool calls. Alice's active context entry (1a1a7b62c5eb) was completely invisible.

21. **Bob's jurati MCP also failed** — same global config conflict. Global entry existed in TWO places: `~/.claude.json` (removed earlier) and `~/.claude/mcp.json` (found now). Both need to be removed for project-level config to work.

22. **Without jurati, agent concluded "no new activity"** — the agent said "No Jurati records with updates from Alice" which is exactly wrong. Alice recorded active context 2 minutes ago. The agent didn't know because it couldn't reach jurati and didn't try.

23. **Agent's fallback (GitHub API) is plausible but incomplete** — it correctly checked PR state, commits, comments, reviews. But active context lives on git refs, not GitHub PRs. The agent has no way to discover active refs without jurati.

## Round 2 — Active Context Check (Bob, after restart — SUCCESS)

24. **Cross-agent active context propagation works** — Alice recorded active context, Bob's agent found it via `context()` + `query(topic="Alice auth refactor")`. All details surfaced: token expiry change, rotation_id, grace period, affected files.

25. **Agent called both context() and query()** — Used context() for broad awareness then query() for targeted search. Good tool selection.

26. **Correct conclusion with full cross-repo picture** — Agent told Bob to wait for API PR, listed exactly what needs to change in frontend when it lands, flagged OAuth2 PKCE as future context. This is the designed experience working end-to-end.

27. **Still prompted for query() approval** — Second jurati read-only tool call still triggered "Do you want to proceed?" Even after approving context() earlier in the session.

## Round 3 — Conflict Detection (SUCCESS)

28. **CRITICAL: jurati-mcp.sh kills ALL jurati processes on reconnect** — Line 28: `pkill -f -u "$(id -u)" "jurati serve"`. Every `/mcp` reconnect in any terminal kills every other terminal's jurati server. This is why servers kept "disconnecting" — they weren't disconnecting, they were being killed by sibling terminals. **This is a showstopper for multi-agent use.** Fixed by removing the pkill line.

## Round 3 — Conflict Detection Results

29. **Alice: record() worked first try** — Breaking change recorded (dad3eb903bf2), cross-tagged all 3 repos. Agent insight about silent undefined in JS frontends was spot-on.

30. **Bob: agent re-checked context before continuing** — Called `sync()` + `context()` proactively. This is the correct behavior — re-check before writing more code.

31. **Bob: caught breaking change and auto-fixed** — Found `refresh_token → token` rename, immediately updated `RefreshResponse` type. Also flagged ambiguity about whether `LoginResponse` is affected (smart — the active entry only mentioned refresh endpoint).

32. **Bob: recommended waiting** — "The backend PR is still open, so more changes like this could come." Correct guidance based on the coordination signals.

33. **Agent exposes entry lifecycle to developers** — After recording, Alice's agent listed entry IDs (`1a1a7b62c5eb`, `dad3eb903bf2`) and told her to "expire them once the changes land." Developers should never see entry IDs or manage entry lifecycle — that's jurati's job. Active entries already have `expires_at`; the agent should either auto-expire on PR merge or handle it silently. This is implementation detail leaking into the developer experience.

**This is the designed experience working end-to-end.** Alice changes a contract, records it, Bob's agent catches it before shipping broken code. Without jurati, Bob would have committed code reading `response.refresh_token` from the refresh endpoint and gotten `undefined` at runtime.

## Round 4 — PR State Change (Bob — SUCCESS)

34. **Agent correctly detected PR merge and cleared blocker** — Called `sync()` + `context()`, confirmed backend PR merged, referenced auth-refactor project entry saying "that's now done."

35. **PR signal effect surfaced** — Agent mentioned `effect: "handoff"` for Bob's frontend PR. The classification system is working and the effect names are meaningful to the agent.

36. **Agent combined jurati + GitHub API** — Used `sync()` and `context()` for knowledge/signals, then `gh pr view` for detailed PR state. Belt-and-suspenders approach is reasonable but shows jurati's PR signal summaries may not include enough detail (merge timestamp, etc.).

37. **Consistent ambiguity tracking** — Agent flagged the LoginResponse vs RefreshResponse question again, same as Round 3. Good continuity within the session.

## Round 5 — Knowledge Proposal (Alice — FUNCTIONAL SUCCESS, DX ISSUES)

38. **propose() + expire() worked in one shot** — Agent called propose() to create L2 decision PR, then expire() on both active entries. All 3 operations succeeded. PR #10 created on eparenti/jurati-knowledge.

39. **Agent tells developer to merge knowledge repo PRs** — "review and merge PR #10, then run sync()." Developer should never manage the knowledge repo directly. L1 auto-merges; L2/L3 review should happen within the knowledge repo's own workflow, not be the developer's chore.

40. **Entry IDs exposed again** — Same issue as #33. Developer sees `1a1a7b62c5eb` and `dad3eb903bf2`. These are implementation details.

41. **Too verbose** — Multi-paragraph explanation of L0→L2 lifecycle. The developer asked to record a decision, not to learn about jurati internals. The agent should confirm the action in one sentence: "Recorded as a team decision — PR open for review."

42. **Prompt burden** — The developer had to say "Propose a decision entry documenting the new token rotation strategy so future agents know about it." Ideally the agent should know to promote active context to a decision when work completes, or at minimum the prompt should be shorter: "Record the token rotation approach as a team decision."

### Root cause analysis (Round 2)
The `.mcp.json` approach works when there's no global config conflict. But many developers will have jurati installed globally AND have project-level configs. The server name collision is a Claude Code limitation — it doesn't merge or prefer project-level, it fails. This needs to be documented in the setup guide, or the project-level config should use a different server name (e.g., `jurati-project`).

### Root cause analysis (Round 1, attempt 2)
CLAUDE.md guidance is too passive for some agent runs. The agent treats "Before starting any task, call context()" as a suggestion, not a requirement. When the agent's default behavior (read files, check git) kicks in first, it may feel it has sufficient context without calling MCP tools. Bob's agent followed the instruction; Alice's didn't — suggesting the issue is stochastic, not systematic. May need stronger CLAUDE.md language, hooks, or jurati needs to inject itself into the agent's workflow more aggressively.
