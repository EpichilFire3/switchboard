"""Stored times come from the injected clock. A run's first seen is the instant of its first `sb`
command and a decision's time is the instant of its own command, both stored as UTC wall time.

The clock is injected through `switchboard.cli.main(argv, clock=...)`, called in a subprocess so
that HOME, the environment and the current directory stay per test.
"""

import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.sb_harness import COMMAND_TIMEOUT_SECONDS, Home, SbTestCase

CLOCK_ENTRY = (
    "import sys; from datetime import datetime; from switchboard.cli import main;"
    " instant = datetime.fromisoformat(sys.argv[1]);"
    " sys.exit(main(sys.argv[2:], clock=lambda: instant))"
)

KOLKATA = timezone(timedelta(hours=5, minutes=30))
# A leap day, late enough that the same instant in Kolkata is already the first of March.
FIRST = datetime(2032, 2, 29, 23, 47, 52, tzinfo=timezone.utc)
FIRST_IN_KOLKATA = datetime(2032, 3, 1, 5, 17, 52, tzinfo=KOLKATA)
FIRST_AS_UTC_WALL_TIME = datetime(2032, 2, 29, 23, 47, 52)
LATER = datetime(2032, 3, 1, 8, 5, 0, tzinfo=timezone.utc)

RUN_ONLY = {"SB_RUN_ID": "r1"}
RUN_ON_TICKET_5 = {"SB_RUN_ID": "r1", "SB_TICKET": "5"}

# (case, sb args, cwd relative to HOME): each is the first command of run r1.
FIRST_COMMANDS = (
    ("decide", ("decide", "x"), "side-projects/alpha"),
    ("status", ("status", "progress"), "side-projects/alpha"),
    ("repos scan", ("repos", "scan"), ""),
)


def sb_at(
    home: Home, instant: datetime, *args: str, cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run `sb <args>` once with a clock that always reads `instant`."""
    return subprocess.run(
        [sys.executable, "-P", "-c", CLOCK_ENTRY, instant.isoformat(), *args],
        cwd=cwd,
        env=home.env(env),
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )


def sb_at_ok(home: Home, instant: datetime, *args: str, cwd: Path, env: dict[str, str]) -> None:
    """An arrange step: `sb_at`, failing the test setup unless it exits 0."""
    result = sb_at(home, instant, *args, cwd=cwd, env=env)
    if result.returncode != 0:
        raise AssertionError(
            f"arrange step `sb {' '.join(args)}` exited {result.returncode}: {result.stderr}"
        )


def stored_instant(text: str) -> datetime:
    """A stored UTC wall time as an aware instant, whether or not the text carries its offset."""
    parsed = datetime.fromisoformat(text)
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)


def stored_wall_time(text: str) -> datetime:
    """The wall-clock fields of a stored time, offset dropped."""
    return datetime.fromisoformat(text).replace(tzinfo=None)


class FirstCommandTest(SbTestCase):
    def test_first_command_of_a_run_records_the_injected_instant_as_first_seen(self) -> None:
        for case, args, cwd in FIRST_COMMANDS:
            with self.subTest(case):
                home = self.registered_home("alpha")

                result = sb_at(home, FIRST, *args, cwd=home.root / cwd, env=RUN_ONLY)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    [(run_id, stored_instant(seen)) for run_id, seen in
                     home.rows("SELECT run_id, first_seen FROM runs")],
                    [("r1", FIRST)],
                )


class FirstSeenTest(SbTestCase):
    def setUp(self) -> None:
        self.home = self.registered_home("alpha")
        self.repo = self.home.side_projects / "alpha"

    def test_later_command_in_a_run_keeps_the_first_commands_first_seen(self) -> None:
        sb_at_ok(self.home, FIRST, "decide", "x", cwd=self.repo, env=RUN_ON_TICKET_5)

        result = sb_at(self.home, LATER, "status", "progress", cwd=self.repo, env=RUN_ON_TICKET_5)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [stored_instant(seen) for (seen,) in self.home.rows("SELECT first_seen FROM runs")],
            [FIRST],
        )

    def test_first_seen_is_stored_as_utc_wall_time(self) -> None:
        result = sb_at(self.home, FIRST_IN_KOLKATA, "decide", "x", cwd=self.repo, env=RUN_ON_TICKET_5)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [stored_wall_time(seen) for (seen,) in self.home.rows("SELECT first_seen FROM runs")],
            [FIRST_AS_UTC_WALL_TIME],
        )


class DecisionTimeTest(SbTestCase):
    def setUp(self) -> None:
        self.home = self.registered_home("alpha")
        self.repo = self.home.side_projects / "alpha"

    def test_decision_records_the_injected_instant(self) -> None:
        result = sb_at(self.home, FIRST, "decide", "x", cwd=self.repo, env=RUN_ON_TICKET_5)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [stored_instant(at) for (at,) in self.home.rows("SELECT at FROM decisions")], [FIRST]
        )

    def test_each_decision_records_its_own_commands_instant(self) -> None:
        sb_at_ok(self.home, FIRST, "decide", "x", cwd=self.repo, env=RUN_ON_TICKET_5)

        result = sb_at(self.home, LATER, "decide", "y", cwd=self.repo, env=RUN_ON_TICKET_5)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [(text, stored_instant(at)) for text, at in
             self.home.rows("SELECT text, at FROM decisions ORDER BY text")],
            [("x", FIRST), ("y", LATER)],
        )

    def test_decision_time_is_stored_as_utc_wall_time(self) -> None:
        result = sb_at(self.home, FIRST_IN_KOLKATA, "decide", "x", cwd=self.repo, env=RUN_ON_TICKET_5)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [stored_wall_time(at) for (at,) in self.home.rows("SELECT at FROM decisions")],
            [FIRST_AS_UTC_WALL_TIME],
        )


if __name__ == "__main__":
    unittest.main()
