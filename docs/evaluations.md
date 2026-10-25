# Evaluations and decisions

Two subagents evaluated these tools on 2026-10-24. The briefs asked for neutral evaluations: the
tracker agent was told nothing about this use case, and the orchestrator agent was given only
neutral criteria such as platform and programmability. Both read the tools' docs and source; no
tool was installed or run. The condensed findings are below; the decisions come after them.

## 1. Trackers: Beads vs. Task Master vs. CCPM

| | Beads (`bd`) 1.3.2 | Task Master 0.43.1 | CCPM (v2 skill) |
| --- | --- | --- | --- |
| Storage | Dolt DB in `.beads/` (since v0.55, no longer plain git; JSONL is export only) | `.taskmaster/tasks/tasks.json` | Markdown + YAML in `.claude/`, synced to GitHub Issues |
| Hierarchy | epic/task/subtask, max depth 3, hash IDs | task → subtask (2 levels) + tags | PRD → epic → task (GitHub sub-issues) |
| Dependencies | 4 blocking + 6 non-blocking types (incl. `discovered-from`), cross-repo `external:` | 1 (prerequisite) | `depends_on` (same epic only), `conflicts_with`, `parallel` |
| Ready set | `bd ready` (+ `--explain`), atomic `--claim` | `next` (deps met, by priority) | Scripts exist but are **broken**: tasks with deps never become ready (#1027) |
| Notes / handoff | notes with append, design, acceptance, comments, `bd prime` context injection | appending notes needs an LLM call | `updates/` files + GitHub comments |
| Needs an LLM | No (optional AI compaction/dedupe needs an API key) | Yes for parse/expand/complexity/update (can use Claude Code CLI OAuth) | No; the host agent does the work |
| Scriptable | Stable `--json` contract (envelope becomes default in v2.0) | Partly | Files readable, scripts text-only |
| Maturity | Post-1.0, active (commit on the day checked), 28k★, **1,071 open issues**, Dolt lock/migration churn, WSL lock issue on `/mnt/c` | **Stalled** since Apr/May 2026, unpatched MCP path-traversal and file-corruption reports, Commons Clause, Sentry on by default | Last real commit Mar 2026, no releases, past installer security incident (v1) |

What each does best: Beads has the dependency graph and the agent ergonomics (ready, claim,
prime, discovered-from). Task Master turns a spec into tasks, with complexity sizing and
"next". CCPM uses GitHub Issues as the visible audit trail and puts a worktree on each epic.

### Decision: GitHub Issues, improved, with SQLite for harness state

The owner is not attached to the epf3 GitHub tracker, so a second, use-case-driven report
re-checked every option against source and the live API:
**[tracker-report.md](tracker-report.md)**, including when to switch to Beads. The short
version is below. It was originally written as "compose our own" and still holds.

1. **epf3-skills already *is* the CCPM-shaped part, done properly.** Its `to-tickets` and
   `manage-tickets` write epics and tickets to GitHub Issues with native sub-issues and
   `blockedBy` links, and compute the frontier in one `gh` + `jq` query
   (`manage-tickets/github.md`). That covers CCPM's strength without CCPM's broken ready
   logic. Adding any second tracker would create two sources of truth for the same tickets, and
   would break epf3's rule that "every tracker write is a gh command in github.md".
2. **We take the best ideas from Beads, Task Master and CCPM, implemented in about 300 lines of Python:**
   - from **Beads**:
     - the ready set with an explanation (`sb why <n>` says which blocker or gate holds it)
     - depth capped at 3, which matches our fan-out rule
     - `discovered-from` (epf3's `discovered` label plus a link)
     - append-only notes (our context-pack handoffs)
     - `bd prime`-style compact context injection (our context pack)
   - from **Task Master**:
     - a size estimate at creation (S/M; L must split)
     - a deterministic `next` (our scheduler score)
   - from **CCPM**:
     - zero-token status scripts (`sb status`, the digest)
     - worktree isolation
     - the idea of `conflicts_with` (later: don't run two sibling tickets that touch the same
       area on parallel branches)
3. **Harness-only state** lives in `switchboard.db`: sessions, cache clocks, budgets, runs,
   questions and the message map. epf3's tickets stay clean, and it says "not a scheduler: no
   priorities, milestones, owners or dates" for a reason.
4. **Claiming is safe without atomic claims.** GitHub has none, but `sb-tick` is the single
   orchestrator behind a lock, which is exactly epf3's "workers never claim" rule.
5. **Cost.** `gh` calls cost no tokens, and a few calls per tick is far below GitHub's rate
   limits. If GitHub is unreachable, the tick exits at its gate.
6. **Escape hatch.** Everything goes through the `Tracker` adapter. If GitHub latency or limits
   ever hurt, Beads (on WSL's ext4, not `/mnt/c`) is the first candidate backend.

## 2. Orchestrators: Vibe Kanban vs. Claude Squad vs. Conductor

| | Vibe Kanban | Claude Squad | Conductor |
| --- | --- | --- | --- |
| Status | **Sunsetting**: the company shut down (Apr 2026); kanban/issues retired, export-only; community-maintained | Active, small team (v1.0.20, Aug 2026) | Active commercial, weekly releases (0.91, Oct 2026) |
| UX | Local web UI | tmux TUI | Native **macOS-only** app + iOS |
| How it runs Claude | Headless `-p` stream-json, worktree per workspace | Interactive TUI in tmux, worktree per session; "autoyes" screen-scrapes permission prompts | Bundled Claude Code; mode undocumented |
| Subscription login | Yes | Yes | Yes (or API key) |
| Windows / WSL2 | Builds; open WSL path bugs | Native Windows broken; WSL2 = Linux build, undocumented | **No** Windows/Linux |
| Programmatic control | Local MCP (app must run); REST undocumented | **None** | REST/CLI/MCP, but **cloud workspaces only**, Pro $50/mo |
| Tracker integration | None (PRs only) | None | GitHub Issues / Linear → workspace |
| Scheduled / unattended | No | No | Cron routines, cloud only |
| Notifications / LAN / chat | Browser/OS notifications; `HOST=0.0.0.0`; no chat | None | iOS remote control via relay; no LAN UI |
| License / telemetry | Apache-2.0; PostHog+Sentry (re-enabled on login, #3482) | AGPL-3.0 + CLA; none found | Proprietary; PostHog, no opt-out documented |

### Decision: none of them is the backbone

- **Conductor** fails the platform constraint (macOS only), and its automation is cloud-only and
  paid.
- **Claude Squad** cannot be driven by a script, and it is interactive by design. Its useful
  idea: harness sessions could optionally run inside named tmux sessions, so the owner can attach
  and watch one live.
- **Vibe Kanban** came closest technically (headless `-p`, worktrees, a local MCP), but it is
  sunsetting and lost its local kanban. Ideas worth taking: its diff-review-with-inline-comments
  flow, a future LAN dashboard feature where the owner comments on a diff and the comment
  becomes an answer; and its MCP tool shape (`start_workspace`, `run_session_prompt`,
  `get_execution`) as a template if `sb` ever exposes an MCP server.
- All three confirm **worktree per task** as the standard isolation. switchboard does the same.

## 3. Phone clients and approval tools (not formally evaluated)

Happy, Omnara, HumanLayer and Claude-Code-Remote target interactive sessions or hosted relays.
switchboard's Telegram bot covers the same ground with no hosted component. Look at them for UX
ideas only.

## 4. Claude Code built-ins (adopted)

| Feature | Use |
| --- | --- |
| Headless `claude -p`, `--session-id`, `--resume`, `stream-json` | The run itself, usage/TTL measurement, and the usage percentages (`rate_limit_event`) |
| Hooks (`PostToolUse`, `PreToolUse`, `Stop`, `SessionStart`) | Budget enforcement, guards, the harness-mode brief |
| Headless `/usage` | Usage percentages when no run has happened recently; no model call ([verification.md](verification.md) §2) |
| Channels (v2.1.80+, research preview) | Optional live lane, on a second bot |
| `/remote-control` | The owner's fallback away from home |
| Cloud routines (`/schedule`) | Later, for `cloud_ok` tickets |
