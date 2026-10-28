"""`sb setup telegram` reads the token without echoing it and verifies it with Telegram. A token Telegram
rejects ends setup with a non-zero exit and no file written."""

import unittest

from tests.sb_harness import SbTestCase
from tests.telegram_harness import (
    ACCEPTED_TOKEN,
    ACCEPTED_TOKEN_SECRET,
    GROUP,
    GROUP_WITH_TOPICS,
    OWNER,
    UNKNOWN_TOKEN,
    run_setup,
    run_setup_on_a_terminal,
    setup_files_present,
)

CLAIM_IN_GROUP = ((GROUP, OWNER, "/claim"),)


class RejectedTokenTest(SbTestCase):
    """The fake Bot API holds ACCEPTED_TOKEN; the owner types a token it does not hold."""

    def test_rejected_token_exits_non_zero(self) -> None:
        home = self.registered_home("alpha")

        run = run_setup(
            home, typed=UNKNOWN_TOKEN, chats=(GROUP_WITH_TOPICS,), owner_writes=CLAIM_IN_GROUP
        )

        self.assertEqual(run.still_waiting, False, run.stderr)
        self.assertNotEqual(run.exit_code, 0, run.stderr)

    def test_rejected_token_writes_no_file(self) -> None:
        home = self.registered_home("alpha")

        run = run_setup(
            home, typed=UNKNOWN_TOKEN, chats=(GROUP_WITH_TOPICS,), owner_writes=CLAIM_IN_GROUP
        )

        self.assertEqual(setup_files_present(home), [], run.stderr)

    def test_rejected_token_on_a_fresh_home_writes_no_file(self) -> None:
        home = self.make_home()

        run = run_setup(
            home, typed=UNKNOWN_TOKEN, chats=(GROUP_WITH_TOPICS,), owner_writes=CLAIM_IN_GROUP
        )

        self.assertEqual(setup_files_present(home), [], run.stderr)


class TokenEchoTest(SbTestCase):
    def test_token_typed_at_a_terminal_is_not_echoed(self) -> None:
        home = self.registered_home("alpha")

        run, shown = run_setup_on_a_terminal(
            home, typed=ACCEPTED_TOKEN, chats=(GROUP_WITH_TOPICS,), owner_writes=CLAIM_IN_GROUP
        )

        self.assertEqual(run.exit_code, 0, shown)
        self.assertNotIn(ACCEPTED_TOKEN_SECRET, shown)


if __name__ == "__main__":
    unittest.main()
