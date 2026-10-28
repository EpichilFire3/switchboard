import fcntl
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# MIGRATIONS[i] takes the schema from user_version i to i + 1. Forward only: the spec migrates on
# start and never back. Append new steps; never edit one that has shipped.
MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (
        """CREATE TABLE repos (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            path TEXT NOT NULL UNIQUE
        )""",
        """CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            first_seen TEXT NOT NULL,
            reported_status TEXT,
            reported_reason TEXT
        )""",
        """CREATE TABLE tickets (
            id INTEGER PRIMARY KEY,
            repo_id INTEGER NOT NULL REFERENCES repos (id),
            number INTEGER NOT NULL,
            questions_cause INTEGER NOT NULL DEFAULT 0,
            reported_cause INTEGER NOT NULL DEFAULT 0,
            harness_status TEXT GENERATED ALWAYS AS (
                CASE WHEN questions_cause OR reported_cause THEN 'blocked' ELSE 'ready' END
            ) VIRTUAL,
            reported_status TEXT,
            reported_reason TEXT,
            UNIQUE (repo_id, number)
        )""",
        """CREATE TABLE decisions (
            id INTEGER PRIMARY KEY,
            run_id TEXT REFERENCES runs (run_id),
            repo_id INTEGER NOT NULL REFERENCES repos (id),
            ticket_id INTEGER REFERENCES tickets (id),
            text TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('agent', 'owner')),
            at TEXT NOT NULL
        )""",
    ),
    (
        "ALTER TABLE repos ADD COLUMN topic_id INTEGER",
        "CREATE TABLE kv (key TEXT PRIMARY KEY, value NOT NULL)",
    ),
)


def connect() -> sqlite3.Connection:
    path = Path.home() / ".switchboard" / "switchboard.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    # Two first opens switching a new file to WAL deadlock and fail at once, busy timeout or not
    # (seen with eight concurrent `sb repos scan`), so setup runs one process at a time.
    with open(path.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        conn.execute("PRAGMA journal_mode = WAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < len(MIGRATIONS):
            with transaction(conn):
                for number, statements in enumerate(MIGRATIONS[version:], start=version + 1):
                    for statement in statements:
                        conn.execute(statement)
                    conn.execute(f"PRAGMA user_version = {number}")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    # IMMEDIATE takes the write lock up front, so a busy database waits out the timeout instead
    # of failing at the first write of a deferred transaction.
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
