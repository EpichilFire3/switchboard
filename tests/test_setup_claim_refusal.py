"""Given a `/claim` from a chat that is not a supergroup with topics enabled, `sb setup telegram` refuses it,
says why, and keeps waiting for a `/claim` that qualifies."""

import unittest

from tests.sb_harness import SbTestCase
from tests.telegram_harness import (
    ACCEPTED_TOKEN,
    GROUP,
    GROUP_WITH_TOPICS,
    OWNER,
    run_setup,
    setup_files_present,
    telegram_config,
)

BASIC_GROUP = -4455667788
SUPERGROUP_WITHOUT_TOPICS = -1001111111111

# (case, chat as (id, type, is_forum), a word the stated reason contains)
UNQUALIFIED_CHATS = (
    ("basic group", (BASIC_GROUP, "group", False), "supergroup"),
    ("supergroup without topics", (SUPERGROUP_WITHOUT_TOPICS, "supergroup", False), "topic"),
    ("private chat with the bot", (OWNER, "private", False), "supergroup"),
)


class RefusedClaimTest(SbTestCase):
    def test_claim_from_a_chat_without_topics_leaves_setup_waiting(self) -> None:
        for case, chat, _ in UNQUALIFIED_CHATS:
            with self.subTest(case):
                home = self.registered_home("alpha")

                run = run_setup(
                    home, typed=ACCEPTED_TOKEN, chats=(chat,), owner_writes=((chat[0], OWNER, "/claim"),)
                )

                self.assertEqual(run.still_waiting, True, run.stderr)

    def test_refusal_says_why_on_stderr(self) -> None:
        for case, chat, reason_word in UNQUALIFIED_CHATS:
            with self.subTest(case):
                home = self.registered_home("alpha")

                run = run_setup(
                    home, typed=ACCEPTED_TOKEN, chats=(chat,), owner_writes=((chat[0], OWNER, "/claim"),)
                )

                self.assertIn(reason_word, run.stderr.lower())

    def test_refused_claim_writes_no_config(self) -> None:
        for case, chat, _ in UNQUALIFIED_CHATS:
            with self.subTest(case):
                home = self.registered_home("alpha")

                run = run_setup(
                    home, typed=ACCEPTED_TOKEN, chats=(chat,), owner_writes=((chat[0], OWNER, "/claim"),)
                )

                self.assertEqual(
                    (run.still_waiting, setup_files_present(home)), (True, []), run.stderr
                )

    def test_setup_takes_a_later_claim_from_a_topics_enabled_supergroup(self) -> None:
        for case, chat, _ in UNQUALIFIED_CHATS:
            with self.subTest(case):
                home = self.registered_home("alpha")

                run = run_setup(
                    home,
                    typed=ACCEPTED_TOKEN,
                    chats=(chat, GROUP_WITH_TOPICS),
                    owner_writes=((chat[0], OWNER, "/claim"), (GROUP, OWNER, "/claim")),
                )

                self.assertEqual(run.exit_code, 0, run.stderr)
                self.assertEqual(telegram_config(home).get("chat_id"), GROUP)


if __name__ == "__main__":
    unittest.main()
