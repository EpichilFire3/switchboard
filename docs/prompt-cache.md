# Prompt cache policy

Ticks are 30 minutes apart, so cache behaviour drives the harness's cost more than anything
else. This doc covers how the cache behaves, what that means for ticks, and the policy that
follows.

Facts marked **(verify)** must be checked against the installed Claude Code version (2.1.251
on 2026-10-24) before code depends on them. §5 says how.

## 1. How the cache works (the parts that matter here)

- **It caches prefixes.** A request is served from cache up to the longest prefix that exactly
  matches an earlier request. The order is tools → system prompt → messages. If one byte changes
  early, everything after it is a miss.
- **TTL: 60 minutes, counted from the last use.** Claude Code on the owner's subscription caches
  for an hour. Every hit refreshes the clock, so a session's cache expires 60 minutes after its
  **last** request, which is the end of its run, not the start. In usage overage the TTL drops to
  5 minutes (observed, **verify**).
- **Prices, as API-equivalent multipliers of base input:** 1-hour write 2×, 5-minute write
  1.25×, read 0.1×. Subscription limits are not published as token formulas. Assume they weight
  the same way until measured.
- **Scope.** The cache belongs to the account, not to the session. Two *different* sessions with
  an identical prefix share it.
- **Changing model means a cold cache.** Opus, Sonnet and Haiku keep separate caches.

## 2. What that means for ticks

Let `S` be the static prefix (tools + system prompt + CLAUDE.md + skill listing, roughly
20–40k tokens), `H` the session history, and `P` a context pack (~3–5k tokens). The cost of the
first request of a run, in base-input units:

| Start mode | Cache state | Cost of first request | Notes |
| --- | --- | --- | --- |
| Resume | warm | 0.1 × (S + H) | Cheapest, with full working memory |
| Resume | cold | 2 × (S + H) | **Worst case.** 100k of history costs 200k |
| Fresh + pack | static prefix warm | 0.1 × S + 2 × P | Same repo ran within the hour |
| Fresh + pack | cold | 2 × (S + P) | Plus re-discovery: the agent re-reads files it needs (10–30k) |

**Cache life per ticket.** A run ends ~10–15 minutes into its tick, so the session that worked
the ticket stays warm until about `run end + 60 min`:

| Next run of this ticket | Gap since its last request | Cache |
| --- | --- | --- |
| Next tick (+30 min) | ~15–20 min | warm |
| Two ticks later (+60 min) | ~45–50 min | warm, inside the margin |
| Three ticks later (+90 min) | ~75–80 min | cold |

**Consequences:**

1. **Resuming is the default whenever the ticket ran within the last hour.** With two active
   repos alternating, each comes back warm. Cold starts begin when three or more repos rotate
   strictly, or when the owner takes hours to answer.
2. **The scheduler keeps the cache warm.** It favours finishing the epic in flight, so the same
   ticket or its siblings tend to come back within an hour. Warm resume is the cheap row, and
   the cost term in the scheduler ([scheduler.md](scheduler.md) §2) prices it in.
3. **Owner answers within the hour resume the session that asked.** It has full context and a
   warm cache.
4. **Fresh + pack is for cold starts and for long sessions.** Resuming 100k of cold history
   costs more than a pack plus some re-reading. Past ~80k a session also suffers from context
   rot, warm or not.

## 3. The policy

### 3.1 Clocks are kept by the harness, never shown to the model

For every Claude session, `switchboard.db` stores `last_request_at` (the timestamp of the last
assistant event in the transcript) and `ttl_seconds` (measured, §5). From those it computes
`cache_expires_at = last_request_at + ttl_seconds`. The owner's idea of a "cache expires at"
mark on each ticket lives here, as scheduler data. It is **not** in the prompt: a timestamp
anywhere in the prefix changes it on every run and defeats the cache. The model has no use for
it anyway.

### 3.2 Choosing how to start a run

```
if ticket has a session and now < cache_expires_at - margin (5 min)
      and H < H_MAX (≈ 80k)
      → RESUME warm      (claude -p --resume <id>)
elif ticket has a session and H < H_SMALL (≈ 15k)
      → RESUME cold      (cheap enough that a pack saves little)
else
      → FRESH + pack     (claude -p --session-id <new uuid>)
```

`H` comes from the last `usage` record in the transcript (input + cache_read + cache_creation).
This is deterministic: no LLM is involved.

### 3.3 Running early to beat the clock

When the owner answers a ticket whose session is still warm, and the next scheduled tick would
start after `cache_expires_at - margin`, `sb-inbox` triggers an **out-of-band run for that
ticket now**. With a 60-minute TTL this matters mostly when the owner answers 40–55 minutes
after the asking run. Otherwise the answer waits for the normal tick, where the scheduler
weights it heavily.

Guards: at most one out-of-band run in flight, it counts against the daily budget, and it obeys
the same gates as a normal tick.

### 3.4 Keeping the prefix stable (so `S` is shared)

- **The harness preamble is static text** (the tick protocol, budget rules, how to call `sb`),
  passed through `--append-system-prompt` (**verify** the flag, or a file variant) and
  byte-identical every run. No timestamps, ticket IDs, budget numbers or repo names.
- **Everything dynamic goes at the end, in the user prompt:** the ticket, the pack, the owner's
  answers, the budget.
- **Hook messages arrive late**, after the cached prefix, so they cost nothing. This includes
  the PostToolUse budget notices.
- **SessionStart output must be deterministic.** epf3's `session-brief.py` has a terse,
  deterministic variant under `SB_RUN_ID` (in epf3-skills).
- **One model per lane per repo,** so tickets in the same repo share the static prefix.

### 3.5 Handoffs and context packs: built by the harness, after the run, with Haiku

The worker does **not** write a summary. Its budget goes to the ticket. It only commits, sets
`sb status`, and ends with the final lines ([epf3 harness-mode](../../epf3-skills/skills/harness-mode/SKILL.md)).
The handoff is built afterwards by the harness, outside the run's budget, and is booked as
harness overhead:

1. **A deterministic digest, after every run, at no token cost.** It is pulled from the
   transcript JSONL and the repo:
   - the last 3 assistant text blocks, with the final `Next:` line
   - the files edited (from tool_use records) and the todo-list state
   - `git log` / `git diff --stat` on the ticket branch
   - the last test command and its exit code
   - the questions asked and the decisions recorded

   Stored at `~/.switchboard/packs/<repo>/<ticket>.digest.json`. The digest also feeds the step
   log and the daily digest message.
2. **The handoff is built lazily.** It is made only when the scheduler has decided the ticket's
   next start is **FRESH**, which means the cache went cold or the session grew too long. A warm
   resume needs no handoff, so most runs never pay for one.
3. **Model: always the cheapest.** `claude -p --model claude-haiku-5-5 --effort low
   --max-turns 1` (**verify** the effort flag) reads the *digest*, never the full transcript (a
   different model gets no benefit from the worker's cache). It writes the pack's handoff
   section to a strict JSON schema.
4. **The pack** (`~/.switchboard/packs/<repo>/<ticket>.md`) has fixed sections and is capped at
   ~4k tokens:
   - **Ticket:** copied from the tracker, verbatim.
   - **Where it sits:** the parent epic in one paragraph, and siblings one line each.
   - **Decisions:** for this ticket or its epic.
   - **Owner answers since the last run:** verbatim.
   - **Handoff:** done / next / gotchas / files / verify-commands. This is the Haiku part.
   - **Pointers:** paths to the ledger, spec and branch, with no file contents.
5. **Validation is deterministic:** every section is present, the pack is under the cap, the
   branch exists, and the files exist. If validation fails, Haiku retries once with the error. If
   it still fails, a `HARNESS` message asks the owner: "#n has no usable handoff; restart from the
   ticket alone? [yes] [show me]".

A run that died (timeout, crash, killed at the hard budget) goes through the same pipeline.
Nothing is special about it.

## 4. Interaction with interactive sessions and Channels

- **Never `--resume` a session the owner has open in VSCode.** Harness sessions belong to their
  ticket. The owner can open any of them from VSCode's history to look.
- **A Channels session** (optional live lane) has its own cache life, outside this policy.

## 5. Measure, don't assume

Every run uses `--output-format stream-json`. The `result` event and each assistant event's
`usage` carry `input_tokens`, `output_tokens`, `cache_read_input_tokens` and
`cache_creation_input_tokens`, plus a breakdown by TTL
(`cache_creation.ephemeral_1h_input_tokens` / `ephemeral_5m_input_tokens`) **(verify the field
names)**. `sb-tick` stores all of them per run, and from them derives:

- **The TTL actually in use**, from which ephemeral bucket is non-zero. This sets `ttl_seconds`
  and detects overage, when the TTL falls to 5 minutes.
- **The shared-prefix size:** cache_read on the first request of a fresh run.
- **The real cost of each start mode,** used to tune the §3.2 thresholds.
- **A cost-equivalent per run** (`total_cost_usd` in the result event if present, else computed
  from the multipliers). This is the scheduler's spend unit, calibrated against the subscription
  `rate_limits` percentage.

## 6. Defaults to start with

| Knob | Start value | Tune by |
| --- | --- | --- |
| tick interval | 30 min | warm-resume rate vs. budget pacing |
| assumed TTL | 60 min, replaced by the measured value | §5 |
| warm margin | 5 min | early-run hit/miss logs |
| `H_MAX` | 80k | quality of resumed runs vs. fresh runs |
| `H_SMALL` | 15k | measured re-discovery cost of fresh runs |
| pack cap | 4k tokens | how much fresh runs re-read |
| summariser | `claude-haiku-5-5`, effort low, 1 turn, lazily on FRESH | handoff validation failures |
| early run on a warm answer | on, max 1 in flight | daily budget burn |
