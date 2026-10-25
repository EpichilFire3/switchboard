# Architecture

## 1. Processes

| Process | Runs | Spends tokens? | Job |
| --- | --- | --- | --- |
| `sb-inbox` | Always (systemd user service in WSL) | Only at routing rung L3 | Polls Telegram; routes answers, ideas and commands; triggers early runs |
| `sb-tick` | Every 30 min (§6) and on early runs | Yes, one budgeted run | Gates, picks a ticket, runs Claude, records |
| `sb boot` | Once per WSL start | No | Fairness reset, stale-lock cleanup, digests for killed runs |
| summariser | After a run, only when the ticket's next start is FRESH | Yes, Haiku 5.5 low, outside the run's budget | Turns the run's deterministic digest into the pack's handoff section |
| `sb` CLI | Called by agents inside runs, and by the owner | No | `ask`, `status`, `decide`, `split`, `pause`, `doctor` |
| hooks | Inside harness runs | No | Budget warn/deny/stop checks; statusline snapshot |
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
| `tickets` | repo, number, size, priority, `session_id`, `pack_path`, runs, `no_progress_runs`, harness status (`queued`/`ready`/`blocked`/`parked`) |
| `sessions` | `session_id`, repo, ticket, model, `last_request_at`, `ttl_seconds`, `context_tokens` |
| `runs` | `run_id`, ticket, start/end, mode (`fresh`/`resume`/`resume-cold`), exit reason, usage fields, cost-equivalent, outcome, final `Next:`/`Gate:` lines, digest path, `handoff_built` |
| `questions` | `qid`, ticket, `run_id`, category, urgency, blocking, round, status, answer, `answered_at` |
| `tg_map` | (`chat_id`, `message_id`) → kind + ref (question, digest item, idea, ticket) |
| `ideas` | text, source message, rung that routed it, repo, kind, status |
| `decisions` | repo, ticket, text, source (owner answer / agent), at |
| `usage_snapshots` | at, source, five-hour %, seven-day %, reset times |
| `kv` | Telegram offset, `paused_until`, cursors |

**Files:** `~/.switchboard/packs/<repo>/<ticket>.md` (context packs),
`~/.switchboard/log/decisions.md` (the decision log mirrored as readable markdown),
`~/.switchboard/config.toml`, `~/.switchboard/jobs.yaml`, `~/.switchboard/secrets.env`.

## 3. Running Claude Code

```
cd <worktree for repo/ticket>
claude -p "<dynamic prompt>" \
  --output-format stream-json --verbose \
  --session-id <new uuid>           # or: --resume <session_id>
  --model <lane model> \
  --max-turns <size budget> \
  --settings ~/.switchboard/harness-settings.json \
  --append-system-prompt "$(cat preamble/harness.md)"    # static, byte-identical every run
```

Each flag needs checking against the installed version **(verify)**.

- **Auth.** The owner's claude.ai login. No `ANTHROPIC_API_KEY` in the environment; `sb doctor`
  fails if one is set, because it would silently switch billing to the API.
- **`--settings`** layers in the harness hooks and permissions only for harness runs. The owner's
  interactive sessions never see them. As a second guard, the hooks also no-op without `SB_RUN_ID`.
- **Permissions.** Headless runs cannot answer prompts, so anything not allowed is denied. Start
  from the repo's epf3 allowlist plus harness additions. `--dangerously-skip-permissions` is never
  used. Whether to use auto mode is an open question ([BRAINSTORM.md](BRAINSTORM.md)).
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
  start. Whether `disable-model-invocation` skills work from `-p` must be checked **(verify)**.

### Prompt layout (cache-aware, see [prompt-cache.md](prompt-cache.md) §3.4)

```
[system]  Claude Code base + CLAUDE.md + skills ...   ← shared, cached
[system+] preamble/harness.md (static)                ← shared, cached
[user]    RUN <run_id> · ticket · size budget          ← dynamic from here on
          context pack (fresh) | owner answers (resume)
          the instruction: the epf3 command (e.g. /implement 412) or "continue from the Next: line"
```

## 4. Hooks (Python, in `switchboard/hooks/`)

| Hook | Event | Does |
| --- | --- | --- |
| `budget_post.py` | `PostToolUse` | Computes used fraction (wall clock, turns, cost-equivalent from transcript usage); at ≥80% returns `additionalContext` with the wrap-up notice, once |
| `budget_pre.py` | `PreToolUse` | At ≥100%, denies every tool except `sb …` and `git commit` on the ticket branch |
| `stop_final.py` | `Stop` | If the last message has no `Next:` line, blocks the stop once with "end with the final lines" (costs one short turn) |
| `statusline.py` | statusline (owner's interactive sessions) | Renders as usual **and** writes `rate_limits` to `usage_snapshots` |

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

**Recommended split.** Windows Task Scheduler is the clock, because it already understands
sleep, battery, logon and missed runs. WSL systemd hosts the daemon.

| Task | Where | Definition |
| --- | --- | --- |
| Boot WSL + `sb boot` | Task Scheduler, *at logon* and *on workstation unlock* | `wsl.exe -d <distro> -u <user> -- ~/.local/bin/sb boot` |
| Tick | Task Scheduler, every 30 min | `wsl.exe -d <distro> -u <user> -- ~/.local/bin/sb-tick`; "start only on AC power" (optional), "don't start a new instance", "run as soon as possible after a missed start" **off** |
| Inbox daemon | WSL systemd user unit `sb-inbox.service` | `Restart=always`; needs `[boot] systemd=true` in `/etc/wsl.conf` and `loginctl enable-linger <user>` |
| Keep WSL alive | `.wslconfig` | Idle-shutdown setting (`vmIdleTimeout`) **(verify name and behaviour on the installed WSL)** |

The alternative, systemd timers inside WSL for ticks as well, keeps everything in Linux but has
to rebuild the battery and sleep logic itself. This choice is open in [BRAINSTORM.md](BRAINSTORM.md).

## 6b. Every repo under `side-projects`, switchboard included

**Registry.** `sb repos scan` registers every git checkout directly under `~/side-projects`:
the apps, `epf3-skills` and `switchboard` itself. A repo becomes schedulable once it is
onboarded the epf3 way (GitHub origin, a `development` branch, labels), has a slot at
`~/.switchboard/wt/<repo>` installed with `setup.py --harness`, and the owner has trusted the
slot once. `sb doctor` lists what is missing for each repo. `epf3-skills` has no origin yet, so
it is not schedulable until the owner pushes it.

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
    cli.py                       # sb: ask, status, decide, split, pause, boot, doctor
    config.py  db.py             # config.toml; SQLite schema + migrations
    tracker/  base.py github.py  # Tracker adapter; gh-backed implementation, epf3 markers
    claude/   invoke.py          # argv builder, timeout, SIGTERM/SIGKILL
              transcript.py      # parse stream-json + ~/.claude/projects JSONL: usage, TTL, files edited
    tick/     runner.py gates.py scheduler.py prompt.py digest.py pack.py summarise.py
    inbox/    poller.py render.py router.py ladder.py commands.py digest.py
    usage/    sources.py         # statusline snapshots, run logs, other sources (see BRAINSTORM)
    hooks/    budget_post.py budget_pre.py stop_final.py statusline.py
    fallback.py                  # the one place that spawns cheap LLM resolver sessions
  deploy/
    systemd/  sb-inbox.service
    windows/  register-tasks.ps1 # creates the Task Scheduler tasks
  tests/
```

## 8. The deterministic-first rule, in one place

Each fallback goes through `fallback.py`. It always runs the cheapest model,
`claude -p --model claude-haiku-5-5 --effort low` (**verify** the effort flag), with a fixed small
`--max-turns`, low effort, a strict JSON schema in the prompt, a timeout, and no tools unless the
case needs them. Every call is logged with the reason it fired, so the thresholds can be tuned
until the fallback rarely runs.

| Deterministic step | Becomes unsure when | Fallback | Then |
| --- | --- | --- | --- |
| Idea routing (L0–L2) | BM25 below thresholds | L3 router | Owner buttons, then `/triage` on the verbatim message in switchboard's slot |
| Lane/kind detection | No regex cue | L3 JSON `kind` | `/brainstorm` |
| Handoff for a cold start | Always needs synthesis (it is not deterministic) | Haiku writes it from the digest, lazily | Validation fails twice: `HARNESS` message |
| Free-text answer to a button question | Text doesn't name an option | Haiku maps text → option or "custom" | Stored as custom; the agent reads it verbatim |
| Tracker/DB disagreement | Issue closed but harness says ready, etc. | Rule table first; Haiku only for unclassified cases | `HARNESS` message |
| Split proposal | JSON invalid or violates limits | Reject with the rule broken; the agent retries once in the same run | Park as `needs-split` |

## 9. Security summary

- No API key; subscription login only.
- Telegram allowlist; the token is unreadable to harness sessions (permission deny).
- Secret redaction before any outbound message.
- Worktrees per ticket; epf3 git guards active; no pushes to `main`/`development` from ticks.
  Merging stays a human `GATE` (epf3's `/ship <n> merge`).
- Forwarded content is labelled as data.
- The LAN dashboard (Phase 3) is read-only and bound to the home network (WSL mirrored
  networking), with no write endpoints.
