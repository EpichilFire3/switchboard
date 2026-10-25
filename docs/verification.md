# Verified facts

The design docs rest on facts about Claude Code, the subscription and WSL that were first written
down as **(verify)**. This doc records what was actually checked, how, and what changed in the
design because of it. Checked on 2026-10-25 against Claude Code **2.1.310**, WSL 2.3.26, Windows
11 (build 26300) and Ubuntu 24.04, on a claude.ai subscription login with no API key.

Raw evidence (stream-json captures, help output, proxy logs with auth redacted) is in
`tmp/verify/<dir>/`, which is gitignored. The stream-json captures double as fixtures for the fake
`claude` binary ([BRAINSTORM.md](BRAINSTORM.md) item 25). Re-check anything here after a Claude
Code upgrade that touches headless mode.

| § | Fact | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | Unattended `claude -p` on a subscription is within the terms | OK, with caveats | (web sources, §1) |
| 2 | Where the usage percentages come from | Settled: `rate_limit_event` in stream-json | `a2-usage/` |
| 3 | The `claude -p` flag set | All exist; two corrections | `v1-flags/` |
| 4 | A static `--append-system-prompt` shares the cache across fresh sessions | Partly: ~26.5k of ~39k shared | `v2-append/` |
| 5 | `--effort low` on Haiku | Works | `v3-effort/` |
| 6 | User-invoked skills run from `-p` | Works, with rules | `v4-skills/` |
| 7 | stream-json usage field names | Correct; four caveats | `v5-stream/` |
| 8 | Cache TTL is 1 hour | Confirmed: warm at 8 and 45 min, cold at 65 | `v6-ttl/` |
| 9 | `.wslconfig` `vmIdleTimeout` keeps WSL alive | Wrong setting, and not enough | `v7-wsl/` |
| 10 | Harness runs can load less | Yes: 45.6k to 35.5k, tail 19.6k to 9.5k; claude-mem is not the cause | `b7-load/` |
| 11 | The budget hooks work under `-p` | Yes, with three design changes | `b26-hooks/` |

## 1. Terms of use (BRAINSTORM A1)

**OK, with caveats.** The Consumer Terms (§3, effective 2025-10-08) forbid access "through
automated or non-human means, whether through a bot, script, or otherwise" *except* "where we
otherwise explicitly permit it". Claude Code's own docs give that permission: `claude setup-token`
exists "for CI pipelines, scripts, or other environments where interactive browser login isn't
available", and the headless docs recommend `--permission-prompts none` "in a scheduled job". The
legal page (code.claude.com/docs/en/legal-and-compliance) aims its ban at developers who "route
requests through Free, Pro, or Max plan credentials on behalf of their users" or "collect, store,
or intermediate Claude.ai credentials", and states that it does not prevent "an end user from
signing in to the unmodified Claude Code binary with their own Claude subscription". Anthropic's
own Desktop scheduled tasks (as often as every 30 minutes) and the Telegram Channel are the
closest first-party analogues, closer than `/remote-control`, where a human drives every turn.

Rules that keep switchboard on the right side, now part of the hard constraints in the README:

- Spawn only the official, unmodified `claude` binary. Never read `~/.claude/.credentials.json`
  and never call Anthropic endpoints with the subscription token.
- One owner, one account, one machine. The Telegram allowlist holds only the owner, because
  anyone else who can command the bot is using the owner's account.
- Stop at the plan's limits. Never work around throttling or rotate accounts.
- `--bare` is out: bare mode ignores the subscription login and needs an API key.

Caveats: the legal page says advertised limits "assume ordinary, individual usage". 48 ticks of up
to 15 minutes is ~12 agent-hours a day, so expect to hit caps, and keep idle ticks at zero tokens.
The subscription policy for `claude -p` and the Agent SDK changed four times in 2026, including a
paused plan to move it to a separate credit pool. Re-read
support.claude.com/en/articles/15036540 before Phase 1 and periodically after.

## 2. Usage percentages (BRAINSTORM A2)

Every `/v1/messages` response carries `anthropic-ratelimit-unified-5h-utilization`,
`-5h-reset`, `-5h-status`, the same for `-7d-`, plus `-surpassed-threshold` and `-overage-*`.
Values are 0 to 1, resets are epoch seconds. The binary stores them, and that store feeds both the
statusline's `rate_limits` (`used_percentage = util × 100`, one decimal) and stream-json.

- **Primary source:** with `--output-format stream-json --verbose`, the run emits a
  `rate_limit_event` whose `rate_limit_info.unifiedWindows.{five_hour,seven_day}` holds
  `{utilization, resetsAt, status, surpassedThreshold}`. It is usually the first line, and on a
  resume it comes after the first assistant message. A new event is emitted when a value changes
  later in the run, so the last one wins. A window drops out once its reset passes, so read with
  `.get()`; fall back to the top-level `utilization` / `rateLimitType` if `unifiedWindows` is
  missing (it is undocumented). Free: it rides on the run's own requests. Not present with
  `--output-format json`.
- **Fallback when idle:** `claude -p "/usage" --output-format json` makes no model call
  (`num_turns 0`, cost 0) and returns "Current session: 13% used · resets …". As a side effect
  the binary writes `cachedUsageUtilization` (with `fetchedAtMs`) into `~/.claude.json`, which
  Python can read without writing. Both are internal formats. At most one call per tick.
- **Not available:** the statusline command never runs under `-p`, even when passed through
  `--settings`. It belongs to the interactive TUI.
- **Not allowed (§1):** `/usage` calls `GET /api/oauth/usage` with the OAuth token. switchboard
  must not call it itself.

Cross-check at the same moment: headers 0.13 / 0.76, `/usage` 13% / 76%, and the reset times agree.

## 3. The `claude -p` flag set

All the flags in [ARCHITECTURE.md](ARCHITECTURE.md) §3 exist. The corrections:

- `--output-format stream-json` requires `--verbose` under `-p` (exit 1 otherwise).
- `--session-id <uuid>` is **single use**: reusing one exits 1 with "Session ID … is already in
  use". New sessions get a fresh uuid; continuing one is `--resume`.
- `--resume <id>` keeps the **same** session id and appends to the same transcript.
  `--fork-session` exists and is off by default.
- `--max-turns` hit: exit 1, `result.subtype = "error_max_turns"`, `is_error: true`, partial work
  kept. `num_turns` can exceed the limit (2 for a limit of 1), so it is not an invariant.
- `--settings <file>` layers on top of project settings: hooks from both fired.
- There is no timeout flag. `sb-tick` enforces wall clock itself.
- An error result exits non-zero, so the runner checks `result.subtype` as well as the exit code.
- Flags the design now uses or should evaluate: `--permission-prompts none` (deny instead of
  hang), `--permission-mode`, `--allowedTools` / `--disallowedTools`, `--setting-sources`,
  `--strict-mcp-config`, `--max-budget-usd`, `--include-hook-events`, `--append-system-prompt-file`.
  `--permission-mode bypassPermissions` is the same as `--dangerously-skip-permissions` and is
  never used.

## 4. Shared prefix across fresh sessions

Haiku, fresh `--session-id` each run, same directory and preamble, first assistant event:

| Change between runs | cache_read | cache_creation |
| --- | --- | --- |
| first run, cold | 0 | 39,370 |
| new session, new prompt | 26,558 | ~12.8k |
| dirty file, untracked file, or a new commit | 26,558 | ~12.8k |
| one byte of the preamble changed | 23,918 | ~15.5k |

- `--append-system-prompt` and `--append-system-prompt-file` both work under `-p` and behave
  the same.
- Git state does not break the shared prefix.
- **~12.5k of every first request is written fresh even when nothing changed.** §10 measured it:
  the tail scales with the skill listing, and claude-mem is not the cause.
- **The ~39k is mostly the owner's global setup:** 86 tools, 40 skills, 3 plugins, 8 claude.ai MCP
  servers. §10 has the flags that cut it.
- `--exclude-dynamic-system-prompt-sections` showed no benefit.

## 5. Effort on the cheap fallback

`--effort low|medium|high|xhigh|max` exists, also as `CLAUDE_CODE_EFFORT_LEVEL` or the
`effortLevel` setting. Haiku 5.5 accepts it (its default is medium). An unknown value only warns
and exits 0, so `fallback.py` validates its own value. The effect on a tiny prompt was small and
noisy: treat `low` as a hint. `--model claude-haiku-5-5` and `--model haiku` both work.

`--json-schema` does not work with `--max-turns 1`: structured output takes an extra turn, so the
run ends in `error_max_turns` with no output. One-turn fallbacks ask for JSON in the prompt and
validate it in Python (`--output-format json`, read `.result`). The verified invocation:

```
claude -p --model claude-haiku-5-5 --effort low --max-turns 1 --output-format json "<reply with only JSON ...>"
```

## 6. User-invoked skills from `-p`

`claude -p "/implement 412"` works for `disable-model-invocation: true` skills: the CLI expands
the skill into a synthetic user message, and `$ARGUMENTS` is `412`. The epf3 "you type" skills use
only that flag. Legacy `.claude/commands/*.md` behave the same.

- The prompt must **start** with `/name`. Everything after it on the line becomes `$ARGUMENTS`
  verbatim (`/dmi 412 and then say hello` gives `412 and then say hello`).
- `user-invocable: false` skills fail **silently** from `-p` (empty result). The runner treats an
  empty result as a failure.
- Loading a skill uses a turn; size `--max-turns` for it.
- "Run the dmi skill" in prose did not invoke a flagged skill, so the flag still guards against
  paraphrase.
- **But a flagged skill's exact `/name` mid-prompt was invoked by the model through the Skill
  tool** (`please do this: /dmi 412`; one run, not yet repeated). Any `/ship <n> merge` text that
  reaches a run's context (a pack's `Next:` line, an owner answer, forwarded content) may be enough
  for the model to run it. `guard-harness.py` is therefore the barrier for never-auto actions, not
  defence in depth, and packs never quote never-auto commands verbatim.

## 7. stream-json usage fields

The field names in [prompt-cache.md](prompt-cache.md) §5 are right. Observed shape:

- Events: `rate_limit_event`, `system/init`, `assistant`, `user` (tool results), `result`; with
  `--include-partial-messages` also `stream_event` and `system/status`.
- `assistant.message.usage`: `input_tokens`, `cache_creation_input_tokens`,
  `cache_read_input_tokens`, `cache_creation.{ephemeral_5m_input_tokens,
  ephemeral_1h_input_tokens}`, `output_tokens`. Both ephemeral fields are always present.
- `result`: `subtype`, `is_error`, `num_turns`, `duration_ms`, `session_id`, `total_cost_usd`,
  `permission_denials`, `usage` (summed over the run, with `iterations[]` holding the last
  request), and camelCase `modelUsage.<model>`.

Caveats:

1. **One `assistant` event per content block, each with the same `message.id` and `usage`.**
   Summing them double-counts. Dedupe by `message.id`, or use `result.usage` for run totals.
2. **`output_tokens` on assistant events is a stale snapshot.** Final values are in
   `result.usage` and the transcript.
3. **`total_cost_usd` is a list-price estimate** (`costBasis: "list"`), not billed spend. It is
   still the right cost-equivalent unit for the scheduler.
4. `modelUsage.inputTokens` does not match `usage.input_tokens`; do not use it for `H`.

`H` = input + cache_read + cache_creation of the last request, i.e. `result.usage.iterations[-1]`.
Transcripts live at `~/.claude/projects/<slug>/<session_id>.jsonl`, where the slug is the absolute
cwd with every `/` and `.` replaced by `-`. Their `assistant` lines carry the same usage, so hooks
can read usage mid-run; filter on `type == "assistant"` and dedupe by id.

## 8. Cache TTL

**The TTL is 1 hour.** Every write, on Haiku and Sonnet alike, went to the 1-hour bucket
(`ephemeral_1h_input_tokens` > 0, `ephemeral_5m_input_tokens` = 0). Two Haiku sessions were
created at 12:30 and resumed with `--resume <id> --max-turns 1`:

| Run | Gap since that session's last request | cache_read | cache_creation |
| --- | --- | --- | --- |
| A0 create | — | 26,527 | 14,652 |
| A1 resume | 8 min | 41,179 | 85 |
| A2 resume | 45 min | 41,264 | 39 |
| B0 create | — | 23,910 | 17,308 |
| B1 resume | 65 min | 23,910 | 17,388 |

At 8 and 45 minutes the whole history was read from cache, so the TTL is longer than 5 minutes.
At 65 minutes the session's own ~17k was written again. Its 23.9k read is the static prefix shared
across sessions, which other runs had kept warm. So the session's cache expired somewhere between
45 and 65 minutes after its last request, which matches a 60-minute TTL.

Not measured: the exact boundary inside 45 to 65 minutes, and whether a hit restarts the clock (A2
was 53 minutes after A0, so it doesn't settle that). Overage was not induced. The sign of it would
be the 5m bucket turning non-zero, which `sb-tick` watches for
([prompt-cache.md](prompt-cache.md) §5). Note too that a "cold" resume still reads the shared
static prefix if any session in the same setup ran within the hour, so the cold rows in
[prompt-cache.md](prompt-cache.md) §2 overstate the cost when other repos are active.

## 9. Keeping WSL alive

- `[wsl2] vmIdleTimeout` (ms, default 60000) governs the whole VM, not the distro.
- `[general] instanceIdleTimeout` (ms, default 15000, `-1` disables) governs the distro, which
  otherwise stops ~15 s after the last `wsl.exe` session or process ends.
- **systemd services and lingering users do not count as activity** (Microsoft docs; WSL issues
  #8854, #13416). A systemd user unit alone cannot keep `sb-inbox` alive, and #13416 (still open)
  reports the distro stopping even with `instanceIdleTimeout` settings in place on some versions.
- What keeps a distro alive is a process attached to a `wsl.exe` session, e.g. a logon task that
  runs `wsl.exe -d <distro> -- <long-running command>`.
- A scheduled `wsl.exe -d <distro> -- cmd` cold-starts a stopped distro (standard behaviour, not
  tested here). With `[boot] systemd=true`, systemd comes up on start.
- Sleep and lid-close behaviour is undocumented. Expect clocks to jump and connections to drop.
- This machine: `/etc/wsl.conf` has only `[boot] systemd=true`; there is no `.wslconfig`; linger
  is off.

The candidate `.wslconfig` (not applied; needs a test on this machine):

```
[general]
instanceIdleTimeout=-1

[wsl2]
vmIdleTimeout=-1
```

## 10. What a harness run loads (BRAINSTORM item 7)

Measured in a scratch slot holding a copy of switchboard's `.claude/` and CLAUDE.md, with a fake
`origin` so `session-brief.py` prints. Two fresh Haiku sessions per variant. "Total" is run 1's
first request; "shared" and "tail" are run 2's cache_read and cache_creation.

| Variant | Total | Shared | Tail | Tools / skills / MCP | epf3 brief |
| --- | --- | --- | --- | --- | --- |
| Baseline, all setting sources | 45.6k | 26.0k | 19.6k | 107 / 89 / 10 | ran |
| `--setting-sources project,local` | 41.8k | 26.0k | 16.2k | 107 / 74 / 10 | ran |
| `--setting-sources project` | 38.4k | 26.5k | 11.8k | 86 / 45 / 8 | **lost** |
| `--strict-mcp-config --mcp-config '{"mcpServers":{}}'` | 41.8k | 26.0k | 15.8k | 28 / 89 / 0 | ran |
| claude-mem off for the run | 42.6k | 26.0k | 16.6k | 88 / 60 / 9 | ran |
| `ENABLE_CLAUDEAI_MCP_SERVERS=false` | 42.6k | 26.0k | 16.6k | 52 / 89 / 2 | ran |
| **Recommended combination** (below) | **35.5k** | 26.0k | **9.5k** | 28 / 45 / 0 | ran |
| the same, with `SB_RUN_ID` set | 34.9k | 26.0k | 8.9k | 28 / 45 / 0 | terse brief |
| diagnostic: `--disable-slash-commands` | 40.0k | 35.2k | 4.8k | 27 / 0 / 0 | off |

- **The shared ~26k is the system prompt and built-in tools.** It doesn't change with any of the
  settings.
- **The tail scales with the skill listing:** 19.6k with 89 skills, 9.5k with 45, 4.8k with none.
  It has the same size every session but is never read from cache across sessions. Why a
  byte-identical tail misses is not known (inferred: the cache only matches up to a block boundary
  before it). Within one session it is cached, as the resumes in §8 show.
- **claude-mem is not the cause.** Turning it off saved ~3k, from its own skills and tools. Its
  hooks errored on this machine (not on PATH), so it injected nothing; on a machine where it works
  it would add more.
- **An empty strict MCP config drops every MCP server, the claude.ai ones included.**
  `ENABLE_CLAUDEAI_MCP_SERVERS=false` drops only the claude.ai ones. MCP tool schemas are
  deferred, so removing 79 tools saved only ~4k.
- **Breaks:**
  - `--setting-sources project` drops `settings.local.json`, which holds epf3's hooks. Never use it.
  - `--disable-slash-commands` drops every skill.
  - `--mcp-config` takes several values and swallows a prompt placed after it, so the prompt goes
    first.
- The subscription login worked in every variant.

The recommended flags for harness runs and fallbacks:

```
ENABLE_CLAUDEAI_MCP_SERVERS=false SB_RUN_ID=<id> \
claude -p "<prompt>" ... \
  --setting-sources project,local \
  --settings <harness settings, including
      {"enabledPlugins": {"claude-mem@thedotmack": false, "context7@claude-plugins-official": false}}> \
  --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
  < /dev/null
```

The remaining lever is the slot's own skill count (45). Untested: a per-lane pruned skill set in the
slot. The ~9.5k tail is paid as a cache write on every fresh start.

## 11. Budget hooks under `-p` (BRAINSTORM item 26)

14 Haiku runs, hooks supplied through `--settings`.

- **`PostToolUse` `additionalContext` works.** The model gets it in the same run and acts on it.
  Output: `{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"…"}}`.
  "Once" works with a flag file keyed on `session_id`.
- **`PreToolUse` deny works.** Output: `{"hookSpecificOutput":{"hookEventName":"PreToolUse",
  "permissionDecision":"deny","permissionDecisionReason":"…"}}`. The model sees an error
  tool_result and stops rather than working around it. Denials appear in
  `result.permission_denials`. **A denied call counts as a turn.** `permissionDecision: "allow"`
  skips the permission check entirely.
- **A `Stop` block once works.** `{"decision":"block","reason":"…"}` reaches the model as "Stop
  hook feedback". The second Stop has `stop_hook_active: true`, and exiting 0 with no output lets
  it stop. The Stop input carries `last_assistant_message`. Cost: one more call over the full
  context. **If the run is already at `--max-turns`, the block still fires and the run ends in
  `error_max_turns` with `result: null`**; the text is only in the stream's last assistant
  message.
- **Hook inputs:** `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `permission_mode`
  and `prompt_id` arrive on stdin; `PostToolUse` also gets `tool_name`, `tool_input`,
  `tool_response` and `duration_ms`. `SB_*` env vars set on the `claude` process reach the hooks.
- **The transcript is one turn behind at `PostToolUse`.** The newest assistant entry is missing or
  holds a streaming snapshot (`output_tokens` 74 against a final 230). At the first Stop it held no
  assistant usage at all. Mid-run spend can't come from the transcript alone.
- **Failures never fail the run.** Exit 1 is logged and ignored. Exit 2 on `PostToolUse` feeds
  stderr to the model. A timeout is cancelled. `--include-hook-events` emits `hook_started` /
  `hook_response` events with exit code and outcome.
- **SessionStart stdout reaches the model** as a system-role block just before the environment
  section, ahead of the user prompt, so it sits in the prefix. Output that changes between runs
  breaks the cache from there on.
- `claude -p` waits 3 s for stdin and warns. The runner starts it with `< /dev/null`.
