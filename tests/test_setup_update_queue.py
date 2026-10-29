"""Which Telegram updates `sb setup telegram` acts on, consumes and leaves queued (Addendum 1, Behaviour 26a).

After verifying the token, setup makes one baseline call (getUpdates, offset -1, timeout 0), acts on nothing in its
answer, and from then on reads only updates that reached Telegram after setup started. Every update it reads while
waiting is consumed. The accepted `/claim` is confirmed after the commit, through that `/claim` and no further, so
what the owner sends after it stays queued for `sb-inbox`. Setup deletes the stored poll offset.
"""

import contextlib
import sqlite3
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
    SECOND_TOKEN,
    run_setup,
    run_setup_ok,
    setup_files_present,
    telegram_config,
)

CLAIM_IN_GROUP = ((GROUP, OWNER, "/claim"),)
QUEUED_IDEA_AND_FOLLOW_UP = (
    (GROUP, OWNER, "an idea for later"),
    (GROUP, OWNER, "and a second thought"),
)
STALE_CLAIM_BEHIND_150_UPDATES = ((OTHER_GROUP, OTHER_OWNER, "/claim"),) + tuple(
    (OTHER_GROUP, OTHER_OWNER, f"queued update {number}") for number in range(1, 151)
)
REPLY_METHODS = {"sendmessage", "setmessagereaction", "answercallbackquery"}


class QueuedBeforeSetupTest(SbTestCase):
    """An idea and a follow-up are queued at Telegram before setup starts; the owner then sends `/claim`."""

    def setUp(self) -> None:
        self.home = self.registered_home("alpha")

    def run_setup_with_a_queue(self):
        return run_setup(
            self.home,
            typed=ACCEPTED_TOKEN,
            chats=(GROUP_WITH_TOPICS,),
            queued_before=QUEUED_IDEA_AND_FOLLOW_UP,
            owner_writes=CLAIM_IN_GROUP,
        )

    def test_setup_accepts_a_claim_sent_after_updates_queued_before_it(self) -> None:
        run = self.run_setup_with_a_queue()

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(
            (telegram_config(self.home).get("chat_id"), telegram_config(self.home).get("owner_id")),
            (GROUP, OWNER),
        )

    def test_updates_queued_before_setup_get_no_reply(self) -> None:
        run = self.run_setup_with_a_queue()

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(REPLY_METHODS & set(run.calls), set())

    def test_updates_queued_before_setup_record_no_decision(self) -> None:
        run = self.run_setup_with_a_queue()

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(self.home.rows("SELECT COUNT(*) FROM decisions"), [(0,)])

    def test_no_update_queued_before_setup_is_delivered_again(self) -> None:
        run = self.run_setup_with_a_queue()

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(run.still_queued, [])

    def test_baseline_call_asks_for_the_newest_update_without_waiting(self) -> None:
        run = self.run_setup_with_a_queue()

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(
            [(params.get("offset"), params.get("timeout", 0)) for params in run.get_updates_params[:1]],
            [(-1, 0)],
        )


class StaleClaimTest(SbTestCase):
    """A `/claim` from an earlier setup run is still queued at Telegram when setup starts."""

    def test_claim_queued_before_setup_does_not_end_the_wait(self) -> None:
        home = self.registered_home("alpha")

        run = run_setup(
            home,
            typed=ACCEPTED_TOKEN,
            chats=(GROUP_WITH_TOPICS,),
            queued_before=CLAIM_IN_GROUP,
            owner_writes=(),
        )

        self.assertEqual(run.still_waiting, True, run.stderr)

    def test_claim_queued_before_setup_writes_nothing(self) -> None:
        home = self.registered_home("alpha")

        run = run_setup(
            home,
            typed=ACCEPTED_TOKEN,
            chats=(GROUP_WITH_TOPICS,),
            queued_before=CLAIM_IN_GROUP,
            owner_writes=(),
        )

        self.assertEqual((run.still_waiting, setup_files_present(home)), (True, []), run.stderr)

    def test_claim_behind_150_updates_does_not_end_the_wait(self) -> None:
        home = self.registered_home("alpha")

        run = run_setup(
            home,
            typed=ACCEPTED_TOKEN,
            chats=(OTHER_GROUP_WITH_TOPICS,),
            queued_before=STALE_CLAIM_BEHIND_150_UPDATES,
            owner_writes=(),
        )

        self.assertEqual(run.still_waiting, True, run.stderr)

    def test_setup_after_a_stale_claim_takes_the_new_claims_ids(self) -> None:
        home = self.registered_home("alpha")

        run = run_setup(
            home,
            typed=ACCEPTED_TOKEN,
            chats=(OTHER_GROUP_WITH_TOPICS, GROUP_WITH_TOPICS),
            queued_before=STALE_CLAIM_BEHIND_150_UPDATES,
            owner_writes=CLAIM_IN_GROUP,
        )

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(
            (telegram_config(home).get("chat_id"), telegram_config(home).get("owner_id")),
            (GROUP, OWNER),
        )

    def test_rerun_with_a_stale_claim_queued_keeps_the_previous_values(self) -> None:
        home = self.registered_home("alpha")
        run_setup_ok(
            home, typed=ACCEPTED_TOKEN, chats=(GROUP_WITH_TOPICS,), owner_writes=CLAIM_IN_GROUP
        )

        run = run_setup(
            home,
            typed=SECOND_TOKEN,
            accepts=SECOND_TOKEN,
            chats=(OTHER_GROUP_WITH_TOPICS,),
            queued_before=STALE_CLAIM_BEHIND_150_UPDATES,
            owner_writes=(),
        )

        self.assertEqual(
            (
                run.still_waiting,
                telegram_config(home).get("chat_id"),
                telegram_config(home).get("owner_id"),
            ),
            (True, GROUP, OWNER),
            run.stderr,
        )


class ConfirmTest(SbTestCase):
    def setUp(self) -> None:
        self.home = self.registered_home("alpha")

    def test_accepted_claim_is_confirmed(self) -> None:
        run = run_setup(
            self.home, typed=ACCEPTED_TOKEN, chats=(GROUP_WITH_TOPICS,), owner_writes=CLAIM_IN_GROUP
        )

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(run.still_queued, [])

    def test_messages_read_while_waiting_are_consumed(self) -> None:
        run = run_setup(
            self.home,
            typed=ACCEPTED_TOKEN,
            chats=(OTHER_GROUP_WITH_TOPICS, GROUP_WITH_TOPICS),
            owner_writes=(
                (OTHER_GROUP, OTHER_OWNER, "hello"),
                (GROUP, OWNER, "an idea while waiting"),
                (GROUP, OWNER, "/claim"),
            ),
        )

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(run.still_queued, [])

    def test_message_sent_right_after_the_claim_stays_queued(self) -> None:
        run = run_setup(
            self.home,
            typed=ACCEPTED_TOKEN,
            chats=(GROUP_WITH_TOPICS,),
            owner_writes=((GROUP, OWNER, "/claim"), (GROUP, OWNER, "right after the claim")),
        )

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(run.still_queued, ["right after the claim"])

    def test_setup_stopped_before_confirming_leaves_its_claim_queued(self) -> None:
        # getUpdates 1 is the baseline, 2 reads the /claim, 3 is the confirming call.
        run = run_setup(
            self.home,
            typed=ACCEPTED_TOKEN,
            chats=(GROUP_WITH_TOPICS,),
            owner_writes=CLAIM_IN_GROUP,
            stop_at_get_updates_call=3,
        )

        self.assertEqual(run.still_queued, ["/claim"], run.stderr)

    def test_setup_deletes_the_stored_poll_offset(self) -> None:
        with contextlib.closing(sqlite3.connect(self.home.db_path)) as conn:
            conn.execute("INSERT INTO kv (key, value) VALUES ('telegram_offset', 4242)")
            conn.commit()

        run = run_setup(
            self.home, typed=ACCEPTED_TOKEN, chats=(GROUP_WITH_TOPICS,), owner_writes=CLAIM_IN_GROUP
        )

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(self.home.rows("SELECT value FROM kv WHERE key = 'telegram_offset'"), [])


if __name__ == "__main__":
    unittest.main()
