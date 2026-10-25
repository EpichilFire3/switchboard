# Task tracking: decisions and build brief

This is the brief for the agent (Opus) that builds switchboard's task tracking. It holds the
owner's decisions from 2026-10-24 and the features to take from Beads, Task Master and CCPM. The
evidence behind it is in [tracker-report.md](tracker-report.md) (use-case report) and
[evaluations.md](evaluations.md) (neutral evaluation). The cloned sources are in
`tmp/eval-trackers/{beads,claude-task-master,ccpm}` (gitignored), checked out at the commits
[tracker-report.md](tracker-report.md) cites. If they are gone, re-clone `gastownhall/beads`,
`eyaltoledano/claude-task-master` and `automazeio/ccpm` there and check out those commits.

## 1. Decisions (owner, 2026-10-24)

| # | Question | Decision |
| --- | --- | --- |
| Q1 | Backend | **Our own tracker on GitHub Issues + SQLite.** Do not adopt Beads, Task Master or CCPM. Build the best features of all three into it (§3) |
| Q2 | Depth | `to-tickets` stays at 2 levels (epic → ticket). Only `sb split` creates a 3rd. A ticket with open sub-issues is a **container**: never ready itself, closed by `sweep` once its children are closed |
| Q3 | Waiting on the owner | SQLite `questions` is the authority, plus an `awaiting-owner` label. **No GitHub issue per question.** The repos must not fill up with question issues |
| Q4 | Metadata | **Labels, generously** ("the more tags the better"). The full set is in §2 |
| Q5 | Split keys | `CR-03.1`, `CR-03.2`: a one-line title-rule change in epf3 `github.md` |
| Q6 | Sizing | The agent proposes a size when it creates a ticket. The harness clamps it with deterministic signals. Anything bigger than M must be split. No LLM sizing pass |
| Q7 | Beads | Not used, but its best features are extracted **now**, not when a trigger fires (§3.1) |
| — | Blocker semantics | Confirmed: `issueDependenciesSummary.blockedBy` counts **open** blockers only |
| — | GitHub Mobile | Not a requirement. The owner reads through switchboard (Telegram, digest, LAN dashboard). Labels exist for filtering and for the harness, not for the phone app |

## 2. Labels

All of these are created idempotently by `github.md`'s label step. A `★` marks a new label.

| Family | Labels | Written by |
| --- | --- | --- |
| state | `in-progress`, `done` (existing); ★`awaiting-owner`, ★`parked` (stuck or held), ★`deferred` (with a `not-before` date in SQLite) | `sb-tick`, `sb-inbox`, `ship` |
| structure | `Epic` (existing); ★`container` (has open sub-issues; derived, but labelled so it is visible) | `to-tickets`, `sb split`, `sweep` |
| origin | `discovered`, `retro` (existing); ★`harness` (created by switchboard, not by a person or a skill run in a terminal) | as today, plus `sb` |
| size | ★`size:S`, ★`size:M` | `to-tickets`, `sb split`, clamped by `sb` |
| type | ★`type:feature`, `type:bug`, `type:chore`, `type:spike`, `type:research`, `type:decision`. These stand in for GitHub issue types, which are org-only | `to-tickets`, `manage-tickets file/bug`, `sb split` |
| priority | ★`prio:0` … `prio:3` | **owner only** (through `/prio`), mirrored from SQLite by the harness. Agents still never set priority (epf3 rule) |
| stream | ★`stream:<name>`: parallel workstreams within a repo (Task Master "tags") | `to-tickets` (one per epic by default), `sb split` |
| question | ★`q:behaviour`, ★`q:architecture`, ★`q:gate`: the kinds of open questions on the ticket | `sb ask` / `sb-inbox` |
| area | `area:<x>` or the repo's existing family | the epf3 rule is "choose, never create". **Proposed change:** allow creating `area:<x>` when the recon map names the area, so labels can grow with the codebase |
| lane | ★`lane:<skill>`: the epf3 skill the next run starts (`implement`, `implement-tests`, `run-tests`, `ship`, `diagnose`, …), from the last `Next:` line | `sb-tick` |

GitHub allows labels freely at this scale. Each label write is one `gh issue edit`, and the run
batches adds and removes into a single call.

## 3. Features to extract

The **Lives in** column decides placement. **epf3** means the feature is useful in any repo,
harness or not, so it goes into `epf3-skills` (`manage-tickets`, `github.md`, `to-tickets`).
**switchboard** means it only makes sense with the harness running.

### 3.1 From Beads

| Feature (Beads) | Our version | Lives in |
| --- | --- | --- |
| `bd ready --explain` | `sb ready --explain [repo]`: for every open ticket, *why* it is or isn't ready (blocked by #n, awaiting qid, container, discovered and not accepted, parked, deferred until, claimed by run r). A pure function over the snapshot plus SQLite, with no API calls. It feeds `/status`, the digest and the dashboard | switchboard; epf3 gets a `frontier --explain` jq variant |
| Gates (`bd gate`: human, timer, CI, PR) | Human is done (`questions` + `awaiting-owner`). **Add** `not-before` (timer), `waits-ci:<run>` and `waits-pr:<n>` (merged) gates in SQLite. `sb-tick` resolves them deterministically from `gh run view` / `gh pr view`. Check the Beads gate types in `BD/docs/workflows/gates.md` | switchboard |
| Atomic claim with lease and heartbeat | SQLite `claims(ticket, run_id, lease_until)`. The lease is extended on every PostToolUse hook call. `sb boot` and every tick release expired leases and flag the run as killed. The GitHub `in-progress` label mirrors the claim | switchboard |
| Dependency kinds beyond `blocks` and `parent-child` | Non-blocking links as markers in the ticket body: `<!-- epf3:link kind=discovered-from\|caused-by\|related\|supersedes\|validates ref=#n -->`. The snapshot query reads bodies already, so this costs nothing extra. `caused-by` gives a bug its origin; `validates` ties test tickets to features | epf3 (`github.md`) |
| `bd create --graph plan.json` (atomic graph create) | **One plan format and one publisher** for `to-tickets` and `sb split`: `plan.json` (nodes with key, title, body, labels, parent key; edges with blocker and blocked keys). `tickets-apply.py` publishes it idempotently: marker lookup, create the missing nodes, add the missing edges, read back, repair. **This saves tokens**: today the agent runs every `gh` call itself; after this it writes one JSON and runs one command | epf3 (`manage-tickets/tickets-apply.py`), called by `sb split` |
| Cycle detection, `bd dep tree`, `bd graph` (mermaid) | `tickets-apply.py` refuses a plan with a cycle. `sb graph <epic>` renders mermaid for the digest and the dashboard | epf3 (cycle check); switchboard (rendering) |
| `bd prime` / `bd remember` (context priming, durable memory) | Already covered by the context pack and the decision log. **Add** `sb remember "<fact>"` for repo-level facts that outlive tickets (a "we use pnpm" kind of fact). It goes into the pack's Pointers section and the routing digest | switchboard |
| Compaction of closed work | When an epic closes, the harness writes a ≤10-line epic summary (Haiku 5.5 low, once per epic) to `decisions` and the repo's routing digest. Old closed tickets then never need re-reading | switchboard |
| Deferred status | `deferred` label + `not-before` | switchboard (label in epf3's set) |
| Issue types, priority | `type:*` and `prio:*` labels (§2) | epf3 (labels), switchboard (prio writes) |
| Metadata and estimates | Labels for anything you would filter on; SQLite for numbers (estimates, spend, runs) | both |

Skip: hash IDs (GitHub numbers are enough), Dolt and federation, molecules and wisps (Gas
Town orchestration), the HTTP backend.

### 3.2 From Task Master

| Feature | Our version | Lives in |
| --- | --- | --- |
| Complexity analysis (LLM) | **Deterministic** clamp on the agent's proposed size. Signals: the number of acceptance criteria, layers touched (from the recon map), the spec sections cited, and the median spend of finished tickets with the same `type` and `area`. A disagreement above a threshold → clamp up, or require a split. No LLM | switchboard |
| Tags (parallel task lists) | `stream:<name>` labels. The scheduler can focus a stream (`/focus <stream>`) | epf3 (label), switchboard (focus) |
| `testStrategy` per task | A `## Verify` section in every ticket body: the commands that prove the acceptance criteria. `implement-tests` and the digest's evidence read it | epf3 (`to-tickets` ticket template) |
| `scope-up` / `scope-down` | `sb resize <n> S\|M` (owner, or the agent with a reason); a size change is logged | switchboard |
| `next` | Superseded by the scheduler's value-per-spend score | — |
| `expand --num` | `sb split` with the hard caps (≤5 children, ≤1 split per run) | switchboard |

### 3.3 From CCPM

| Feature | Our version | Lives in |
| --- | --- | --- |
| `conflicts_with` / `parallel` | A `## Touches` list in the ticket body (areas or path globs; `sb split` children must declare it). The scheduler avoids starting a ticket whose `Touches` overlaps an **unmerged** sibling branch, which saves merge conflicts even when ticks run one at a time | epf3 (body section), switchboard (scheduler rule) |
| Stream analysis per issue (work split by file scope) | Folded into `sb split`'s plan: each child's `Touches` must be disjoint, or explicitly ordered by a `blocks` edge | switchboard |
| Zero-token status, standup and blocked scripts | `sb status`, `sb standup` (yesterday's moves, today's ready set, waiting on owner) and `sb ready --explain`. All deterministic; they feed Telegram `/status` and the digest | switchboard |
| Epic progress % | From `subIssuesSummary` in the snapshot | switchboard |
| One summary comment, not one per tick | Already an epf3 rule (three comments per ticket's life). Keep it | epf3 |

## 4. Build order

1. **epf3 (general, any repo):** the label set (§2), the link markers, `## Verify` and
   `## Touches` in the ticket template, the `CR-03.1` key rule, the `question` and `answer`
   comment kinds, containers in `sweep`, and `tickets-apply.py` with `plan.json` and the cycle
   check. `to-tickets` switches to writing `plan.json` and calling the publisher.
2. **switchboard:** the `Tracker` adapter (snapshot query, ready predicate, `--explain`), the
   SQLite tables (`questions`, `claims`, `gates`, `decisions`, `snapshots`, `outbox`),
   `sb split` (caps, plan validation, `Touches` disjointness) and `sb ask` / `sb-inbox` label
   flips.
3. **switchboard:** the extra gate types, the size clamp, `sb graph`, `sb standup`,
   `sb remember`, epic compaction.

Tests use a fake `gh` (recorded GraphQL and REST responses) plus a frozen clock, so the tests
spend no tokens and make no API calls.

## 5. Constraints for the builder

- Deterministic first. The only LLM use in this whole brief is epic compaction (Haiku 5.5 low,
  once per epic).
- Everything in epf3 must work in a plain terminal session in an app repo with no switchboard
  installed. Anything that needs `sb` or `SB_RUN_ID` belongs in switchboard or behind the
  `--harness` install (see [skills-extensions.md](skills-extensions.md) §0).
- Keep epf3's existing rules unless this brief changes them: no reopening, no rewording what was
  agreed, the marker on every write, no ticket means no commit.
