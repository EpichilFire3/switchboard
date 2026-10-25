# Scheduler, budgets and fan-out

## 1. The tick

`sb-tick` is started by a systemd user timer in WSL every 30 minutes (Windows side in
[architecture.md](architecture.md) §6). One tick runs **at most one ticket**:

1. **Lock.** Take `~/.switchboard/tick.lock`. If a run is already going, exit; ticks never
   overlap.
2. **Gates.** Exit (zero tokens) when any of these hold: limits exhausted until `reset_at`; the
   5-hour window is above `FIVE_HOUR_STOP` (85%); on battery (optional, read through
   `powershell.exe`); the owner has paused the harness (`/pause` in Telegram).
3. **Pick.** Choose a ticket with the scoring below.
4. **Prepare.** Branch or worktree for the ticket, then start fresh or resume per
   [prompt-cache.md](prompt-cache.md) §3.2, then build the prompt.
5. **Run.** `claude -p …` under a wall-clock timeout, with the budget hooks active.
6. **Record.** Usage, cost-equivalent units, outcome, the final `Next:` / `Gate:` lines, and any
   new questions. Build the deterministic digest ([prompt-cache.md](prompt-cache.md) §3.5).
   The Haiku handoff is built later, and only if the ticket's next start turns out to be FRESH.
7. **Release** the lock.

If nothing is ready because every branch is waiting on the owner, the tick costs nothing. It
sends at most one nudge per 4 hours: "everything is waiting on you: 3 questions".

## 2. Unfair on purpose

Plain round-robin spreads the work evenly and the cost badly: every switch means a cold cache, a
re-read of context, and half-finished trees in several repos at once. switchboard deliberately
favours **finishing what is open** and **using warm caches**, and pays the fairness back later.

### 2.1 Ticket score: what a run closes, per unit it spends

Each candidate is scored by **value per expected spend**. A cheap run that closes a lot comes
first, and an expensive run that closes little comes last. Both halves are deterministic and come
from the tracker and the run log:

```
value(t) =  V_CLOSE                                   # the ticket itself
          + V_UNBLOCK · tickets_it_unblocks(t)        # open tickets with t as their only open blocker
          + V_EPIC    · closes_epic(t)                # t is the last open child of its epic
          + V_FINISH  · siblings_done_fraction(t)     # nearer the end of an epic is worth more
          + V_ANSWER  · owner_answered_since_last_run(t)   # the owner already spent time on it
          + V_PRIO    · priority(t)                   # owner-set, default 0
          + V_AGE     · age_days(t)
          − V_NEWROOT · starts_new_epic(t)            # opening a new front while others are open

spend(t) =  start_cost(t)                             # from prompt-cache.md §2: warm resume ≈ 0.1×(S+H),
                                                      #   cold resume ≈ 2×(S+H), fresh ≈ 0.1×S + 2×P + re-read
          + work_cost(size(t), repo(t))               # median cost of runs of that size in that repo
          × runs_to_close(t)                          # 1 for most tickets; from the handoff's own
                                                      #   estimate or the repo's history otherwise

score(t) = value(t) / spend(t)  −  W_REPO · normalized_vruntime(repo(t))   # fairness, see 2.2
```

The cache needs no separate bonus. A warm ticket's `start_cost` is a twentieth of a cold one's,
so the ratio rewards warm resumes by itself.

Only tickets in the **ready set** are scored: open, no open blocker, no pending owner question,
not over the stuck threshold.

Starting values, to tune from the tick log: `V_CLOSE 10`, `V_UNBLOCK 5`, `V_EPIC 20`,
`V_FINISH 10`, `V_ANSWER 30`, `V_PRIO 10`, `V_AGE 0.5`, `V_NEWROOT 15`, `W_REPO` sized so that
one day's fair share of difference is worth about one `V_EPIC`. Until there is history,
`work_cost` is a per-size constant.

### 2.1a Yield: catching epics that spend without closing

After each run, the harness updates the yield of every open epic: tickets and acceptance criteria
closed per cost-equivalent spent, over its last 10 runs.

- **Low yield** (bottom quartile across open epics, after at least 5 runs): the epic's `value`
  terms are halved, and the digest flags it: "epic *Report preview* has spent 30% of this week and
  closed 1 of 9 tickets: [keep going] [re-split] [pause]".
- **Recovery:** the halving lifts automatically once its yield climbs back above the median.

This is the owner's "weigh the spend against how much it closes", applied to whole epics as well
as to single tickets.

### 2.2 Paying fairness back: virtual runtime per repo

Each repo has a `vruntime`, in the style of Linux's CFS. Every run adds its cost-equivalent units
to the repo's `vruntime`. The `W_REPO` term pulls toward repos that are behind. The boosts in 2.1
let a repo **borrow ahead** of its fair share while it is closing an epic. Once that epic closes,
the boosts disappear, and the repo's inflated `vruntime` keeps it low-priority until the others
catch up. Being boosted while open and lowered once resolved falls out of the same mechanism,
with no extra rules. Pacing (2.3) adjusts how strong the pull back to fairness is: when the
budget runs ahead of the week, `W_REPO` drops so that closing wins; when it runs behind, `W_REPO`
and `V_NEWROOT` both relax so that idle repos and new ideas get turns.

- **Starvation floor.** A repo with ready work that has not run in `STARVE_HOURS` (8) is picked
  next regardless of score.
- **Boot and day reset.** `sb boot` (run once when WSL starts) and the first tick of each day
  set every repo's `vruntime` to the current minimum. This restarts the round-robin for the day
  without erasing the order inside the day.

### 2.3 Pacing to the usage budget

The owner splits the subscription limits by day. `pace = used_fraction / elapsed_fraction` is
measured over the weekly window, and the day's target is the weekly share for that day
(configurable, e.g. weekdays heavier).

| Pace | Behaviour |
| --- | --- |
| < 0.8 (under-using) | Exploration allowed: new epics (still gated by the owner), `SCHEDULED` jobs, idea triage. Optional burst: ticks every 10 min |
| 0.8 – 1.1 | Normal |
| > 1.1 (over-using) | Closing work only: answered, warm, in-flight. No `SCHEDULED` jobs, no new epics |
| weekly > 90% | Only tickets with an owner answer waiting |

## 3. Budgets per run

Each ticket has a size, which sets its budget. The agent proposes the size when the ticket is
created. The harness clamps it.

| Size | Wall clock | Turns | Cost-equivalent units |
| --- | --- | --- | --- |
| S | 8 min | 25 | tuned from data |
| M | 15 min | 50 | tuned from data |
| L | not allowed as a single run: must be split | | |

The wall clock is always shorter than the tick interval.

**The whole budget goes to the ticket.** Summarising for the next run is not the worker's job,
because a budget spent carrying a task forward could have been spent finishing it. The handoff
is built by the harness afterwards, with Haiku, only when it is needed, and booked as harness
overhead ([prompt-cache.md](prompt-cache.md) §3.5). The worker's own wrap-up costs a few
tool calls (§4).

**Enforcement, all deterministic:**

| At | Mechanism | Effect |
| --- | --- | --- |
| 80% | `PostToolUse` hook returns `additionalContext`, once | "80% of this run's budget is used. Finish the step in hand, commit it, then wrap up." |
| 100% | `PreToolUse` hook | Denies every tool except the `sb` CLI and `git commit` on the ticket branch |
| 110% or wall clock | `sb-tick` sends SIGTERM, then SIGKILL | The run is recorded as killed. The digest and handoff pipeline treats it like any other run |

The hooks read the budget from env vars that `sb-tick` sets (`SB_RUN_ID`, `SB_BUDGET_*`) and the
usage so far from the transcript. They are no-ops when `SB_RUN_ID` is unset, so they never touch
the owner's interactive sessions. Harness overhead (digests, Haiku handoffs, routing) is tracked
separately in the run log and counts against the *daily* pace, not against any run.

## 4. Wrap-up protocol (what every run must do)

Taught by the static preamble and epf3's `harness-mode` skill:

1. Commit WIP to the ticket branch. Never to `development` or `main`. epf3's `guard-git.py`
   and `guard-harness.py` block the dangerous cases.
2. `sb status --ticket <n> <progress|blocked|done|needs-split>`.
3. `sb decide …` for each decision made in this run. One line each, appended to the decision
   log.
4. `sb ask …` for any question still open. The ticket becomes blocked.
5. End with the final lines: `Gate:` if any, then exactly one `Next:`. The harness parses them
   with a regex.

That is all. The worker writes no handoff note.

## 5. Fan-out rules (enforced by `sb split`, not by prompts)

A ticket that will not fit in one run gets `needs-split`. The agent proposes children as JSON
through `sb split`, and the harness accepts or rejects the proposal. `sb split` is the one choke
point, with four rules and about 130 lines. No tracker provides this, so it is built here
whichever tracker is used ([tracker-report.md](tracker-report.md) §5):

| Rule | Limit |
| --- | --- |
| Depth | Epic → ticket → subtask. `to-tickets` creates the first two levels and only `sb split` creates the third. A ticket with open subtasks is a container: not ready itself, and closed by `sweep` when its children close |
| Children per split | ≤ 5 |
| Splits per run | ≤ 1 |
| Open tickets per repo | ≤ 15. Beyond that the split is **refused**: the ticket parks as `needs-split` and a `HARNESS` message goes out. There is no queued state |
| Each child | Must have acceptance criteria that are false today, and size S or M |
| New epic | Always an owner `GATE` |
| Discovered work | Filed with the `discovered` label (an epf3 convention) and **not ready** until the owner accepts it in the digest |

**Stuck detection.** A ticket with 3 runs and no progress (no new commit, no criterion ticked,
the same "next" in the handoff) is parked. It sends a `HARNESS` message: "#n is stuck: [show
handoff] [re-split] [drop] [I'll take it]".

## 6. Laptop off, restarts, and limits

- **Laptop off or asleep.** Ticks simply do not fire. Missed ticks are never caught up.
- **Restart.** WSL boot runs `sb boot`: fairness reset (2.2), stale-lock cleanup, and salvage of
  any run that was killed by the shutdown.
- **Limits exhausted.** A run that fails on a usage limit, or a snapshot over the threshold, sets
  `paused_until = reset_at`. Ticks exit at the gate until then. The first tick after the reset
  does a day reset.
- **Cloud.** Not now. Later, selected tickets may be marked `cloud_ok` for `/schedule`
  routines.

## 7. Usage (`UTIL`) messages

Sent to the Usage topic:

- End of each 5-hour window and end of day, when the remaining budget is above
  `UTIL_NOTIFY_MIN` (20%): "You have X% of today's budget left (Y% of the week). Waiting on you:
  N questions. Top open items: …" with buttons **[burst now]** **[add idea]** **[fine]**.
- End of week and end of month: the same, plus closed epics and decisions made.

Where the percentages come from is an open question: the statusline does not run under `-p`
**(verify)**. The candidate sources are in [BRAINSTORM.md](BRAINSTORM.md).

## 8. Scheduled jobs (`SCHEDULED`)

`~/.switchboard/jobs.yaml` holds the jobs, for example:

```yaml
- name: suggested-features
  repos: [all]
  cadence: weekly
  when: [pace_below: 0.9, repo_has_no_ready_tickets]
  skill: research            # epf3 skill; output is a list of suggestions
  size: M
  output: scheduled-message  # each item gets [accept → brainstorm idea] [reject]
- name: codebase-cleanup
  repos: [all]
  cadence: biweekly
  when: [pace_below: 1.0]
  skill: recon               # refresh the map, list dead code and drift
  size: S
  output: discovered-tickets
```

A job is just a ticket the harness creates on schedule, so the same budgets and limits apply.
