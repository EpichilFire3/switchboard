# switchboard and epf3-skills

Every repo uses [`epf3-skills`](../../epf3-skills/). switchboard does not replace any of its
pipeline. It **drives** that pipeline unattended and **carries its gates to Telegram**. This
doc covers how the two fit together and what to add to `epf3-skills` for that.

## 0. Scope rule: apps never carry the harness

epf3-skills builds the apps too, not only the app builder. So:

| Kind of change | Where it goes | In a default `setup.py` install? |
| --- | --- | --- |
| General improvements (`Next:` line, `[behaviour\|architecture]` tags, tracker features in [tracker.md](tracker.md) §3 marked epf3, the `implement` → `implement-tests` fix) | epf3-skills | yes. Useful in any repo |
| Harness paragraphs inside skills ("when `SB_RUN_ID` is set …") | epf3-skills | yes, but **inert**: nothing sets `SB_RUN_ID` outside a switchboard run. They cost a few lines of context when a skill loads |
| `harness-mode` (the contract) and `guard-harness.py` | epf3-skills, next to the skills they govern | **no.** Only `setup.py --harness <slot>`, which only switchboard passes, for its own worktree slots |
| Harness-only skills (`/triage`) and everything `sb` | the switchboard repo (`.claude/skills/triage/`) | no. epf3 never installs them |
| `session-brief.py` harness branch | epf3-skills | yes, but it is the same hook with an early branch, and it returns the old output without `SB_RUN_ID` |

The owner's working checkouts and every app repo get a plain install. Only the slots
`~/.switchboard/wt/<repo>` get `--harness`.

## 1. Where the two fit already

| epf3 has | switchboard uses it as |
| --- | --- |
| GitHub Issues with native sub-issues and `blockedBy`; "the frontier is one query" (`manage-tickets/github.md`) | The ready set for the scheduler. Nothing is duplicated |
| `to-tickets`: "each ticket can be picked up cold in one fresh context window" | Each ticket fits one run. Matches the fresh-session + context-pack default |
| Ledgers (`.brainstorm/`, `.implement/`, …) that survive `/compact` | Durable state the context pack *points to* instead of copying |
| Reports ending in `Next: /<cmd> <n>` | The tick runner's next command, parsed deterministically (§3.2) |
| Gates (brainstorm rounds, experiment cards, diagnose gate, `/ship` merge, devops production `yes`, wizard steps) | `GATE` messages on Telegram (§3.1) |
| `manage-tickets` rules: no progress comments, claim by orchestrator, markers on every write | Respected. Handoffs live in switchboard packs, not issue comments; `sb-tick` is the orchestrator that claims |
| `guard-git.py`, `guard-dispatch.py` | Stay on in harness runs |
| `discovered` label | Discovered work, not ready until the owner accepts it |
| `docs/adr/` | Where owner `ARCH` decisions that settle an architecture end up (through `brainstorm` → `to-spec`) |

## 2. The conflict to design around

epf3 marks fourteen skills **you type**: Claude cannot start them, it names the command and
stops. That human-in-the-loop property is deliberate. In switchboard, **the runner does the
typing** (`claude -p "/implement 412"`), which would quietly remove the human from every step
unless the harness puts the gate back.

Rule: **the runner may type a command only if the auto-advance policy allows it, or the owner
tapped it.** Two commands are never auto-typed, in any configuration: `/ship <n> merge` and any
devops production command. Both are enforced by `sb-tick`'s command allowlist **and** by a guard
hook (§3.6).

## 3. Proposed additions to epf3-skills

**Status (2026-10-25):** implemented and committed in epf3-skills (`a22c02b`, "feat: lsp,
trailhq, harness mode") and pushed to `EpichilFire3/epf3-skills` (private). That repo has no
integration branch: work lands on `main`, and `guard-git.py` allows pushes there for that repo
only. `triage` lives in switchboard.

| § | Item | Status |
| --- | --- | --- |
| 3.1 | Async gates | Done: `skills/harness-mode/{SKILL.md,gates.md}`, plus a pointer at every gate in 15 skills |
| 3.2 | Machine-readable `Next:` line | Done in every report template. `implement` now says `Next: /implement-tests <n>`; it used to say `/ship`, which was a bug |
| 3.3 | Question-kind tag | Done: `brainstorm` rounds use `Q1. <title> [behaviour\|architecture]` |
| 3.4 | `question` / `answer` comment kinds | **Dropped 2026-10-27.** Q&A stays off GitHub: questions and answers live only in the switchboard database |
| 3.5 | Terse SessionStart brief | Done: `session-brief.py` under `SB_RUN_ID`, deterministic |
| 3.6 | `guard-harness.py` | Done, smoke-tested. Installed only with `setup.py --harness`. Approval files are at `~/.switchboard/approvals/<SB_RUN_ID>/<action>` |
| 3.7 | `triage` skill | Done, and **moved to switchboard** (`.claude/skills/triage/`). It runs in switchboard's checkout and reads siblings at `../<repo>` |
| 3.8 | Scheduled-job output for `research` / `recon` | Done: an `sb-items` JSON schema, at most 8 items |
| 3.9 | `/feedback` from Telegram | switchboard side; nothing to change in epf3 |

The original proposals follow.

Ranked by how much they unblock. Each is small and changes no existing behaviour outside harness
mode, which is detected by `SB_RUN_ID` being set.

### 3.1 Async gates: `skills/_shared/async-gates.md` (highest value)

A shared reference that every gate-holding skill reads:

> If `SB_RUN_ID` is set, you cannot wait for an answer. At the gate: render each question with
> `sb ask` (category, options, recommendation and trade-offs exactly as the round would show
> them), write the skill's ledger as usual, run the wrap-up protocol, and end the run. The
> owner's answers arrive in the next run's prompt. Continue from the ledger.

Each gate skill (`brainstorm`, `experiment`, `diagnose`, `ship`, `devops`, `wizard`) gets one line
pointing to it at each gate. `brainstorm`'s round format already matches `sb ask`
(options + recommendation + trade-offs), so a round becomes one `--round` group.

### 3.2 A machine-readable `Next:` line

Make the last line of every report exactly `Next: /<cmd> <args>` or `Next: none`, plus an
optional `Gate: <kind>`. The harness parses it with a regex, no LLM, and checks the
auto-advance policy, e.g.:

| Next | Default policy |
| --- | --- |
| `to-spec` after a brainstorm greenlight | auto |
| `/to-tickets <spec>` | owner tap (it freezes the spec, and the spec commit is "your call") |
| `/implement`, `/implement-tests`, `/run-tests` | auto |
| `/ship <n>` (open PR) | auto |
| `/ship <n> merge` | **owner tap, always** |
| devops Release / production | **owner tap, always** |

### 3.3 A question-kind tag on gate questions

Each question carries `behaviour` or `architecture` (or `gate`), which becomes the `sb ask`
category. `brainstorm` already separates user-facing behaviour from implementation choices
informally. A tag makes the split explicit and routes the two to different notification styles.

### 3.4 Two new comment kinds in `manage-tickets` (dropped)

> **Dropped 2026-10-27.** `kind=question` and `kind=answer` are not added. Questions, answers and
> ideas never touch GitHub in Phase 0, and nothing needs defining once Q&A stays off the tickets.
> The original proposal is kept below for the record.

- `kind=question`: when a run parks a ticket on the owner. This is the existing `blocked`
  comment with the question and the Telegram link.
- `kind=answer`: the owner's answer, written by `sb-inbox`, with the agent line
  `> *Owner via Telegram | …*`.

This keeps the issue timeline the audit trail, the way epf3 intends, without adding progress
comments.

### 3.5 A terse SessionStart brief in harness mode

`session-brief.py` prints the lane table and ledgers in flight. Under `SB_RUN_ID` it should print
only the ledgers relevant to the ticket. The output should be deterministic for a given repo
state, so it is cheap and stays stable for the cache.

### 3.6 `guard-harness.py` (PreToolUse, harness mode only)

Denies the never-auto actions unless the harness wrote an approval file for this run,
`~/.switchboard/approvals/<SB_RUN_ID>/<action>` (`merge-<pr>`, `push-development`, `production`).
`sb-tick` finds the PR number for `merge-<pr>` with `gh pr list --head <branch>`. It denies: merging PRs (`gh pr merge`), pushing to `development`/`main`, devops production
commands, and editing `~/.switchboard/`. Together with the runner's allowlist, it is the actual
barrier for never-auto actions, not defence in depth: `disable-model-invocation` does not stop
the model from invoking a skill whose exact `/name` appears in its context
([verification.md](verification.md) §6).

### 3.7 A `triage` skill (now in switchboard, `.claude/skills/triage/`)

Input: one verbatim owner message. Output: `{repo, lane, title}`, or a one-question `sb ask`
when the message is truly ambiguous. This is rung L4 of the routing ladder
([telegram.md](telegram.md) §5). Note: `side-projects` is not a git repo, so `setup-skills` does
not install there today. Triage needs either a small install target for the parent folder or its
own `.claude/skills/`.

### 3.8 Harness-mode output for `research` and `recon` (for `SCHEDULED` jobs)

When a run is a scheduled job, `research` (suggested features) and `recon` (cleanup drift) end
with a list of items. Each item has a title, one line of why, and a size, so `sb-inbox` can show
[accept] [reject] per item. Accepted items become `/brainstorm` ideas or `discovered` tickets.

### 3.9 `/feedback` from Telegram

A Telegram `/feedback <text>` command (or a reply to any harness message) that files an epf3
`feedback` issue. It closes the loop when a skill misbehaves in an unattended run.

## 4. What stays in the switchboard repo, not epf3-skills

The `sb` CLI, the daemons, the hooks that enforce budgets, the static preamble, and the
harness-only skills (`.claude/skills/triage/`). The budget hooks reach runs through
`--settings`. The wrap-up protocol is in epf3's `harness-mode`, which is installed into slots with
`setup.py --harness`.
