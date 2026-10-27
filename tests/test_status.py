"""`sb status` inside a run records the last reported status and reason on the run and, when there
is a ticket, on the ticket; `blocked` also sets the ticket's `reported` cause."""

import unittest

from tests.sb_harness import SbTestCase

RUN_ON_TICKET_5 = {"SB_RUN_ID": "r1", "SB_TICKET": "5"}
NON_BLOCKING_STATUSES = ("progress", "done", "needs-split")
ALL_STATUSES = ("progress", "blocked", "done", "needs-split")

VERBATIM_REASONS = (
    ("sql fragment", "ci'); DROP TABLE runs; --"),
    ("accents cjk and emoji", "café 漢字 \U0001F6A7"),
    ("newline and quotes", "first line\nsecond \"line\" it's"),
)


class BlockedStatusTest(SbTestCase):
    def setUp(self) -> None:
        self.home = self.registered_home("alpha")
        self.repo = self.home.side_projects / "alpha"

    def block(self):
        return self.home.sb(
            "status", "blocked", "--reason", "waiting on CI", cwd=self.repo, env=RUN_ON_TICKET_5
        )

    def test_blocked_records_status_and_reason_on_the_run(self) -> None:
        result = self.block()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.home.rows("SELECT run_id, reported_status, reported_reason FROM runs"),
            [("r1", "blocked", "waiting on CI")],
        )

    def test_blocked_records_status_and_reason_on_the_ticket(self) -> None:
        result = self.block()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.home.rows("SELECT number, reported_status, reported_reason FROM tickets"),
            [(5, "blocked", "waiting on CI")],
        )

    def test_blocked_sets_the_tickets_reported_cause(self) -> None:
        result = self.block()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT reported_cause FROM tickets"), [(1,)])

    def test_blocked_makes_the_tickets_harness_status_blocked(self) -> None:
        result = self.block()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT harness_status FROM tickets"), [("blocked",)])

    def test_blocked_leaves_the_questions_cause_clear(self) -> None:
        result = self.block()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT questions_cause FROM tickets"), [(0,)])

    def test_blocked_without_a_reason_blocks_the_ticket(self) -> None:
        result = self.home.sb("status", "blocked", cwd=self.repo, env=RUN_ON_TICKET_5)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT harness_status FROM tickets"), [("blocked",)])


class NonBlockingStatusTest(SbTestCase):
    def test_non_blocking_status_leaves_a_new_ticket_ready(self) -> None:
        for status in NON_BLOCKING_STATUSES:
            with self.subTest(status):
                home = self.registered_home("alpha")

                result = home.sb(
                    "status", status, cwd=home.side_projects / "alpha", env=RUN_ON_TICKET_5
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    home.rows("SELECT number, harness_status FROM tickets"), [(5, "ready")]
                )

    def test_non_blocking_status_keeps_a_blocked_ticket_blocked(self) -> None:
        for status in NON_BLOCKING_STATUSES:
            with self.subTest(status):
                home = self.registered_home("alpha")
                repo = home.side_projects / "alpha"
                home.sb_ok("status", "blocked", "--reason", "waiting on CI", cwd=repo, env=RUN_ON_TICKET_5)

                result = home.sb("status", status, cwd=repo, env=RUN_ON_TICKET_5)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(home.rows("SELECT harness_status FROM tickets"), [("blocked",)])

    def test_non_blocking_status_after_blocked_becomes_the_last_reported_status(self) -> None:
        for status in NON_BLOCKING_STATUSES:
            with self.subTest(status):
                home = self.registered_home("alpha")
                repo = home.side_projects / "alpha"
                home.sb_ok("status", "blocked", "--reason", "waiting on CI", cwd=repo, env=RUN_ON_TICKET_5)

                result = home.sb("status", status, cwd=repo, env=RUN_ON_TICKET_5)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(home.rows("SELECT reported_status FROM tickets"), [(status,)])


class RunStatusTest(SbTestCase):
    def test_each_status_is_recorded_as_the_runs_last_reported_status(self) -> None:
        for status in ALL_STATUSES:
            with self.subTest(status):
                home = self.registered_home("alpha")

                result = home.sb(
                    "status", status, cwd=home.side_projects / "alpha", env=RUN_ON_TICKET_5
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    home.rows("SELECT run_id, reported_status FROM runs"), [("r1", status)]
                )

    def test_progress_with_a_reason_records_the_reason_on_the_run(self) -> None:
        home = self.registered_home("alpha")

        result = home.sb(
            "status", "progress", "--reason", "half way",
            cwd=home.side_projects / "alpha", env=RUN_ON_TICKET_5,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(home.rows("SELECT reported_reason FROM runs"), [("half way",)])

    def test_status_in_one_run_leaves_another_runs_status(self) -> None:
        home = self.registered_home("alpha")
        repo = home.side_projects / "alpha"
        home.sb_ok("status", "blocked", "--reason", "waiting on CI", cwd=repo, env=RUN_ON_TICKET_5)

        result = home.sb("status", "progress", cwd=repo, env={"SB_RUN_ID": "r2", "SB_TICKET": "6"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            home.rows("SELECT reported_status, reported_reason FROM runs WHERE run_id = 'r1'"),
            [("blocked", "waiting on CI")],
        )


class TicketlessStatusTest(SbTestCase):
    """A run that reported on ticket 5 earlier now reports with no ticket."""

    def setUp(self) -> None:
        self.home = self.registered_home("alpha")
        self.repo = self.home.side_projects / "alpha"
        self.home.sb_ok("status", "progress", cwd=self.repo, env=RUN_ON_TICKET_5)

    def test_status_without_a_ticket_records_on_the_run(self) -> None:
        result = self.home.sb("status", "done", cwd=self.repo, env={"SB_RUN_ID": "r1"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT run_id, reported_status FROM runs"), [("r1", "done")])

    def test_status_without_a_ticket_changes_no_other_record(self) -> None:
        before = self.home.contents()
        before.pop("runs")

        result = self.home.sb("status", "done", cwd=self.repo, env={"SB_RUN_ID": "r1"})

        self.assertEqual(result.returncode, 0, result.stderr)
        after = self.home.contents()
        after.pop("runs")
        self.assertEqual(after, before)


class TicketFlagTest(SbTestCase):
    def setUp(self) -> None:
        self.home = self.registered_home("alpha")
        self.repo = self.home.side_projects / "alpha"

    def test_ticket_flag_names_the_ticket_without_sb_ticket(self) -> None:
        result = self.home.sb("status", "--ticket", "9", "blocked", cwd=self.repo, env={"SB_RUN_ID": "r1"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.home.rows("SELECT number, reported_status FROM tickets"), [(9, "blocked")]
        )

    def test_ticket_flag_takes_precedence_over_sb_ticket(self) -> None:
        result = self.home.sb("status", "--ticket", "9", "blocked", cwd=self.repo, env=RUN_ON_TICKET_5)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.home.rows("SELECT reported_status FROM tickets WHERE number = 9"), [("blocked",)]
        )


class ReasonTextTest(SbTestCase):
    def test_status_stores_the_reason_verbatim(self) -> None:
        for case, reason in VERBATIM_REASONS:
            with self.subTest(case):
                home = self.registered_home("alpha")

                result = home.sb(
                    "status", "blocked", "--reason", reason,
                    cwd=home.side_projects / "alpha", env=RUN_ON_TICKET_5,
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(home.rows("SELECT reported_reason FROM runs"), [(reason,)])


if __name__ == "__main__":
    unittest.main()
