import argparse
import os
import re
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple, NoReturn

from switchboard import db

Clock = Callable[[], datetime]

STATUSES = ("progress", "blocked", "done", "needs-split")


class Parser(argparse.ArgumentParser):
    # The run contract allows one stderr line per invalid input; argparse prints the usage first.
    def error(self, message: str) -> NoReturn:
        self.exit(2, f"{self.prog}: {message}\n")


class Run(NamedTuple):
    conn: sqlite3.Connection
    id: str
    repo_id: int
    ticket_id: int | None
    now: str


def ticket_number(text: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise argparse.ArgumentTypeError(f"not a ticket number (from --ticket or SB_TICKET): {text!r}")
    return int(text)


def resolve_repo(conn: sqlite3.Connection) -> int:
    name = os.environ.get("SB_REPO")
    if name:
        row = conn.execute("SELECT id FROM repos WHERE name = ?", (name,)).fetchone()
    else:
        # Every worktree shares the common directory, so a harness slot or an epf3 worktree
        # resolves to the checkout it was made from.
        git = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        row = None
        if git.returncode == 0:
            checkout = Path(git.stdout.strip()).resolve().parent
            row = conn.execute("SELECT id FROM repos WHERE path = ?", (str(checkout),)).fetchone()
    if row is None:
        sys.exit(f"sb: {name or Path.cwd()} is not a registered repo; run sb repos scan")
    return row[0]


def utc_now() -> datetime:
    return datetime.now(UTC)


def stamp(clock: Clock) -> str:
    # Stored times are UTC whatever offset the injected clock reports.
    return clock().astimezone(UTC).isoformat(timespec="seconds")


def create_run(conn: sqlite3.Connection, run_id: str, now: str) -> None:
    conn.execute(
        "INSERT INTO runs (run_id, first_seen) VALUES (?, ?) ON CONFLICT DO NOTHING", (run_id, now)
    )


@contextmanager
def open_run(command: str, ticket: int | None, clock: Clock) -> Iterator[Run]:
    run_id = os.environ.get("SB_RUN_ID")
    if not run_id:
        sys.exit(f"sb {command}: not a harness run: SB_RUN_ID is unset")
    now = stamp(clock)
    with closing(db.connect()) as conn:
        repo_id = resolve_repo(conn)
        with db.transaction(conn):
            create_run(conn, run_id, now)
            ticket_id = None
            if ticket is not None:
                key = (repo_id, ticket)
                conn.execute(
                    "INSERT INTO tickets (repo_id, number) VALUES (?, ?) ON CONFLICT DO NOTHING", key
                )
                ticket_id = conn.execute(
                    "SELECT id FROM tickets WHERE repo_id = ? AND number = ?", key
                ).fetchone()[0]
            yield Run(conn, run_id, repo_id, ticket_id, now)


def scan_repos(args: argparse.Namespace, clock: Clock) -> None:
    root = Path.home() / "side-projects"
    if not root.is_dir():
        sys.exit(f"sb repos scan: {root} does not exist")
    added = []
    run_id = os.environ.get("SB_RUN_ID")
    with closing(db.connect()) as conn, db.transaction(conn):
        if run_id:
            create_run(conn, run_id, stamp(clock))
        for child in sorted(root.iterdir()):
            # A linked worktree has a .git file and resolves to its parent repo; it is not a repo.
            if not (child / ".git").is_dir():
                continue
            inserted = conn.execute(
                "INSERT INTO repos (name, path) VALUES (?, ?) ON CONFLICT DO NOTHING",
                (child.name, str(child.resolve())),
            )
            if inserted.rowcount:
                added.append(child.name)
    for name in added:
        print(f"registered {name}")


def record_decision(args: argparse.Namespace, clock: Clock) -> None:
    with open_run(args.command, args.ticket, clock) as run:
        run.conn.execute(
            """INSERT INTO decisions (run_id, repo_id, ticket_id, text, source, at)
                VALUES (?, ?, ?, ?, 'agent', ?)""",
            (run.id, run.repo_id, run.ticket_id, args.text, run.now),
        )


def report_status(args: argparse.Namespace, clock: Clock) -> None:
    with open_run(args.command, args.ticket, clock) as run:
        run.conn.execute(
            "UPDATE runs SET reported_status = ?, reported_reason = ? WHERE run_id = ?",
            (args.status, args.reason, run.id),
        )
        if run.ticket_id is None:
            return
        # Only blocked reaches the harness status: mapping the others is Phase 1's decision.
        run.conn.execute(
            """UPDATE tickets SET reported_status = ?, reported_reason = ?,
                reported_cause = reported_cause OR ? WHERE id = ?""",
            (args.status, args.reason, args.status == "blocked", run.ticket_id),
        )


def build_parser() -> Parser:
    parser = Parser(prog="sb")
    commands = parser.add_subparsers(dest="command", required=True)

    repos = commands.add_parser("repos", help="the repos switchboard knows")
    repos_actions = repos.add_subparsers(dest="action", required=True)
    scan = repos_actions.add_parser("scan", help="register every git checkout under ~/side-projects")
    scan.set_defaults(handler=scan_repos)

    in_run = Parser(add_help=False)
    in_run.add_argument("--ticket", type=ticket_number, default=os.environ.get("SB_TICKET") or None)

    decide = commands.add_parser("decide", parents=[in_run], help="record a decision made in a run")
    decide.add_argument("text")
    decide.set_defaults(handler=record_decision)

    status = commands.add_parser("status", parents=[in_run], help="report where a run stands")
    status.add_argument("status", choices=STATUSES)
    status.add_argument("--reason")
    status.set_defaults(handler=report_status)
    return parser


def main(argv: list[str] | None = None, clock: Clock = utc_now) -> None:
    args = build_parser().parse_args(argv)
    args.handler(args, clock)
