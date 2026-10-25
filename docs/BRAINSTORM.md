# Open questions to brainstorm

Each topic below should go to an agent (`/brainstorm` in this repo unless noted). Each states
the question, why it matters, and what is already known, so it can be picked up cold. Topics
marked **measure** are better settled by `experiment` than by argument. Topics marked
**research** need outside facts first.

Recommended order: A → B → C before Phase 0/1 code. The rest can run in parallel once Phase 1
logs exist.

## A. Foundations (blocks Phase 0/1)

1. **Is unattended headless use on a subscription within the terms?** Settled 2026-10-25: OK,
   with caveats ([verification.md](verification.md) §1). The terms allow scripted use of the
   unmodified `claude` binary with the owner's own login. switchboard never touches the token,
   only the owner can command it, and it stops at the plan's limits. Re-read the Agent SDK /
   `claude -p` plan article before Phase 1; that policy moved four times in 2026.
2. **Where do the usage percentages come from under `-p`?** Settled 2026-10-25
   ([verification.md](verification.md) §2). Primary: the `rate_limit_event` that every
   stream-json run emits (`unifiedWindows.five_hour` / `seven_day`, 0 to 1, from the API's
   `anthropic-ratelimit-unified-*` response headers). Fallback when idle: headless
   `claude -p "/usage"`, which makes no model call. The statusline never runs under `-p`.
3. **Tracker.** Settled 2026-10-24: see [tracker.md](tracker.md). What is left is
   building it (an Opus session), plus one decision inside it: may agents create `area:` labels
   (tracker.md §2)?
4. **Permission model for unattended runs.** Repo allowlist + harness settings, vs. auto mode,
   vs. a sandbox (devcontainer / separate WSL user). What may a run do without the owner: install
   deps? run migrations? touch the network? `--dangerously-skip-permissions` (and
   `--permission-mode bypassPermissions`, the same thing) is ruled out; `--permission-prompts
   none` makes unallowed actions deny instead of hang.
5. **Which clock?** The owner's call. Windows Task Scheduler driving `wsl.exe` (knows sleep,
   battery, logon, missed runs) vs. systemd timers inside WSL. New facts
   ([verification.md](verification.md) §9, [ARCHITECTURE.md](ARCHITECTURE.md) §6): the distro
   stops ~15 s after the last `wsl.exe`-attached process ends, systemd services do not count as
   activity, and `vmIdleTimeout` is the VM's setting, not the distro's. Whatever the clock,
   something Windows-side must hold a `wsl.exe` session open for `sb-inbox` (candidate: run
   `sb-inbox` itself from a logon task). Open: does `instanceIdleTimeout=-1` hold on this WSL
   (2.3.26; issue #13416)? What happens to a run when the lid closes mid-run?
6. **Auto-advance policy for epf3's `Next:` chain.** Which steps run on their own and which need
   a tap. Merge and production are never automatic ([skills-extensions.md](skills-extensions.md) §2–3.2).
   Brainstorm this *with the epf3-skills repo open*.

## B. Cost and the cache

7. **Confirm the cache facts.** (measure) Partly done 2026-10-25
   ([verification.md](verification.md) §4, §8): the TTL is 1 hour (warm at 45 minutes, cold at
   65), and two fresh sessions share ~26k, with git state making no difference. Loading less is
   settled ([verification.md](verification.md) §10): the harness load flags take a fresh start
   from 45.6k to 35.5k, and the unshared tail from 19.6k to 9.5k. claude-mem is not the cause;
   the tail grows with the skill listing. Still open:
   - A per-lane pruned skill set in the slot: how much of the 9.5k tail does it save, and is it
     worth a second install shape?
   - Why the byte-identical tail never matches across sessions.
   - The real cost of the four start modes in [prompt-cache.md](prompt-cache.md) §2, with the
     load flags.
8. **Thresholds**: `H_MAX`, `H_SMALL`, the warm margin, the pack cap. Is the early run on a
   warm answer worth it, or does it wreck pacing?
9. **The budget unit.** Cost-equivalent units vs. tokens vs. wall clock. How each size (S/M)
   maps to them. How to convert a weekly subscription percentage into a daily budget, and how to
   split it across weekdays.
10. **Model per lane.** Opus for design and architecture questions, Sonnet for implement/test
    runs? Haiku 5.5 low is settled for summaries, routing and every fallback. Keeping one model
    per lane keeps the static prefix shared.

## C. Scheduling and the ticket tree

11. **Scheduler weights.** The starting numbers in [scheduler.md](scheduler.md) §2.1
    are guesses. Define the tick-log metrics that tune them: epic lead time, cold-start rate,
    starvation events, owner wait time.
12. **Fan-out limits and stuck detection.** Depth 3, children ≤ 5, open per repo ≤ 15,
    epics in progress ≤ 2, stuck after 3 no-progress runs. Are these right? What counts as
    "progress" deterministically?
13. **The ideas queue vs. epf3's pipeline.** Ideas live in `switchboard.db` until a
    `/brainstorm` settles them. How many ideas may be in brainstorm at once per repo? Who
    greenlights?
14. **Owner-active detection.** Skipping a repo when a non-harness transcript was written in
    the last 10 minutes. Enough? What about the owner editing files without Claude?

## D. The owner's interface

15. **Telegram UX.** The header format, rounds, the digest layout, urgency to notification
    sound, which commands to have. How to keep noise low enough that the owner still reads
    `high` messages. Mock the messages first (as a `/wizard`-style walkthrough on the real bot).
16. **Routing ladder thresholds** (measure): `T_ABS`, `T_RATIO` and the L3 confidence cutoff,
    from a labelled set of the owner's real idea messages. What goes into a repo digest.
17. **Self-editing.** Settled in outline ([ARCHITECTURE.md](ARCHITECTURE.md) §6b):
    installed releases, a contract version, pinned epf3 worktrees. Still open: should `sb upgrade`
    run automatically after a merge, and what does the dry-run tick check?
18. **The decision log.** One log in `switchboard.db`, mirrored to markdown, plus tracker
    `answer` comments, plus ADRs for architecture. Is that one place too many? What does the
    owner actually read weekly?
19. **LAN dashboard** (Phase 3). Read-only status page over WSL mirrored networking. Is it
    needed if the digest is good?

## E. Integration with epf3-skills

20. **The async-gate adapter** ([skills-extensions.md](skills-extensions.md) §3.1).
    Design it in the epf3-skills repo: the exact text each gate skill gets, and how a
    brainstorm round resumes from its ledger plus the answers.
21. **`guard-harness.py` and the never-auto list.** What else belongs on it? It is now the
    barrier, not defence in depth: in one run the model invoked a `disable-model-invocation`
    skill through the Skill tool because its exact `/name` appeared mid-prompt
    ([verification.md](verification.md) §6). Repeat that test a few times, including with
    `/ship <n> merge` in a pack's text, and decide how packs and owner answers neutralise
    slash commands.
22. **Scheduled jobs catalogue.** Beyond suggested features and cleanup: dependency updates?
    test-flake sweeps? doc drift? Each needs a condition, a cadence and an output form.

## F. Robustness

23. **Failure modes.** Telegram down, `gh` auth expired, a corrupt DB, Claude Code
    auto-updating mid-run, a worktree left dirty, the clock skewing after sleep. What does
    `sb doctor` check, and what pages the owner?
24. **Security.** Prompt injection through forwarded content, secret redaction rules, token
    isolation, what a compromised phone could make the harness do (cap it: no merges, no
    production).
25. **Testing the harness itself.** A fake `claude` binary that replays recorded `stream-json`
    output, recorded Telegram updates, and a frozen clock. That way the scheduler and the
    budget hooks can be tested with no tokens spent. Real stream-json captures from 2.1.310
    (tool calls, resumes, `error_max_turns`, `rate_limit_event`, headless `/usage`) are in
    `tmp/verify/` ([verification.md](verification.md)).
26. **Budget hooks under `-p`.** Settled 2026-10-25 ([verification.md](verification.md) §11):
    all three work. The design changes that followed are in [ARCHITECTURE.md](ARCHITECTURE.md)
    §4:
    - Hooks count turns and time themselves, because the transcript lags a turn.
    - `budget_pre.py` never returns `allow`.
    - `stop_final.py` never blocks at the turn limit.
    - Hook outcomes are logged through `--include-hook-events`.

## G. Later

27. **Channels as a live lane.** Worth a second bot? When would the owner use it instead of
    `/remote-control`?
28. **Cloud fallback.** Which tickets are `cloud_ok`, how cloud routines read the same
    tracker, and how results come back to the laptop's state.
