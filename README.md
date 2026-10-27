# switchboard

**Claude prompts you, not the other way round.**

switchboard is a harness that runs on the laptop. It keeps Claude Code working through every side
project in the background, a small slice at a time, and gets in touch with the owner only when
it needs a decision. The owner answers from their phone in a Telegram thread. The answer is routed
back to the ticket that asked, and the next tick acts on it.

The name comes from the old telephone switchboard. An operator sat between many lines and
connected each call to the right line. Here the lines are repos, tickets and Claude sessions, and
the calls go both ways: questions from agents to the owner, and answers and ideas from the owner
to the right agent.

> Status: design only. No code exists yet. These docs are the brief for the agents that will
> build it. Start with this file, then [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## 1. The idea in one paragraph

A tick fires every ~30 minutes. Each tick, a scheduler picks one ticket that is ready (not
blocked) from one repo and runs one budgeted, headless Claude Code session on it. The session
works until its time or token budget runs low, commits, and stops. The harness writes the handoff
for the next run itself, with the cheapest model, and only when the next run starts cold. When the
session needs the owner (a product-behaviour question, an architecture choice), it sends a
fixed-format message to Telegram and marks that ticket blocked. The next tick works a different
branch of the ticket tree. The owner's replies, sent from the phone whenever convenient, unblock
those tickets. Progress stops only when every branch is waiting on the owner. The owner reads
neat tickets and a short decision log, not chat transcripts. The full Claude Code history is
still there to inspect in VSCode.

## 2. Hard constraints (owner's words, non-negotiable)

1. **No server and no API-key token spend.** Everything drives the owner's own Claude Code CLI
   on the laptop (WSL2) with the existing claude.ai subscription login. There is no Anthropic
   API key and no hosted backend. switchboard only ever spawns the unmodified `claude` binary:
   it never reads `~/.claude/.credentials.json` or calls Anthropic endpoints with the
   subscription token, and only the owner can command it. That is what keeps unattended use
   within the terms ([docs/verification.md](docs/verification.md) §1).
2. **The laptop version comes first.** Cloud routines (`/schedule`) come later and are optional,
   used only if they are simple.
3. **Burn as few tokens as possible.** The default is deterministic code (Python, `gh`, SQLite,
   regex, BM25). An LLM is the fallback, not the first resort.
4. **The harness is never the blocker.** Every deterministic step that can be unsure (a
   confidence below threshold, a parse failure, two sources disagreeing) has an LLM fallback:
   a short, low-effort session (cheap model, few turns, strict JSON output). It resolves the
   step, and the pipeline carries on. If that also fails, the owner gets asked; nothing fails
   silently.
5. **Async first.** This is not a remote control. `/remote-control` remains the owner's
   fallback when away from home (rare; the owner works from home).
6. **Windows + WSL2.** A finely scoped Windows/WSL automation is acceptable: Task Scheduler,
   `wsl.exe`, systemd user units in WSL.
7. **Low friction.** Messages carry fixed metadata (repo, ticket, category, urgency, thread).
   Answering a message is a reply or a button tap. No digging through chats to find what Claude
   is waiting on.
8. **Python** for the daemon, the tick runner, the scheduler, the hooks and every CLI the agents
   call.

## 3. Preferences and decisions so far

| Topic | Decision | Where |
| --- | --- | --- |
| Messaging | **Telegram bot**. One forum topic per repo, reply-to threading, inline buttons, long polling (no inbound ports, so it also works away from home) | [docs/telegram.md](docs/telegram.md) |
| Claude Code integration | Headless `claude -p` with `--session-id` / `--resume`, hooks for budgets, the stream-json `rate_limit_event` for usage percentages, and Channels as an optional live lane. Every flag was checked on 2.1.310 ([docs/verification.md](docs/verification.md)) | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Sessions vs. cache | Start fresh with a compact context pack by default. Resume only while the prompt cache is warm. Dynamic text stays out of the cached prefix | [docs/prompt-cache.md](docs/prompt-cache.md) |
| Scheduling | Deliberately **unfair**: finish open work (and use warm caches) before starting new work, with a starvation floor so every repo gets some ticks | [docs/scheduler.md](docs/scheduler.md) |
| Fan-out | Hard limits enforced by code (depth, children per parent, open per repo), not by prompts | [docs/scheduler.md](docs/scheduler.md) |
| Routing new messages | Deterministic routing first (topic, then tag, then BM25 over repo READMEs). If that is unsure, a cheap router (Haiku 5.5, low effort) rewrites the message into a clean prompt and picks the repo and the skill. If the router is unsure too, switchboard's own `/triage` skill runs on the message verbatim | [docs/telegram.md](docs/telegram.md) |
| Tracker | **Decided: our own tracker on GitHub Issues + SQLite**, with the best features of Beads, Task Master and CCPM built in. Generous labels; no GitHub issue per question. Orchestrators are out | [docs/tracker.md](docs/tracker.md) (build brief), [docs/tracker-report.md](docs/tracker-report.md) |
| Scope | Apps never carry the harness: `harness-mode` and its guard install only with `setup.py --harness` into switchboard's slots; `/triage` lives in this repo | [docs/skills-extensions.md](docs/skills-extensions.md) §0 |
| Reach | Every git repo under `side-projects`, switchboard and epf3-skills included. switchboard runs from an installed release, so editing itself is safe | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) §6b |
| Skills | Every repo uses [`epf3-skills`](../epf3-skills/). switchboard adapts to it, plus a short list of proposed extensions | [docs/skills-extensions.md](docs/skills-extensions.md) |
| Laptop off / limits exhausted | That tick is skipped. On boot the day's round-robin restarts. Nothing runs in the cloud for now | [docs/scheduler.md](docs/scheduler.md) |

## 4. What makes Claude ask the owner something

Every outbound message has one **category**. The category picks the skill that formats the
message and the gate it waits on. Agents never name a category: they pass a question kind
(`behaviour`, `architecture` or `gate`) to `sb ask`, which maps it to `BEHAVIOUR`, `ARCH` or
`GATE`. The other categories are sent by switchboard itself.

| Category | Trigger | Expected reply |
| --- | --- | --- |
| `BEHAVIOUR` | How a feature should behave for the user of an app | pick an option / free text |
| `ARCH` | How to implement it: libraries, data model, service boundaries | approve / pick / veto |
| `UTIL` | End of a usage window, day, week or month with budget left: "X% of your budget remains, review your open action items" | optional: add or reprioritise work |
| `SCHEDULED` | Output of a recurring job, such as *suggested features* or *codebase cleanup* | accept / reject per item |
| `GATE` | A gate the epf3 skills already have: brainstorm round, experiment card, PR ready to merge, production `yes` | the gate's answer |
| `HARNESS` | switchboard itself is unsure (routing ambiguity, a corrupt handoff, a stuck ticket) | a one-tap fix |
| `DIGEST` | Daily summary: what moved, what is waiting, the decision log | none |

## 5. Component map

```
 Phone ── Telegram (topics: one per repo + Inbox + Digest + Usage)
            ▲  sendMessage / buttons                │ getUpdates (long poll)
            │                                       ▼
   sb ask (CLI the agent calls)            sb-inbox (daemon, no LLM on the hot path)
            ▲                                       │ reply → ticket, new msg → route
            │                                       ▼
   ┌────────┴──────────── state ───────────────────────────────────┐
   │ tracker (GitHub Issues per repo, see evaluations)             │
   │ switchboard.db (SQLite): tick log, budgets, sessions,         │
   │   cache clocks, message↔ticket map, decision log, queue       │
   │ context packs: ~/.switchboard/packs/<repo>/<ticket>.md        │
   └────────┬──────────────────────────────────────────────────────┘
            ▼
   sb-tick (every 30 min; the clock is open, see ARCHITECTURE.md §6)
     lock → laptop/limit checks → scheduler picks ticket → build prompt
     → claude -p … (--resume if cache warm, else fresh + context pack)
     → hooks enforce budget → status + Next: line → log + digest
     (handoff built later by Haiku 5.5 low, only if the next start is cold)
```

The details are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## 6. Doc index

| Doc | What it holds |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, data model, Python layout, Claude Code flags and hooks, WSL/Windows automation, security |
| [docs/prompt-cache.md](docs/prompt-cache.md) | How the prompt cache behaves under ticks, and the session / resume / summarise policy that follows |
| [docs/scheduler.md](docs/scheduler.md) | Unfair scheduler, budgets, wrap-up protocol, fan-out limits, skip rules |
| [docs/telegram.md](docs/telegram.md) | Bot setup, topics, message format, reply routing, the deterministic-then-LLM routing ladder |
| [docs/evaluations.md](docs/evaluations.md) | Neutral evaluations: Beads vs. Task Master vs. CCPM; Vibe Kanban vs. Claude Squad vs. Conductor |
| [docs/tracker.md](docs/tracker.md) | **Tracker build brief**: decisions, labels, features taken from Beads, Task Master and CCPM, build order |
| [docs/tracker-report.md](docs/tracker-report.md) | The use-case tracker report: capability matrix, concurrency, overhead, fan-out, the recommended design, and when to pick each option |
| [docs/skills-extensions.md](docs/skills-extensions.md) | How switchboard drives `epf3-skills`, and what to add to that repo |
| [docs/verification.md](docs/verification.md) | What was checked against the installed Claude Code and WSL, how, and what it changed: terms of use, usage source, flags, caching, skills, stream-json fields, WSL idle settings |
| [docs/BRAINSTORM.md](docs/BRAINSTORM.md) | Open questions to settle with agents (`/brainstorm` per topic) before building |

## 7. Build phases (laptop only)

| Phase | Deliverable | Done when |
| --- | --- | --- |
| 0 | `sb-inbox` daemon (starts at Windows logon, keeps WSL alive, restarts itself), `sb ask` CLI inside harness runs, Telegram topics, the question map in SQLite. Nothing writes to GitHub | The manual end-to-end check: a shell stand-in calls `sb ask`, then a real headless `claude -p /brainstorm` run does. The owner answers on the phone, and `sb answers` shows the answer for the next run |
| 1 | `sb-tick` + scheduler + budget hooks, **one repo** | A week of unattended ticks in one repo with usable handoffs and no runaway fan-out |
| 2 | Round-robin across repos, usage snapshots, `UTIL` and `DIGEST` messages | Every onboarded repo progresses; the daily digest is the only thing the owner reads |
| 3 | Idea routing (the ladder), `SCHEDULED` jobs, LAN dashboard (read-only) | A one-line idea from the phone becomes a brainstorm round in the right repo with no typing at the laptop |
| later | Cloud routines for selected tickets while the laptop is off | Only if Phase 2 shows the laptop being off is the bottleneck |

## 8. Prior art (summary)

No product does all of this. The pieces that exist:

- Claude Code itself: headless mode, hooks, statusline `rate_limits`, Channels
  (Telegram/Discord/iMessage into a *running* session) and cloud routines
- agent trackers: Beads, Task Master, CCPM
- multi-agent runners: Vibe Kanban (sunsetting), Claude Squad, Conductor (macOS only)
- phone clients and approval tools: Happy, Omnara, HumanLayer, Claude-Code-Remote

switchboard uses Claude Code's own features, takes ideas from the trackers, and builds on what
epf3-skills already does with GitHub Issues. How each one fits is in
[docs/evaluations.md](docs/evaluations.md).
