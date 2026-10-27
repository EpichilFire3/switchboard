"""`sb decide` inside a run writes a decision record (source agent), creating the run record and
the ticket record on first reference."""

import unittest

from tests.sb_harness import SbTestCase

RUN_ON_TICKET_5 = {"SB_RUN_ID": "r1", "SB_TICKET": "5"}

DECISION_REPOS = (
    "SELECT repos.name, decisions.text FROM decisions JOIN repos ON repos.id = decisions.repo_id"
)
DECISION_TICKET_CASES = (
    ("with a ticket", RUN_ON_TICKET_5),
    ("without a ticket", {"SB_RUN_ID": "r1"}),
)

VERBATIM_TEXTS = (
    ("sql fragment", "use sqlite'); DROP TABLE decisions; --"),
    ("html and format specifiers", "<b>bold</b> %s %d {0} {name}"),
    ("accents cjk rtl and emoji with joiner", "café 漢字 مرحبا \U0001F469‍\U0001F4BB"),
    ("combining accent", "café"),
    ("zero-width space", "zero​width"),
    ("newline and tab", "line one\nline two\tend"),
    ("quotes and backslashes", "it's \"quoted\" \\ back\\slash"),
    ("literal null", "null"),
    ("literal None", "None"),
    ("literal zero", "0"),
    ("ten thousand characters", "d" * 10000),
)


class DecideTest(SbTestCase):
    def setUp(self) -> None:
        self.home = self.registered_home("alpha")
        self.repo = self.home.side_projects / "alpha"

    def test_decide_writes_one_decision_record_with_source_agent(self) -> None:
        result = self.home.sb("decide", "x", cwd=self.repo, env=RUN_ON_TICKET_5)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.home.rows("SELECT run_id, text, source FROM decisions"), [("r1", "x", "agent")]
        )

    def test_decide_creates_the_run_record(self) -> None:
        result = self.home.sb("decide", "x", cwd=self.repo, env=RUN_ON_TICKET_5)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT run_id FROM runs"), [("r1",)])

    def test_decide_creates_the_ticket_record_named_by_sb_ticket(self) -> None:
        result = self.home.sb("decide", "x", cwd=self.repo, env=RUN_ON_TICKET_5)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT number FROM tickets"), [(5,)])

    def test_decide_ticket_flag_creates_the_ticket_record(self) -> None:
        result = self.home.sb("decide", "--ticket", "6", "y", cwd=self.repo, env={"SB_RUN_ID": "r1"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT number FROM tickets"), [(6,)])

    def test_decide_without_a_ticket_creates_no_ticket_record(self) -> None:
        result = self.home.sb("decide", "x", cwd=self.repo, env={"SB_RUN_ID": "r1"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT number FROM tickets"), [])

    def test_ticket_number_unknown_to_github_gets_a_record(self) -> None:
        result = self.home.sb(
            "decide", "x", cwd=self.repo, env={"SB_RUN_ID": "r1", "SB_TICKET": "987654"}
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT number FROM tickets"), [(987654,)])

    def test_second_decide_in_a_run_adds_a_second_record(self) -> None:
        self.home.sb_ok("decide", "x", cwd=self.repo, env=RUN_ON_TICKET_5)

        result = self.home.sb("decide", "y", cwd=self.repo, env=RUN_ON_TICKET_5)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.home.rows("SELECT run_id, text FROM decisions ORDER BY text"),
            [("r1", "x"), ("r1", "y")],
        )

    def test_second_command_in_a_run_keeps_one_run_record_and_its_first_seen(self) -> None:
        self.home.sb_ok("decide", "x", cwd=self.repo, env=RUN_ON_TICKET_5)
        first = self.home.rows("SELECT run_id, first_seen FROM runs")

        result = self.home.sb("decide", "y", cwd=self.repo, env=RUN_ON_TICKET_5)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT run_id, first_seen FROM runs"), first)

    def test_second_reference_to_a_ticket_keeps_one_ticket_record(self) -> None:
        self.home.sb_ok("decide", "x", cwd=self.repo, env=RUN_ON_TICKET_5)

        result = self.home.sb("decide", "y", cwd=self.repo, env={"SB_RUN_ID": "r2", "SB_TICKET": "5"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT number FROM tickets"), [(5,)])


class DecisionRepoTest(SbTestCase):
    """Three registered repos; the decision is made from the middle one."""

    def test_decision_records_the_repo_resolved_from_the_current_directory(self) -> None:
        for case, env in DECISION_TICKET_CASES:
            with self.subTest(case):
                home = self.registered_home("alpha", "beta", "gamma")

                result = home.sb("decide", "x", cwd=home.side_projects / "beta", env=env)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(home.rows(DECISION_REPOS), [("beta", "x")])


class DecisionTextTest(SbTestCase):
    def test_decide_stores_the_text_verbatim(self) -> None:
        for case, text in VERBATIM_TEXTS:
            with self.subTest(case):
                home = self.registered_home("alpha")

                result = home.sb(
                    "decide", text, cwd=home.side_projects / "alpha", env=RUN_ON_TICKET_5
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(home.rows("SELECT text FROM decisions"), [(text,)])


class ParallelDecideTest(SbTestCase):
    """Four commands of one run started together, each the run's and ticket's first reference."""

    def setUp(self) -> None:
        self.home = self.registered_home("alpha")
        self.outcomes = self.home.sb_parallel(
            4, "decide", "x", cwd=self.home.side_projects / "alpha", env=RUN_ON_TICKET_5
        )

    def test_parallel_decides_all_succeed(self) -> None:
        self.assertEqual([code for code, _ in self.outcomes], [0, 0, 0, 0], self.outcomes)

    def test_parallel_decides_in_one_run_create_one_run_record(self) -> None:
        self.assertEqual(self.home.rows("SELECT run_id FROM runs"), [("r1",)])

    def test_parallel_decides_on_one_ticket_create_one_ticket_record(self) -> None:
        self.assertEqual(self.home.rows("SELECT number FROM tickets"), [(5,)])

    def test_parallel_decides_write_one_decision_each(self) -> None:
        self.assertEqual(self.home.rows("SELECT COUNT(*) FROM decisions"), [(4,)])


if __name__ == "__main__":
    unittest.main()
