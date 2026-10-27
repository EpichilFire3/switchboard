"""`sb decide` and `sb status` exit non-zero without `SB_RUN_ID` and write nothing."""

import unittest

from tests.sb_harness import SbTestCase

TICKET_5_WITHOUT_RUN = {"SB_TICKET": "5"}

RUN_COMMANDS = (
    ("decide", ("decide", "x")),
    ("status blocked with reason", ("status", "blocked", "--reason", "waiting on CI")),
    ("status progress", ("status", "progress")),
)


class RunRequiredTest(SbTestCase):
    def test_command_without_sb_run_id_exits_non_zero(self) -> None:
        for case, args in RUN_COMMANDS:
            with self.subTest(case):
                home = self.registered_home("alpha")

                result = home.sb(*args, cwd=home.side_projects / "alpha", env=TICKET_5_WITHOUT_RUN)

                self.assertNotEqual(result.returncode, 0, result.stderr)

    def test_command_without_sb_run_id_writes_nothing(self) -> None:
        for case, args in RUN_COMMANDS:
            with self.subTest(case):
                home = self.registered_home("alpha")
                before = home.contents()

                home.sb(*args, cwd=home.side_projects / "alpha", env=TICKET_5_WITHOUT_RUN)

                self.assertEqual(home.contents(), before)


if __name__ == "__main__":
    unittest.main()
