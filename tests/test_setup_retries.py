"""A failed baseline, poll or confirming call in `sb setup telegram` is retried until it succeeds; only a rejected
token ends setup with a non-zero exit (Addendum 1, Behaviour 26a, by Failure 39's rule).

Retries wait in real time (1 second first), so each test here takes at least a second.
Call numbers follow the Addendum 1 data flow with a script whose first message is the `/claim`: getUpdates 1 is
the baseline, 2 is the first poll (it reads the `/claim`), 3 is the confirming call.
"""

import unittest

from tests.sb_harness import SbTestCase
from tests.telegram_harness import ACCEPTED_TOKEN, GROUP, GROUP_WITH_TOPICS, OWNER, run_setup

CLAIM_IN_GROUP = ((GROUP, OWNER, "/claim"),)

# (case, the getUpdates call answered HTTP 502 once)
FAILED_CALLS = (
    ("baseline call", 1),
    ("first poll", 2),
    ("confirming call", 3),
)


class RetryTest(SbTestCase):
    def test_setup_finishes_after_a_failed_get_updates_call(self) -> None:
        for case, failed_call in FAILED_CALLS:
            with self.subTest(case):
                home = self.registered_home("alpha")

                run = run_setup(
                    home,
                    typed=ACCEPTED_TOKEN,
                    chats=(GROUP_WITH_TOPICS,),
                    owner_writes=CLAIM_IN_GROUP,
                    fail_get_updates_call=failed_call,
                )

                self.assertEqual(run.exit_code, 0, run.stderr)

    def test_claim_is_confirmed_after_a_failed_confirming_call(self) -> None:
        home = self.registered_home("alpha")

        run = run_setup(
            home,
            typed=ACCEPTED_TOKEN,
            chats=(GROUP_WITH_TOPICS,),
            owner_writes=CLAIM_IN_GROUP,
            fail_get_updates_call=3,
        )

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(run.still_queued, [])


if __name__ == "__main__":
    unittest.main()
