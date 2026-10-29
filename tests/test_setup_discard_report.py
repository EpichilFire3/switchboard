"""After its confirming call, `sb setup telegram` prints what it discarded (Addendum 1, Behaviour 26a): one line when
the baseline call returned an update queued before setup started, and the number of updates discarded while
waiting, when there were any, not counting refused `/claim`s. When it prints either line it tells the owner to tap
again any answer given while `sb-inbox` was stopped. The report is on stdout.
"""

import re
import unittest

from tests.sb_harness import SbTestCase
from tests.telegram_harness import (
    ACCEPTED_TOKEN,
    GROUP,
    GROUP_WITH_TOPICS,
    OTHER_GROUP,
    OTHER_GROUP_WITH_TOPICS,
    OTHER_OWNER,
    OWNER,
    run_setup,
)

BASIC_GROUP = -4455667788
CLAIM_IN_GROUP = ((GROUP, OWNER, "/claim"),)
QUEUED_IDEA = ((GROUP, OWNER, "an idea for later"),)
TWO_MESSAGES_THEN_CLAIM = (
    (OTHER_GROUP, OTHER_OWNER, "hello"),
    (GROUP, OWNER, "an idea while waiting"),
    (GROUP, OWNER, "/claim"),
)


def numbers_on_discard_lines(stdout: str) -> list[str]:
    """Every number on the stdout lines that say something was discarded."""
    return [
        number
        for line in stdout.splitlines()
        if "discarded" in line.lower()
        for number in re.findall(r"\d+", line)
    ]


class DiscardReportTest(SbTestCase):
    def setUp(self) -> None:
        self.home = self.registered_home("alpha")

    def test_report_says_updates_queued_before_setup_were_discarded(self) -> None:
        run = run_setup(
            self.home,
            typed=ACCEPTED_TOKEN,
            chats=(GROUP_WITH_TOPICS,),
            queued_before=QUEUED_IDEA,
            owner_writes=CLAIM_IN_GROUP,
        )

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertIn("discarded", run.stdout.lower())

    def test_report_counts_updates_discarded_while_waiting(self) -> None:
        run = run_setup(
            self.home,
            typed=ACCEPTED_TOKEN,
            chats=(OTHER_GROUP_WITH_TOPICS, GROUP_WITH_TOPICS),
            owner_writes=TWO_MESSAGES_THEN_CLAIM,
        )

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(numbers_on_discard_lines(run.stdout), ["2"], run.stdout)

    def test_report_does_not_count_a_refused_claim(self) -> None:
        run = run_setup(
            self.home,
            typed=ACCEPTED_TOKEN,
            chats=((BASIC_GROUP, "group", False), GROUP_WITH_TOPICS),
            owner_writes=(
                (BASIC_GROUP, OWNER, "/claim"),
                (GROUP, OWNER, "an idea while waiting"),
                (GROUP, OWNER, "/claim"),
            ),
        )

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(numbers_on_discard_lines(run.stdout), ["1"], run.stdout)

    def test_report_tells_the_owner_to_tap_again(self) -> None:
        for case, queued_before, owner_writes in (
            ("an update queued before setup", QUEUED_IDEA, CLAIM_IN_GROUP),
            ("updates discarded while waiting", (), TWO_MESSAGES_THEN_CLAIM),
        ):
            with self.subTest(case):
                home = self.registered_home("alpha")

                run = run_setup(
                    home,
                    typed=ACCEPTED_TOKEN,
                    chats=(OTHER_GROUP_WITH_TOPICS, GROUP_WITH_TOPICS),
                    queued_before=queued_before,
                    owner_writes=owner_writes,
                )

                self.assertEqual(run.exit_code, 0, run.stderr)
                self.assertIn("tap again", run.stdout.lower())

    def test_setup_with_nothing_discarded_prints_no_discard_report(self) -> None:
        run = run_setup(
            self.home, typed=ACCEPTED_TOKEN, chats=(GROUP_WITH_TOPICS,), owner_writes=CLAIM_IN_GROUP
        )

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(
            ("discarded" in run.stdout.lower(), "tap again" in run.stdout.lower()),
            (False, False),
            run.stdout,
        )


if __name__ == "__main__":
    unittest.main()
