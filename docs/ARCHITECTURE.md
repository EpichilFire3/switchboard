# Architecture

## 1. Processes

| Process | Runs | Spends tokens? | Job |
| --- | --- | --- | --- |
| `sb-inbox` | Always, while WSL is up (how it is kept up is §6) | Only at routing rung L3 | Polls Telegram; routes answers, ideas and commands; triggers early runs |
| `sb-tick` | Every 30 min (§6) and on early runs | Yes, one budgeted run | Gates, picks a ticket, runs Claude, records |
| `sb boot` | Once per WSL start | No | Fairness reset, stale-lock cleanup, digests for killed runs |
| summariser | After a run, only when the ticket's next start is FRESH | Yes, Haiku 5.5 low, outside the run's budget | Turns the run's deterministic digest into the pack's handoff section |
| `sb` CLI | Called by agents inside runs, and by the owner | No | `ask`, `status`, `decide`, `split`, `pause`, `doctor` |
| hooks | Inside harness runs | No | Budget warn/deny/stop checks |
| Claude Code | Spawned by `sb-tick` | Yes | The actual work, in a per-ticket worktree |

Deterministic code does the routing, scheduling, bookkeeping and enforcement. Claude does the
reasoning and the implementation, plus the narrow fallbacks listed in §8.

## 2. State

**Source of truth for work:** the tracker, with one per repo. GitHub Issues is the default, because
`epf3-skills` already writes tickets there through `gh` (see [evaluations.md](evaluations.md)).
switchboard reads and writes it through a small `Tracker` adapter so the backend can change.

**Harness state:** `~/.switchboard/switchboard.db` (SQLite, WAL mode). The tracker knows nothing
about sessions, caches or budgets, and should not.

| Table | Key columns |
| --- | --- |
| `repos` | name, path, gh `nameWithOwner`, `topic_id`, `vruntime`, `last_run_at`, enabled, lane model |
| `tickets` | repo, number, size, priority, `session_id`, `pack_path`, runs, `no_progress_runs`, harness status (`queued`/`ready`/`blocked`/`parked`), the two block causes `questions` and `reported` (blocked while either is set), last reported status and reason |
| `sessions` | `session_id`, repo, ticket, model, `last_request_at`, `ttl_seconds`, `context_tokens` |
| `runs` | `run_id`, ticket, start/end, mode (`fresh`/`resume`/`resume-cold`), exit reason, usage fields, cost-equivalent, outcome, final `Next:`/`Gate:` lines, digest path, `handoff_built` |
| `questions` | `qid`, ticket, `run_id`, category, urgency, blocking, round, status, answer, `answered_at` |
| `tg_map` | (`chat_id`, `message_id`) → kind + ref (question, digest item, idea, ticket) |
| `ideas` | text, source message, rung that routed it, repo, lane, status |
| `decisions` | repo, ticket, text, source (owner answer / agent), at |
| `usage_snapshots` | at, source (`rate_limit_event` / `/usage`), five-hour %, seven-day %, reset times, status |
| `kv` | Telegram offset (`telegram_offset`, deleted by `sb setup telegram`), `harness_topic_id`, `paused_until`, cursors |

**Files:** `~/.switchboard/packs/<repo>/<ticket>.md` (context packs),
`~/.switchboard/log/decisions.md` (the decision log mirrored as readable markdown),
`~/.switchboard/config.toml` (`[telegram]` `chat_id` and `owner_id`), `~/.switchboard/jobs.yaml`,
`~/.switchboard/secrets.env` (`TELEGRAM_BOT_TOKEN`, mode 600),
`~/.switchboard/switchboard.lock` (held while a process opens the database and migrates it, so
concurrent first opens do not race the switch to WAL), `~/.switchboard/inbox.lock` (the
single-poller lock: held by `sb-inbox` for its lifetime and by `sb setup telegram` while it runs).

## 3. Running Claude Code

```
cd <worktree for repo/ticket>
ENABLE_CLAUDEAI_MCP_SERVERS=false SB_RUN_ID=<run_id> SB_BUDGET_…=… \
claude -p "<dynamic prompt>" \
  --output-format stream-json --verbose \
  --session-id <fresh uuid>         # or: --resume <session_id>
  --model <lane model> \
  --max-turns <size budget> \
  --permission-mode <mode> --permission-prompts none \
  --setting-sources project,local \
  --settings ~/.switchboard/harness-settings.json \
  --append-system-prompt-file preamble/harness.md \
  --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
  < /dev/null
```

The prompt comes first, because `--mcp-config` takes several values and would swallow a prompt
placed after it. `< /dev/null` stops `claude -p` waiting 3 s for stdin.

Every flag was checked on 2.1.310 ([verification.md](verification.md) §3).

- **Auth.** The owner's claude.ai login. No `ANTHROPIC_API_KEY` in the environment; `sb doctor`
  fails if one is set, because it would silently switch billing to the API. switchboard never
  reads `~/.claude/.credentials.json` or calls Anthropic endpoints with the token itself
  ([verification.md](verification.md) §1). `--bare` is not an option: it ignores the subscription
  login.
- **Sessions.** `--session-id` is single use, so every fresh start gets a new uuid. `--resume`
  keeps the same session id and appends to the same transcript, so `sessions.session_id` stays
  valid across resumes.
- **stream-json needs `--verbose`** under `-p`. The stream also carries the usage percentages
  (`rate_limit_event`, [verification.md](verification.md) §2), so every run refreshes
  `usage_snapshots` for free.
- **Result handling.** The run's outcome is the `result` event's `subtype`, not the exit code
  alone: hitting `--max-turns` exits 1 with `error_max_turns` and keeps the partial work, so the
  runner records it as a partial run to resume, not a crash. There is no timeout flag: `sb-tick`
  enforces the wall clock (SIGTERM, then SIGKILL).
- **`--settings`** layers in the harness hooks and permissions on top of the slot's own settings,
  only for harness runs. The owner's interactive sessions never see them. As a second guard, the
  hooks also no-op without `SB_RUN_ID`.
- **What a run loads** ([verification.md](verification.md) §10). Harness runs drop the owner's
  user settings (`--setting-sources project,local`), every MCP server (the strict empty config;
  `ENABLE_CLAUDEAI_MCP_SERVERS=false` as well), and the claude-mem and context7 plugins
  (`enabledPlugins` set to false in `harness-settings.json`). They keep `local`, because epf3's
  hooks live in the slot's `settings.local.json`. That takes a fresh start from 45.6k to 35.5k
  tokens: ~26k shared with every other fresh session, plus a ~9.5k tail that is written fresh
  each time. The tail grows with the number of skills listed, so the slot's skill count is the
  remaining lever.
- **Permissions.** Headless runs cannot answer prompts. `--permission-prompts none` makes anything
  not allowed a denial instead of a hang. Start from the repo's epf3 allowlist plus harness
  additions. `--dangerously-skip-permissions` and `--permission-mode bypassPermissions` (the same
  thing) are never used. Whether to use auto mode is an open question
  ([BRAINSTORM.md](BRAINSTORM.md)).
- **Worktrees: fixed slots, not one per ticket.** A fresh worktree has none of epf3's
  `.claude/skills`, `settings.local.json` hooks or ledgers, because all of them are untracked or
  excluded. It is also an untrusted folder, so Claude Code skips the agents' guard hooks, and
  `guard-dispatch.py` refuses the guarded agents. So each repo gets **one reusable harness
  worktree**, `~/.switchboard/wt/<repo>`. It is created once, then `setup.py <path>` installs into
  it, and the owner trusts it once (a `/wizard` step). Each run checks out the ticket's branch
  there. `sb doctor` re-checks install and trust. The harness hooks also come in through
  `--settings`, so a missing install cannot silently disable the budget hooks. The owner's VSCode
  checkout is never touched. Ledgers live in the slot, so they persist across that repo's runs.
- **Owner-active gate.** If a *non-harness* transcript under `~/.claude/projects/<repo>/` was
  written in the last 10 minutes, the owner is working there. Skip that repo this tick.
- **Inspection.** Harness sessions are ordinary Claude Code sessions, so they appear in VSCode's
  session history for the repo. The `runs` table maps ticket to session for `/status` and the
  digest.
- **Skills.** A run may be started as an epf3 command, e.g. `claude -p "/implement 412"`. The
  runner is "the user typing the command", which is how epf3's user-invoked skills are meant to
  start, and it works for `disable-model-invocation` skills ([verification.md](verification.md)
  §6). The prompt starts with `/name`, and everything after it on that line becomes
  `$ARGUMENTS`, so the context pack and other dynamic text go on later lines. An empty result
  counts as a failure. Loading the skill uses a turn.
- **The model can type commands too.** A flagged skill's exact `/name` anywhere in the context was
  enough for the model to invoke it through the Skill tool. So never-auto actions rest on
  `guard-harness.py` and the runner's allowlist, never on `disable-model-invocation`, and packs
  never quote a never-auto command (`/ship <n> merge`, devops production) verbatim.

### Prompt layout (cache-aware, see [prompt-cache.md](prompt-cache.md) §3.4)

```
[system]  Claude Code base + CLAUDE.md + skills ...   ← shared, cached (git state does not break it)
[system+] preamble/harness.md (static)                ← shared, cached
[user]    /<epf3 command> <args>  (first line, when the run starts one)
          RUN <run_id> · ticket · size budget          ← dynamic from here on
          context pack (fresh) | owner answers (resume)
          the instruction: the epf3 command (e.g. /implement 412) or "continue from the Next: line"
```

## 4. Hooks (Python, in `switchboard/hooks/`)

| Hook | Event | Does |
| --- | --- | --- |
| `budget_post.py` | `PostToolUse` | Counts turns and tool calls and tracks the wall clock in its own state file keyed on `session_id`. Adds cost-equivalent from transcript usage with a margin, because the transcript is one turn behind at this point. At ≥80% returns `additionalContext` with the wrap-up notice, once |
| `budget_pre.py` | `PreToolUse` | At ≥100%, denies every tool except `sb …` and `git commit` on the ticket branch, checking the command itself. It only ever denies or says nothing, never `allow`: an `allow` would skip the permission rules entirely |
| `stop_final.py` | `Stop` | If `last_assistant_message` has no `Next:` line and the turn count is below `--max-turns`, blocks the stop once with "end with the final lines" (one more call over the full context). At the turn limit it never blocks, because a block there ends the run with `result: null` |

All three are verified under `-p` ([verification.md](verification.md) §11). A hook that crashes
or times out never fails the run, so `sb-tick` runs with `--include-hook-events` and records each
hook's outcome. A missing budget hook then shows up in the run log instead of passing silently.
A denied tool call still counts as a turn. If a run ends at the turn limit with `result: null`,
the runner takes the final text from the stream's last assistant message.
Usage percentages need no hook: `sb-tick` reads the `rate_limit_event` from each run's stream,
and when no run has happened recently it runs `claude -p "/usage"`, which makes no model call
([verification.md](verification.md) §2). The statusline never runs under `-p`.

These sit alongside epf3's hooks (`session-brief.py`, `guard-git.py`, `guard-dispatch.py`), which
stay active in harness runs. `guard-git.py` already blocks force pushes and pushes to the default
branch.

## 5. Claude Code Channels: where it fits

Channels (research preview, v2.1.80+) pushes Telegram, Discord or iMessage messages into an
**already running** session. It is not the backbone: the harness is tick-based and needs no
long-lived session. It remains an optional **live lane**: the owner starts
`claude --channels …` in tmux on one repo, paired to a **second** bot (one poller per token),
and chats with it in real time. Its usage counts against the same limits, and the scheduler sees
it through the owner-active gate (§3).

## 6. Windows + WSL automation

**What WSL does on its own** ([verification.md](verification.md) §9). The distro stops ~15 s
after the last process attached to a WSL session ends, and the VM follows about a minute later.
The settings that tune those delays (`[general] instanceIdleTimeout`, `[wsl2] vmIdleTimeout`)
need WSL 2.5.4 or later. This machine has 2.3.26, so nothing here depends on them. **systemd
services and lingering users do not count as activity**, so a systemd unit cannot keep itself, or
WSL, alive. A process started through `wslg.exe` or `wsl.exe` does. Either one cold-starts a
stopped distro, and systemd comes up with it (`[boot] systemd=true` is already set on this
machine).

So whatever runs the clock, something Windows-side must hold a WSL session open while `sb-inbox`
is meant to be up. That process is `sb-inbox` itself, started through `wslg.exe`: it opens no
console window, where `wsl.exe` opens one, and it needs no VBScript wrapper, `conhost --headless`
or hidden PowerShell (each flashes a window). `wslg.exe` discards stdout and stderr, so
`sb-inbox` logs only to its size-rotated log file.

| Task | Where | Definition |
| --- | --- | --- |
| Inbox daemon, which also keeps WSL alive | One Task Scheduler task. Triggers: at logon, on workstation unlock, and repeat every 10 minutes indefinitely. `sb install-task` registers it as the current user, without admin rights | `wslg.exe -d <distro> -u <user> -- <absolute path to sb-inbox>`. It runs `sb boot` first, once per WSL start |
| Tick | Task Scheduler every 30 min, **or** a systemd timer in WSL | Task Scheduler: `wsl.exe -d <distro> -u <user> -- ~/.local/bin/sb-tick`, "start only on AC power" (optional), "don't start a new instance", "run as soon as possible after a missed start" **off** |
| Idle settings | `%UserProfile%\.wslconfig` | Optional extra layer, never the keep-alive. `[general] instanceIdleTimeout=-1` and `[wsl2] vmIdleTimeout=-1` only exist from WSL 2.5.4, and WSL issue #13416 reports the distro stopping anyway on some versions, so test it once there. Not applied |

The inbox task is set explicitly, not left to defaults:

- run only when the user is logged on, as the owner (not "whether logged on or not": that runs in
  session 0, where WSL does not start)
- no execution time limit
- start and keep running on battery
- start when available after a missed start
- ignore a new instance while one runs, so a trigger that fires while `sb-inbox` is up does
  nothing

**Two layers of restart.** Task Scheduler's restart-on-failure is not used: it most likely never
fires after a launched process exits.

1. **Inside WSL**, `sb-inbox` is the supervisor. It takes the single-instance lock for its
   lifetime and runs the poller as its child. When the poller exits, the supervisor restarts it
   after 1 s, doubling to 60 s on consecutive crashes, until the crash-loop rule backs it off to
   one restart every 5 minutes.
2. **Inside Windows**, the 10-minute repeat trigger restarts everything the supervisor cannot:
   `wsl --shutdown`, a WSL update, or the supervisor dying. The task instance ends with the
   session, and the next trigger starts a new one, so recovery takes at most 10 minutes.

Linger is off on this machine and is not needed if nothing runs as a systemd user unit. Which
clock drives the tick is the owner's call ([BRAINSTORM.md](BRAINSTORM.md) A5). Task Scheduler
already knows sleep, battery, logon and missed runs. A systemd timer keeps everything in Linux,
but only fires while something else keeps WSL up, and has to rebuild the battery logic itself.
What happens to a run when the laptop sleeps is undocumented: expect the clock to jump and the
connection to drop, and let `sb boot`'s salvage handle it.

## 6b. Every repo under `side-projects`, switchboard included

**Registry.** `sb repos scan` registers every git checkout directly under `~/side-projects`:
the apps, `epf3-skills` and `switchboard` itself. A repo becomes schedulable once it is
onboarded the epf3 way (GitHub origin, a `development` branch, labels), has a slot at
`~/.switchboard/wt/<repo>` installed with `setup.py --harness`, and the owner has trusted the
slot once. `sb doctor` lists what is missing for each repo. `epf3-skills` is the exception to the
branch flow: it has no `development` branch and takes work on `main` (`guard-git.py` allows pushes
to its `main` only). Its origin is `EpichilFire3/epf3-skills` (private). It still needs labels and
a slot before it is schedulable, and its ticket branches merge straight into `main`.

**Self-editing switchboard.** A run on a switchboard ticket changes switchboard's code in the
switchboard slot, on a ticket branch, like any other repo. The rules that keep that safe:

1. **The running harness is an installed release, not a checkout.** `sb` runs from
   `~/.switchboard/releases/<sha>/` (a `uv tool install` of a merged commit). The hooks,
   preamble and settings come from the release, so a run cannot weaken its own budget hooks or
   guard mid-run, and `guard-harness.py` already denies writes under `~/.switchboard/`.
2. **Upgrade is a gate.** Merging a switchboard PR is the owner's `/ship <n> merge`, as for any
   repo. `sb upgrade` (the owner's command, or automatically at the next `sb boot` once the
   owner says so) installs the new sha, runs the DB migrations, then `sb doctor` and a dry-run
   tick. Any failure rolls back to the previous sha and sends a `HARNESS` message.
3. **One contract version.** `harness-mode/SKILL.md` carries `contract: <n>`. `sb` refuses to run
   ticks against a different contract, so the two repos change together.

**Self-editing epf3-skills.** Skills are linked from the epf3-skills checkout into every repo,
so a pull changes every repo's skills at once, even mid-run. Slots therefore link to a pinned
worktree, `~/.switchboard/epf3@<sha>`, which is moved forward only at `sb boot` after a merge.
Runs on epf3-skills tickets work in their own slot like any repo. The owner's merge is the gate.

## 7. Python layout

```
switchboard/
  pyproject.toml                 # uv; deps: httpx, rank-bm25, pydantic, tomli (stdlib on 3.11+)
  preamble/harness.md            # static tick protocol, appended to the system prompt
  src/switchboard/
    cli.py                       # sb: ask, status, decide, repos scan, setup telegram, split, pause, boot, doctor
    config.py  db.py             # config.toml; SQLite schema + migrations
    telegram.py                  # Bot API client over an injected transport; the single-poller lock
    fake_telegram.py             # the fake Bot API every test runs against, in place of the network
    tracker/  base.py github.py  # Tracker adapter; gh-backed implementation, epf3 markers
    claude/   invoke.py          # argv builder, timeout, SIGTERM/SIGKILL
              transcript.py      # parse stream-json + ~/.claude/projects JSONL: usage, TTL, files edited, rate_limit_event
    tick/     runner.py gates.py scheduler.py prompt.py digest.py pack.py summarise.py
    inbox/    poller.py render.py router.py ladder.py commands.py digest.py
    usage/    sources.py         # rate_limit_event from runs; headless /usage when idle
    hooks/    budget_post.py budget_pre.py stop_final.py
    fallback.py                  # the one place that spawns cheap LLM resolver sessions
  deploy/
    windows/  register-tasks.ps1 # creates the Task Scheduler tasks (sb-inbox at logon; the tick, if it is the clock)
    wsl/      wslconfig.example  # the idle settings of §6
  tests/
```

## 8. The deterministic-first rule, in one place

Each fallback goes through `fallback.py`. It always runs the cheapest model at low effort, one
turn, JSON out ([verification.md](verification.md) §5):

```
claude -p --model claude-haiku-5-5 --effort low --max-turns 1 --output-format json "<prompt>"
```

The JSON schema is in the prompt, and Python validates `.result` against it. `--json-schema` is
not used here, because structured output needs a second turn and fails under `--max-turns 1`.
An unknown `--effort` value only warns, so `fallback.py` fixes the value in code. Each call has a
timeout and no tools unless the case needs them, and uses the same load flags as runs (§3).
A fallback needs none of epf3's skills or hooks, so it can run from an empty directory with
`--setting-sources project`, which is smaller still. That case is not measured yet. Every call is logged with the
reason it fired, so the thresholds can be tuned until the fallback rarely runs.

| Deterministic step | Becomes unsure when | Fallback | Then |
| --- | --- | --- | --- |
| Idea routing (L0–L2) | BM25 below thresholds | L3 router | Owner buttons, then `/triage` on the verbatim message in switchboard's slot |
| Lane detection | No regex cue | L3 JSON `lane` | `/brainstorm` |
| Handoff for a cold start | Always needs synthesis (it is not deterministic) | Haiku writes it from the digest, lazily | Validation fails twice: `HARNESS` message |
| Free-text answer to a button question | Text doesn't name an option | Haiku maps text → option or "custom" | Stored as custom; the agent reads it verbatim |
| Tracker/DB disagreement | Issue closed but harness says ready, etc. | Rule table first; Haiku only for unclassified cases | `HARNESS` message |
| Split proposal | JSON invalid or violates limits | Reject with the rule broken; the agent retries once in the same run | Park as `needs-split` |

## 9. Security summary

- No API key; subscription login only. The harness never touches the subscription token: it
  only spawns the unmodified `claude` binary.
- The Telegram allowlist is the owner alone: anyone else who can command the bot is using the
  owner's account.
- Never-auto actions (merge, production) are enforced by `guard-harness.py` and the runner's
  allowlist, because the model can invoke a flagged skill whose `/name` appears in its context.
- Telegram allowlist; the token is unreadable to harness sessions (permission deny).
- Secret redaction before any outbound message.
- Worktrees per ticket; epf3 git guards active; no pushes to `main`/`development` from ticks.
  Merging stays a human `GATE` (epf3's `/ship <n> merge`).
- Forwarded content is labelled as data.
- The LAN dashboard (Phase 3) is read-only and bound to the home network (WSL mirrored
  networking), with no write endpoints.
