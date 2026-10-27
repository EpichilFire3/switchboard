# Tracker report: Beads vs. Task Master vs. CCPM vs. GitHub Issues (improved)

Date: 2026-10-24. Written for the owner. This builds on [evaluations.md](evaluations.md) §1 and
re-checks the claims the decision depends on, against source and live APIs.

Evidence key: **[src]** read in the cloned source, **[live]** run against the GitHub API from this
laptop, **[docs]** the project's own docs or GitHub's docs, **[est]** my estimate,
**[unverified]** not checked.

**Annotation, 2026-10-27.** Phase 0 keeps questions, answers and ideas off GitHub. The
`awaiting-owner` label and the `question` and `answer` comment kinds this report recommends were
dropped; waiting on the owner is database-only. Each affected row below carries a note. The
report is otherwise unchanged ([tracker.md](tracker.md) Q3).

Source clones (read-only, gitignored): `tmp/eval-trackers/{beads,claude-task-master,ccpm}` in
this repo, re-cloned 2026-10-25 at the commits below.
In this doc they are written `BD/`, `TM/` and `CC/`. Beads is at `main` `b5881d73e`
(2026-10-24); the latest release is v1.3.2 (2026-10-23). Task Master is at 0.43.1 (`c0c98d36`,
2026-04-23). CCPM is at `3294c85`.

---

## 1. Bottom line

**Use GitHub Issues as the source of truth, with a thin Python layer and SQLite for harness
state.** This is the current plan, with the concrete improvements in §6. Do not adopt Beads, Task
Master or CCPM now.

Why, in one paragraph: most of the custom code switchboard needs is harness policy that no tracker
provides. That covers the fan-out validator, the question-to-Telegram map, the decision log, stuck
detection and the scheduler inputs. Every option needs it. The tracker-specific part is small
whichever tool you pick: about 425 lines on GitHub against about 345 on Beads (§2, §4). Beads
saves about 80 lines of Python. To get that saving you would rewrite most of `manage-tickets` and
`github.md`, rebuild "a ticket closes when its `Closes:` commit reaches the default branch", run a
second database per repo, and accept a GitHub mirror whose relationship sync is still unreleased.
The trade is not worth it for one developer with one orchestrator.

| Use | When |
| --- | --- |
| **GitHub + SQLite (recommended)** | One orchestrator (`sb-tick` behind a lock), tens to low hundreds of open tickets per repo, GitHub already the audit trail, and the phone as a reader. All of these hold today. |
| **Beads**, as the working store, optionally mirrored to GitHub | Any one of these becomes true: (a) you run **parallel workers in one repo** and need atomic claims; (b) agents create **many short-lived subtasks** (more than ~20 a day) that you don't want on GitHub; (c) you **leave GitHub**; (d) Phase 1 logs show `gh` latency or limits hurting ticks. The `Tracker` adapter (§6.1) keeps this switch to roughly 1 to 2 days of adapter and skill work. |
| **Hybrid: GitHub for epics and tickets, Beads only for agent subtasks** | Only under (b). It splits the truth about whether a parent ticket is ready across two systems, so the reconciliation code costs back most of what Beads saves. |
| **Task Master** | Not for this harness. It suits a person working interactively who has no spec-to-tickets pipeline and wants an LLM to parse a PRD into tasks. epf3's `to-tickets` already does that job better. Development has also been dormant since April 2026 (§4.3). |
| **CCPM** | Never as a tool. Borrow three ideas (§4.4). |

---

## 2. Capability matrix against our needs

"Built-in" means it works with zero switchboard code. "Config" means a label, setting or flag
choice. "Build" means switchboard code, given in rough lines of Python plus tests, which is
**[est]** throughout. Code that is harness-generic and the same in every option is in the last
block, so it doesn't distort the comparison.

### 2.1 Tracker-specific capabilities

| Need | GitHub + SQLite | Beads (`bd`) | Task Master | CCPM |
| --- | --- | --- | --- | --- |
| Tree: epic → ticket → subtask | **Built-in.** Sub-issues, 100 per parent, 8 levels **[docs]** | **Built-in.** `parent-child` deps, hierarchical IDs `bd-x.1.2` **[src]** | **No.** 2 levels: `Subtask` has `subtasks?: never` (`TM/packages/tm-core/src/common/types/index.ts`). A 3rd level needs one tag per epic | PRD → epic → task, as files; sub-issue linking never runs (`CC/references/sync.md:48-68`) |
| Ready set (no open blocker) | **Build ~30 + 80 adapter.** One GraphQL query per repo returns `issueDependenciesSummary.blockedBy` (open blockers), `parent`, `subIssuesSummary` and labels. Cost **3 points, 1.85 s** for 100 issues with bodies **[live]**. Or use the `-is:blocked` search qualifier, which means "has an open blocker" **[live]** | **Built-in.** `bd ready --json` with `--parent`, `--label`, `--exclude-label`, `--type`, `--exclude-type`, `--metadata-field k=v`, `--priority`, `-n`, `--sort`, `--explain` (`BD/docs/cli-reference/ready.md`). Gate types are excluded by default; **epics are not**, so pass `--exclude-type epic` (`BD/internal/storage/sqlbuild/ready.go:16`) | **Built-in.** `next` and `list --ready`. Only the literal status `done` satisfies a dependency (`TM/packages/tm-core/src/modules/tasks/services/task-service.ts:299-418`) | **Broken.** `next.sh` lists a task only when `depends_on` is empty (#1027) |
| Ready set minus "waiting on owner" | **Build ~15.** A SQLite `questions` join, which the scheduler needs anyway for its score | **Built-in** via a human gate (next row) | **Config.** Status `blocked` or `deferred` is skipped by `next` | n/a |
| Human-gate blocking and unblocking on an answer | **Build ~40.** `sb ask` writes the question row, adds label `awaiting-owner` and posts a `kind=question` comment. `sb-inbox` posts `kind=answer` and removes the label once the last blocking question is answered *[Annotation 2026-10-27: the `awaiting-owner` label was dropped, with the `question` and `answer` comment kinds; waiting on the owner is database-only.]* | **Built-in + glue ~25.** `bd gate create --type human --blocks <id> --reason …`, then `bd gate resolve <gate>`. The blocked bead leaves `bd ready` until then (`BD/docs/workflows/gates.md`). A qid↔gate map is still needed for Telegram | **Build ~20.** `set-status blocked`/`pending`; there is no gate object | n/a |
| Claiming | **Config ~15.** Label `in-progress` plus a claim comment (epf3 rule). This is safe because `sb-tick` is the only claimer, behind `tick.lock` | **Built-in.** `bd update --claim` / `bd ready --claim` is atomic, with lease and heartbeat columns (`BD/internal/types/types.go`, "Leasing") | **None.** `in-progress` tasks are returned again | `status: in-progress` frontmatter |
| Size / budget metadata | **Config ~10.** Labels `size:S` and `size:M`, written at creation and clamped into SQLite. Personal accounts have no issue fields: those are GA for **orgs only** (2026-07-02) **[docs]** | **Built-in.** `--estimate <min>` (`estimated_minutes`) and `--set-metadata size=S`, filterable in `ready` (`BD/docs/core-concepts/metadata.md`) | `metadata` exists (0.43.0), but is writable only through MCP with `TASK_MASTER_ALLOW_METADATA_UPDATES=true` | n/a |
| Notes / handoff | **Harness files** (context packs). epf3 forbids progress comments, and that is right | `--append-notes`, `--design`, `--acceptance`, comments. The packs would still be files (4k-token cap, validation) | **LLM call per note.** `update-subtask` rewrites your note through the model (`TM/scripts/modules/task-manager/update-subtask-by-id.js:315-360`) | `updates/<N>/*.md` files |
| Fan-out limits (§5) | **Build ~130.** GitHub's 100 per parent and 8 levels are too loose | **Build ~90.** `hierarchy.max-depth=3` exists as config but **is not enforced**: `CheckHierarchyDepth` has no non-test caller (`BD/internal/types/id_generator.go:110`). There is no children cap. `bd create --graph plan.json` creates nodes and edges atomically, which saves the creation code | **Not usable.** `expand --num` is prompt text and is never checked (`TM/scripts/modules/task-manager/expand-task.js:186-207, 337-342`) | Prose ("aim for ≤10 tasks") |
| Decision log | **Build ~40.** SQLite `decisions`, a markdown mirror and a `kind=answer` comment *[Annotation 2026-10-27: the `question` and `answer` comment kinds were dropped; answers are database-only.]* | **Build ~25.** An issue type `decision` exists (`-t decision`, alias `adr`) | Build | n/a |
| Discovered work, not ready until accepted | **Config.** epf3's `discovered` label, filtered out of the ready set | **Built-in.** A `discovered-from` dep, plus `--exclude-label discovered` | Build | n/a |
| Phone-readable view | **Built-in.** GitHub Mobile shows sub-issues **[docs]**. Whether it shows blocked-by is **[unverified]** | **Config + caveats.** `bd github sync --push-only` pushes title, `description` as the body, state and scoped labels (`BD/internal/github/mapping.go:155-190`). Notes, acceptance, design and comments are not pushed. Relationship sync (epic/child → sub-issues, blocks → blocked_by) is **on `main` only, not in v1.3.2**, and it only adds links, never removes them (`BD/cmd/bd/github.go` `pushGitHubDependencyLinks`, commit `bcf4da3c6`) | **None** (a local JSON file) | Issues, without dependency links |
| Commit linkage: `Closes: #N` closes the ticket | **Built-in** (GitHub closes the issue) | **Lost.** Build a trailer → `bd close` sweep, ~80 lines, and rework the `ship`/`manage-tickets` conventions. Bead IDs (`sb-a3f8`) replace `#412` in branch names | None | Partial |
| Cross-repo links | **Built-in.** Same owner, for sub-issues **[docs]**; blocked-by works across repos **[live]** | **Config.** `external:<project>:<capability>` deps plus `external_projects` (`BD/docs/core-concepts/dependencies.md`) | No (tags only) | No |
| Spec → tickets | **Existing** (`to-tickets`, unchanged) | **Rewrite** the publish step to `bd create --graph` | `parse-prd` (an LLM call; duplicates `to-tickets`) | `/pm` flow |
| Works when offline | No. The tick exits at its gate; `sb-inbox` queues writes in an outbox (§6.5) | Yes. That rarely matters: Claude Code needs the network anyway | Yes | Yes |

### 2.2 Harness-generic code (the same in every option, so not a differentiator)

| Piece | Lines | Notes |
| --- | --- | --- |
| Scheduler score + vruntime | ~150 | Needs SQLite clocks; no tracker has this |
| Context packs + validation + salvage | ~250 | Files; no tracker's notes satisfy the cap and validation |
| Stuck detection | ~40 | "3 runs without progress" uses git and handoff data |
| Questions ↔ Telegram map, rounds | ~120 | `tg_map`, `questions`; a Beads gate would still need this map |
| Budgets/hooks | ~200 | Unrelated to the tracker |

### 2.3 Totals (tracker-specific only)

| Option | switchboard Python | epf3 skill changes | New ops surface |
| --- | --- | --- | --- |
| **GitHub + SQLite** | **~425 lines**, about 2 days with tests | **< 1 hour.** Add 3 labels (`awaiting-owner`, `size:S`, `size:M`), 2 comment kinds, the split key format, and container-ticket closing in `sweep` *[Annotation 2026-10-27: the `awaiting-owner` label was dropped, with the `question` and `answer` comment kinds; waiting on the owner is database-only.]* | None (`gh` ≥ 2.94 is already installed) |
| **Beads + GH mirror** | **~345 lines**, about 1.5 days | **1.5 to 2.5 days.** Replace all 242 lines of `github.md`; rewrite every operation in `manage-tickets` (171 lines) and the publish half of `to-tickets`; touch 9 other skills that reference `gh issue` | Install and pin `bd` (CGO build); `bd init --stealth --skip-hooks --skip-agents` in each repo; backups (`bd backup` / Dolt remote); test every upgrade |
| **Task Master** | ~400+ lines, and it still can't do depth 3 or write notes without an LLM or direct JSON edits | Full rewrite | Node toolchain; turn off Sentry (§4.3) |
| **CCPM** | Build almost everything; its scripts are broken | Full rewrite | n/a |

---

## 3. Operational model and concurrency

Who writes tracker state: `sb-tick` (claims, splits, status), `sb-inbox` (answers, label flips),
the agent inside a run (epf3 `manage-tickets` operations: file discovered, done), and hooks (none
write to the tracker in the plan).

| | GitHub + SQLite | Beads embedded (default) | Beads server mode | Task Master | CCPM |
| --- | --- | --- | --- | --- | --- |
| Storage | GitHub (remote). SQLite WAL for harness state | `.beads/embeddeddolt/` per repo; linked worktrees share one `.beads` (`BD/docs/reference/worktrees.md`) | `dolt sql-server` (a systemd user unit you run) | `.taskmaster/tasks/tasks.json` | `.claude/` markdown |
| Concurrent writers | Handled by the server. Labels and comments commute; body edits are last-writer-wins. No transactions | **Serialized.** Each process opens the engine; the driver backoff waits until context cancel (`BD/internal/storage/embeddeddolt/open.go:40-43`); a `bd` command's open timeout is **30 s** (`BD/cmd/bd/main.go:123`). A 10-process concurrent test exists (`concurrency_test.go:23`). Anything that holds a store open blocks everyone (#3415 `bd list --watch`) | True multi-writer; auto-commit off by default | `proper-lockfile`, but the legacy `writeJSON` replaces the whole tag with the caller's stale read, so **lost updates** happen (`TM/scripts/modules/utils.js`; issues #1420, #1708) | None |
| Atomic multi-step writes | **No.** create, parent and blocked-by are separate calls. Mitigation: marker-keyed, idempotent re-runs (the epf3 pattern already) | Yes: `bd batch`, `bd create --graph` (one Dolt transaction) | Yes | No | No |
| Per-call latency | gh startup ~0.15 s + round trip ~0.4 s; ~1.9 s for the full 100-issue snapshot **[live]** | ~14 ms engine open per store call at 200 issues, ~47 ms at 2k (#5397 measurements), plus process start **[unverified on this laptop]** | lower | ~process start | ~0 |
| Limits | 5,000 GraphQL points/h (a snapshot is 3); 80 content writes/min, 500/h; search 30/min; 50 blockers per issue **[docs, live]** | Local | Local | Local | Local |
| Sync / backup | GitHub is the backup | `bd dolt push` to a remote (`refs/dolt/data`); `bd github sync` mirror | Same | git, if you commit the JSON | Push to GitHub |
| WSL specifics | none | Keep `.beads` on ext4, never `/mnt/c` (9P locks, #3613) | Windows/WSL2 loopback identity issue (#4637); one more daemon to keep alive | none | none |
| Failure mode | GitHub outage (e.g. 2026-08-17, ~7 h): ticks skip, answers queue in the outbox | An upgrade migration fails, or the lock stays held | The server is down | A corrupted or lost tag | Broken readiness |

**What this means for the daemon and runner.** With GitHub, none of the three writers needs to
coordinate beyond `tick.lock` and SQLite's `busy_timeout`. With Beads embedded, every writer must
shell out per operation and never keep a store open, and a 30 s stall becomes a possible tick
delay. Server mode fixes this, at the cost of one more always-on service on WSL. Neither is hard,
but each is a new thing to operate.

---

## 4. Overhead and long-term cost

### 4.1 GitHub + SQLite

- **Churn:** low. The sub-issue and dependency APIs are GA (dependencies since 2025-08-21). gh
  gained `--parent`, `--add-sub-issue` and `--add-blocked-by` in 2.94 (2026-06-10) **[docs]**.
  There are no data migrations to run.
- **Token overhead for the agent:** none from the tracker in harness mode, if agents receive the
  ticket in the context pack and write through `sb` (§6.3). epf3 skills that call `gh` print
  small JSON.
- **Limits you might hit:** none at this scale. A tick snapshots N repos at 3 points each; six
  repos × 48 ticks a day is ~860 points a day, against a 5,000-points-per-hour budget.
- **Migration from today:** additive edits only (§2.3).

### 4.2 Beads

- **Activity:** very high. 586 commits in the last 30 days; v1.3.0 (2026-09-15) to v1.3.2
  (2026-10-23); 28.2k stars; 1,519 open issues and PRs **[live]**.
- **History of breaking change:** SQLite → Dolt (v0.50); JSONL demoted to export only (v0.55);
  `migrate --to-dolt` removed (v0.58); the JSON envelope becomes the default in v2.0
  (`BD/docs/reference/json-schema.md`).
- **Roadmap for 1.4** (`BD/ROADMAP.md`, updated 2026-10-05): versioned beads with CAS, "Beads
  Graph Preview 2" (a generic Bead-and-Link graph model), and contributor onboarding. Graph mode
  is the item most likely to change the CLI under you.
- **Relation to Gas Town:** Beads lives in the same org (`gastownhall`), its docs are at
  `beads.gascity.com`, and CI re-pins against "gascity". Gas Town is Steve Yegge's multi-agent
  orchestrator (Jan 2026). Gas City is reported as its successor SDK (Apr 2026, one secondary
  source **[unverified]**).
- **Orchestrator concepts sit in core** even though the charter says they should not
  (`BD/engdocs/PROJECT_CHARTER.md`, "Orchestration Boundary"):
  - the ready query excludes `rig`, `molecule`, `gate` and `merge-request` types;
  - there are `mol`, `wisp`, `swarm`, `mail`, `merge-slot` and `federation` commands;
  - the docs start servers with `gt dolt start`.
- **Assessment:** the primitives switchboard would use (ready, dep, gate, metadata, claim) are
  the stable centre. The risk is surface size and upgrade churn, not being steered away from solo
  use.
- **Ongoing cost if adopted:** pin a version, test each upgrade on a copy of `.beads`, run
  `bd metrics off`, back up per repo. Allow about 1 hour a month.
- **Migration cost:** 1.5 to 2.5 days of skill rewriting (§2.3). Also a one-off
  `bd github sync --pull-only` import per repo, and new branch and key conventions.

### 4.3 Task Master: dormancy is a real long-term risk

- **Activity:**
  - Commits per month: 81 to 98 (Jul to Dec 2025), 41 (Jan 2026), then 1, 2 and 2 (Feb to Apr).
  - Last push 2026-04-28; 0 merged PRs since 2026-05-01.
  - npm `latest` is 0.43.1 (2026-03-31). `1.0.0-rc.1` (2026-02-18) never shipped.
- **Company:** docs moved to `tryhamster.com`, and the code has Hamster `storage: 'api'`,
  `login` and `briefs` paths. The company's effort has visibly moved to the hosted product.
- **License and telemetry:** MIT with Commons Clause (`TM/LICENSE`). Sentry is on by default with
  `recordInputs/recordOutputs: true` and `sendDefaultPii: true` (`TM/src/telemetry/sentry.js`).
- **The `claude-code` provider works on a subscription with no API key** (it wraps the Agent SDK,
  `TM/src/ai-providers/claude-code.js`). Each `expand` or `analyze-complexity` call then becomes a
  full Claude Code session: it loads your project settings, and therefore your hooks, and does
  codebase analysis first. That is tens of thousands of tokens per call **[est]**.

### 4.4 CCPM

- **State:** dormant. A one-day v2 relaunch on 2026-03-18, then only a `funding.json` commit.
  Local files are the source of truth; sync is a one-way push with no `blockedBy`; sync writes
  empty bodies and calls a nonexistent `gh issue create --json` (#1024).
- **Worth borrowing:**
  1. `conflicts_with`: don't run two sibling tickets that touch the same area on parallel
     branches. This matters only if ticks ever run in parallel.
  2. A per-issue stream analysis with file scopes, as an optional pre-run artifact.
  3. "One summary comment, not one per tick", which epf3 already enforces.

---

## 5. Fan-out control specifically

The owner's concern is that every rule is code to build and maintain. Facts first: **no option
gives you a usable fan-out controller.**

| Option | What exists | Usable as the controller? |
| --- | --- | --- |
| GitHub | Hard limits of 100 sub-issues per parent, 8 levels, 50 blockers per type **[docs]** | No. Far looser than ours |
| Beads | `hierarchy.max-depth` config (default 3) and `MaxHierarchyDepth` | No. **Not enforced**: there is no non-test caller of `CheckHierarchyDepth`, and child-ID minting (`BD/internal/storage/issueops/child_id.go`) does no depth check. Reparenting (`update --parent`) keeps the ID, so counting dots would not work anyway. Formulas and molecules give fixed-shape templates, not dynamic caps |
| Task Master | `expand --num N`, `defaultSubtasks` 5, complexity `recommendedSubtasks`, `--threshold` | No. The number is prompt text; the result is never counted; `--num 0` means unbounded; it needs an LLM call each time |
| CCPM | "aim for ≤10 tasks" in prose | No |

So the controller is ours in every option. Keep it to **one choke point and four rules**:

| Rule | Keep? | Enforced by | Lines |
| --- | --- | --- | --- |
| Depth ≤ 3 (epic → ticket → subtask), counted along the `parent` chain in the snapshot | Keep | `sb split` | ~10 |
| ≤ 5 children per split, ≤ 1 split per run | Keep | `sb split` (count in SQLite `runs`) | ~10 |
| Open tickets per repo ≤ 15 | Keep, but **refuse** the split rather than queue the children: park `needs-split` plus a `HARNESS` message. Queuing needs another state | `sb split` | ~10 |
| Each child is size S or M, with non-empty acceptance criteria | Keep (pydantic schema). "False today" stays a prompt rule: it can't be checked deterministically | `sb split` | ~30 |
| Epics in progress ≤ 2 | **Drop as a hard rule.** New epics are already an owner `GATE` (`harness-mode` "Never on its own"), and the scheduler's `V_NEWROOT` penalty does the rest | — | 0 |
| Discovered work | No cap needed. The `discovered` label keeps it out of the ready set until you accept it in the digest, so you are the limiter | label filter | ~3 |

Creating the children is ~60 lines: `gh issue create --parent`, then blocked-by links, then a
read-back, keyed by marker. That gives **~130 lines plus tests, about half a day.** The only path
that bypasses it is an agent running `gh issue create --parent` directly. epf3 confines that to
`file` (discovered work), which is already not ready until accepted, so no guard hook is needed.

**Resolve first:**
- `to-tickets` says "Two levels: the epic and its tickets. Never nest deeper." (`to-tickets/SKILL.md`,
  Slicing). `scheduler.md` §5 says depth 3. Proposal: `to-tickets` stays at 2 levels, and only
  `sb split` creates level 3.
- A ticket with open sub-issues is then a container: it is not ready itself, and `sweep` closes
  it when its children close, the same way finished epics are closed.

---

## 6. Recommended design (GitHub + SQLite), concrete enough to build

### 6.1 Boundary

`src/switchboard/tracker/base.py` defines `Tracker` with `snapshot(repo)`, `claim(n)`,
`set_waiting(n, on)`, `comment(n, kind, body)`, `create_children(parent, plan)` and
`read_back(n)`. `github.py` implements it with `gh api graphql` and `gh issue …`. Nothing else in
switchboard calls `gh` for issues. This is the escape hatch to Beads: a `beads.py` with the same
interface.

### 6.2 Where each piece of state lives

| Data | Lives in | Written by |
| --- | --- | --- |
| Epic/ticket/subtask tree | GitHub sub-issues | `to-tickets`, `sb split` |
| Blocking between tickets | GitHub `blockedBy` | `to-tickets`, `sb split`, `manage-tickets blocked` |
| Size | Label `size:S` / `size:M` (visible on the phone) and `tickets.size` in SQLite (clamped) | `to-tickets` (new: one label per ticket), `sb split` |
| Priority | SQLite `tickets.priority` (epf3 forbids agents setting priority labels) | owner `/prio` |
| Claimed / done | Labels `in-progress` / `done` + comments (epf3, unchanged) | `sb-tick` (claim), `ship` (done) |
| Waiting on owner | SQLite `questions` (authority) + label `awaiting-owner` (visibility) + a `kind=question` comment per round *[Annotation 2026-10-27: the `awaiting-owner` label was dropped, with the `question` and `answer` comment kinds; waiting on the owner is database-only.]* | `sb ask` |
| Owner answer | SQLite `questions.answer`, a `kind=answer` comment, `decisions` + `decisions.md` *[Annotation 2026-10-27: the `question` and `answer` comment kinds were dropped; answers are database-only.]* | `sb-inbox` |
| Sessions, cache clocks, runs, budgets, packs | SQLite + `~/.switchboard/packs/` | `sb-tick` (digest after each run; the Haiku handoff only before a cold start) |
| Last snapshot per repo | SQLite `snapshots(repo, fetched_at, json)` | `sb-tick`; read by `/status` with no API call |

Alternative considered: **each owner question as its own GitHub issue that blocks the ticket.**
This would make the ready set pure GitHub (`-is:blocked`) and let you answer on GitHub too. It
costs three writes per round, fills the repo with question issues, and duplicates the SQLite
`questions` table that Telegram routing needs anyway. Rejected; revisit only if you want GitHub to
be the only place blocking is visible.

### 6.3 Commands the harness calls

The snapshot is one query per repo (verified: cost 3, ~1.9 s with bodies, 100 per page) **[live]**:

```graphql
query($owner:String!, $name:String!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    issues(states:OPEN, first:100, after:$cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title body
        labels(first:20) { nodes { name } }
        parent { number state }
        subIssuesSummary { total completed }
        issueDependenciesSummary { blockedBy totalBlockedBy }
      }
    }
  }
}
```

`issueDependenciesSummary.blockedBy` is the count of open blockers: an issue whose blockers are all
closed shows up under `-is:blocked` **[live]**. Confirm the count semantics on one epf3 issue
before relying on it (§7). `subIssuesSummary.completed/total` of the parent gives the scheduler's
`siblings_done_fraction` for free.

**Ready predicate** (Python, ~30 lines). A ticket is ready when all of these hold:
- the body carries an `epf3:ticket` marker;
- it has no `Epic` label;
- `blockedBy == 0`;
- it has no open sub-issues (`total - completed == 0`), so it is not a container;
- it has neither `done` nor `discovered` (unless accepted in SQLite) nor `awaiting-owner`; *[Annotation 2026-10-27: the `awaiting-owner` label was dropped, with the `question` and `answer` comment kinds; waiting on the owner is database-only.]*
- if it is `in-progress`, SQLite must show `sb-tick` as the claimer. This excludes tickets you
  claimed from VSCode.

SQLite must also show no pending blocking question, and the ticket must be neither `parked` nor
over the stuck threshold.

| Event | Calls (in order, one at a time, read back per epf3) |
| --- | --- |
| First dispatch | `gh issue edit N --add-label in-progress`; `gh issue comment N --body-file` (`kind=claim`) |
| `sb ask` (blocking) | INSERT `questions`; `gh issue edit N --add-label awaiting-owner`; one `kind=question` comment per round with the Telegram link *[Annotation 2026-10-27: the `awaiting-owner` label was dropped, with the `question` and `answer` comment kinds; waiting on the owner is database-only.]* |
| Answer arrives | UPDATE `questions`; `kind=answer` comment; once no blocking question remains, `gh issue edit N --remove-label awaiting-owner`; INSERT `decisions` *[Annotation 2026-10-27: the `awaiting-owner` label was dropped, with the `question` and `answer` comment kinds; waiting on the owner is database-only.]* |
| `sb split` | Validate (§5); for each child, `gh issue create --parent N --label size:X,<area> --body-file` with marker `<!-- epf3:ticket spec=<slug> key=<KEY>.<i> -->`; `gh issue edit <child> --add-blocked-by <m>` for each link; read-back; the parent becomes a container |
| Done / close | Unchanged: `ship` labels `done`; the `Closes:` trailer closes; `sweep` also closes containers whose children are all closed |

New split keys (`CR-03.1`) need a one-line change to the title rule in `github.md` (today it is
`KEY-NN`). That is your call.

### 6.4 What the agent sees

The agent sees the ticket text in the context pack, never a tracker query. It writes through
`sb status|split|ask|decide`, plus the epf3 operations it already runs (`file`
discovered, `done` via `ship`). This keeps tracker tokens near zero, and it keeps runs
independent of the backend, so a future switch only touches `tracker/*.py` and epf3's
`github.md`.

### 6.5 Concurrency and failure

- **Writers:** only `sb-tick` (under `tick.lock`) and `sb-inbox` write issues. `sb-inbox` only
  adds labels and comments, never edits bodies, so its writes commute with the run's writes.
- **SQLite:** WAL mode with `busy_timeout=5000`.
- **Outbox (~30 lines):** `sb-inbox` puts tracker writes in an `outbox` table and replays them, so
  an answer tapped while GitHub is down still lands. `sb-tick` exits at its gate if a snapshot
  fails (zero tokens).
- **Consistency rules (~50 lines):** the existing "tracker/DB disagreement" table, e.g. the issue
  is closed but SQLite says ready, or `awaiting-owner` is set but no question is pending. Both
  repair deterministically. *[Annotation 2026-10-27: the `awaiting-owner` label was dropped, with the `question` and `answer` comment kinds; waiting on the owner is database-only.]*

### 6.6 epf3 edits (under an hour)

- `github.md`: three labels (`awaiting-owner`, `size:S`, `size:M`) and the snapshot query beside
  the existing frontier `jq`. *[Annotation 2026-10-27: the `awaiting-owner` label was dropped, with the `question` and `answer` comment kinds; waiting on the owner is database-only.]*
- `manage-tickets`: comment kinds `question` and `answer` (already proposed in
  skills-extensions §3.4), and `sweep` step 3 extended to containers. *[Annotation 2026-10-27: the `question` and `answer` comment kinds were dropped; answers are database-only.]*
- `to-tickets`: one `size:*` label per ticket.

---

## 7. Open risks and what to verify hands-on first

| # | Check | How | If it fails |
| --- | --- | --- | --- |
| 1 | `issueDependenciesSummary.blockedBy` counts **open** blockers only | Close a blocker on a scratch epf3 issue and re-query | Add `blockedBy(first:20){nodes{state}}` to the query (still 3 points) |
| 2 | GitHub Mobile shows sub-issue progress and blocked-by **[unverified]** | Look on the phone | The `awaiting-owner` label and the epic's ticket list carry the information; the digest covers the rest *[Annotation 2026-10-27: the `awaiting-owner` label was dropped, with the `question` and `answer` comment kinds; waiting on the owner is database-only.]* |
| 3 | Partial `sb split` (create succeeded, link failed) re-runs cleanly | Kill it mid-split in a test repo | Marker lookup + read-back repair, as `to-tickets` does already |
| 4 | Two spec contradictions | Resolved 2026-10-24 | (a) Depth: `to-tickets` stays at 2 levels; only `sb split` creates level 3 (scheduler.md §5). (b) Handoff: the harness writes it after the run with Haiku 5.5 low, outside the run's budget, and only before a cold start (prompt-cache.md §3.5). The scheduler and prompt-cache docs now say so |
| 5 | Owner's own interactive claims aren't picked up by ticks | Claim a ticket from VSCode, run `sb-tick --dry-run` | The ready predicate already requires a SQLite claim row |
| 6 | gh latency per tick acceptable (~1.9 s per repo snapshot) | Phase 1 tick log | Run snapshots in parallel (≤ 100 concurrent allowed), or cache with ETag REST `since=` polling (304s are free) |
| 7 | If Beads is ever reconsidered | Throwaway repo on ext4 | Before any decision, test: (1) daemon, tick and agent `bd` writes concurrently, to measure the 30 s lock waits; (2) the `bd github sync --push-only` mapping once relationship sync is in a release; (3) per-call latency on this laptop; (4) `hierarchy.max-depth` enforcement (expect none) |

Not verified here: Beads per-call latency on this laptop, Beads telemetry defaults (`bd metrics`
exists; check `bd metrics` output), Task Master token figures (estimates from prompt sizes), and
the Gas City details.

### Sources

- GitHub sub-issues: https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/adding-sub-issues
- Dependencies GA: https://github.blog/changelog/2025-08-21-dependencies-on-issues/
- gh sub-issue and dependency flags: https://github.blog/changelog/2026-06-10-manage-sub-issues-types-and-dependencies-from-github-cli/
- Issue fields GA (orgs): https://github.blog/changelog/2026-07-02-issue-fields-are-now-generally-available/
- GraphQL limits: https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api
- REST limits: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
- Mobile sub-issues: https://github.blog/changelog/2025-03-21-create-add-and-remove-sub-issues-on-github-mobile
- Availability report Aug 2026: https://github.blog/news-insights/company-news/github-availability-report-august-2026/
- Beads issues: https://github.com/gastownhall/beads/issues/5397, /3415, /3613, /4637
- Task Master issues: https://github.com/eyaltoledano/claude-task-master/issues/1708, /1728; Hamster: https://tryhamster.com/product/taskmaster
- CCPM: https://github.com/automazeio/ccpm/issues/1027, /1016
- Gas Town / Gas City background: https://en.wikipedia.org/wiki/Steve_Yegge
