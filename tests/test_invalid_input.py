"""Invalid input to `sb decide` or `sb status` exits 2 with one stderr line naming the problem,
and writes nothing."""

import unittest

from tests.sb_harness import SbTestCase

RUN_ON_TICKET_5 = {"SB_RUN_ID": "r1", "SB_TICKET": "5"}
RUN_ON_BAD_SB_TICKET = {"SB_RUN_ID": "r1", "SB_TICKET": "abc"}

INVALID_INPUTS = (
    ("unknown status", ("status", "paused"), RUN_ON_TICKET_5),
    ("status in the wrong case", ("status", "BLOCKED"), RUN_ON_TICKET_5),
    ("status with underscore for hyphen", ("status", "needs_split"), RUN_ON_TICKET_5),
    ("empty status", ("status", ""), RUN_ON_TICKET_5),
    ("status missing", ("status",), RUN_ON_TICKET_5),
    ("status missing beside a reason", ("status", "--reason", "waiting on CI"), RUN_ON_TICKET_5),
    ("reason flag without a value", ("status", "blocked", "--reason"), RUN_ON_TICKET_5),
    ("status ticket flag without a value", ("status", "progress", "--ticket"), RUN_ON_TICKET_5),
    ("status ticket flag not a number", ("status", "--ticket", "abc", "progress"), RUN_ON_TICKET_5),
    ("status ticket flag a decimal", ("status", "--ticket", "5.5", "progress"), RUN_ON_TICKET_5),
    ("status with SB_TICKET not a number", ("status", "progress"), RUN_ON_BAD_SB_TICKET),
    ("decide text missing", ("decide",), RUN_ON_TICKET_5),
    ("decide ticket flag not a number", ("decide", "--ticket", "abc", "x"), RUN_ON_TICKET_5),
    ("decide with SB_TICKET not a number", ("decide", "x"), RUN_ON_BAD_SB_TICKET),
)

REJECTED_STATUSES = ("paused", "BLOCKED", "needs_split")

FLAG_PROBLEMS = (
    ("reason flag without a value", ("status", "blocked", "--reason"), "--reason"),
    ("status ticket flag without a value", ("status", "progress", "--ticket"), "--ticket"),
    ("status ticket flag not a number", ("status", "--ticket", "abc", "progress"), "--ticket"),
    ("status ticket flag a decimal", ("status", "--ticket", "5.5", "progress"), "--ticket"),
    ("decide ticket flag not a number", ("decide", "--ticket", "abc", "x"), "--ticket"),
)


class InvalidInputTest(SbTestCase):
    def test_invalid_input_exits_2(self) -> None:
        for case, args, env in INVALID_INPUTS:
            with self.subTest(case):
                home = self.registered_home("alpha")

                result = home.sb(*args, cwd=home.side_projects / "alpha", env=env)

                self.assertEqual(result.returncode, 2, result.stderr)

    def test_invalid_input_prints_one_stderr_line(self) -> None:
        for case, args, env in INVALID_INPUTS:
            with self.subTest(case):
                home = self.registered_home("alpha")

                result = home.sb(*args, cwd=home.side_projects / "alpha", env=env)

                self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)

    def test_invalid_input_writes_nothing(self) -> None:
        for case, args, env in INVALID_INPUTS:
            with self.subTest(case):
                home = self.registered_home("alpha")
                before = home.contents()

                home.sb(*args, cwd=home.side_projects / "alpha", env=env)

                self.assertEqual(home.contents(), before)

    def test_rejection_names_the_rejected_status(self) -> None:
        for status in REJECTED_STATUSES:
            with self.subTest(status):
                home = self.registered_home("alpha")

                result = home.sb("status", status, cwd=home.side_projects / "alpha", env=RUN_ON_TICKET_5)

                self.assertIn(status, result.stderr)

    def test_rejection_names_the_flag(self) -> None:
        for case, args, flag in FLAG_PROBLEMS:
            with self.subTest(case):
                home = self.registered_home("alpha")

                result = home.sb(*args, cwd=home.side_projects / "alpha", env=RUN_ON_TICKET_5)

                self.assertIn(flag, result.stderr)


if __name__ == "__main__":
    unittest.main()
