# Glossary

Canonical terms for switchboard. Use them exactly, in docs, code, tickets and messages.

**Owner**: the one person who runs switchboard and answers its questions. The Telegram allowlist
holds the owner alone.

**Ticket**: a GitHub issue in a registered repo, created by the epf3 skills. Identified by repo and
issue number. Tickets are technical and managed on their own terms; questions and answers never
appear on them.

**Run**: one headless `claude -p` session started by switchboard, identified by `SB_RUN_ID`. Usually
works one ticket (`SB_TICKET`); some runs have none.

**Question**: one decision put to the owner through `sb ask` from inside a run. It has options, a
recommendation and a reason. It belongs to the run that asked it and, when the run has one, to
that run's ticket. It lives in `switchboard.db` and Telegram only. Interactive sessions never ask
questions this way: the owner is at the terminal.

**qid**: the short id `sb ask` prints for a question. Button callbacks, the message footer and the
`Gate:` line all carry it.

**Blocking question**: a question the ticket cannot move past until it is answered. A question
sent with `--nonblocking` is not one.

**Round**: questions sent together under one `--round` slug, shown under one header message.

**Answer**: the owner's response to one question: an option letter, or their own words verbatim.
An answer settles its question and nothing else. It reaches the next run of the ticket in the
prompt's `OWNER ANSWERS` block.

**Category**: the class of every outbound Telegram message: `BEHAVIOUR`, `ARCH`, `GATE`, `UTIL`,
`SCHEDULED`, `HARNESS`, `DIGEST`. Only switchboard assigns it. It picks the header emoji, the
topic and the notification style.

**Question kind**: what an agent passes to `sb ask --kind`: `behaviour`, `architecture` or `gate`.
Each maps to exactly one category (`behaviour` → `BEHAVIOUR`, `architecture` → `ARCH`, `gate` →
`GATE`). Agents cannot send the other categories. Not to be confused with the `kind=` field of
epf3 comment markers, which is unrelated.

**Lane**: the epf3 entry point a piece of work starts through (`/brainstorm`, `minidiff`,
`/diagnose`, ...), as in the lane table every epf3 session prints. An idea is routed to a repo and
a lane.

**Topic**: a forum topic in the owner's Telegram supergroup. One per registered repo, plus the
fixed topics (General, Harness, and later Digest and Usage).

**Idea**: a new message from the owner that is not an answer or a command. It lives in
`switchboard.db` until a `/brainstorm` settles it. It is never a GitHub issue on its own.
