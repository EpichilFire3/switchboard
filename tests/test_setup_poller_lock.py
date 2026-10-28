"""One process polls the bot token at a time, enforced by a file lock. `sb setup telegram` is a poller: it
takes the single-poller lock, and while another process holds it, setup refuses before any Telegram call and
tells the owner to stop `sb-inbox` first."""

import subprocess
import sys
import unittest

from tests.sb_harness import COMMAND_TIMEOUT_SECONDS, SbTestCase
from tests.telegram_harness import (
    ACCEPTED_TOKEN,
    GROUP,
    GROUP_WITH_TOPICS,
    HOLDER,
    OWNER,
    hold_poller_lock,
    release_poller_lock,
    run_setup,
    setup_files_present,
    telegram_config,
)

CLAIM_IN_GROUP = ((GROUP, OWNER, "/claim"),)


class LockHeldTest(SbTestCase):
    """Another process (standing in for a running `sb-inbox`) holds the single-poller lock."""

    def setUp(self) -> None:
        self.home = self.registered_home("alpha")
        holder = hold_poller_lock(self.home)
        self.addCleanup(release_poller_lock, holder)

    def run_setup_while_held(self):
        return run_setup(
            self.home, typed=ACCEPTED_TOKEN, chats=(GROUP_WITH_TOPICS,), owner_writes=CLAIM_IN_GROUP
        )

    def test_setup_exits_non_zero_while_another_process_polls(self) -> None:
        run = self.run_setup_while_held()

        self.assertEqual(run.still_waiting, False, run.stderr)
        self.assertNotEqual(run.exit_code, 0, run.stderr)

    def test_setup_makes_no_telegram_call_while_another_process_polls(self) -> None:
        run = self.run_setup_while_held()

        self.assertEqual(run.calls, [], run.stderr)

    def test_setup_tells_the_owner_to_stop_sb_inbox(self) -> None:
        run = self.run_setup_while_held()

        self.assertIn("sb-inbox", run.stdout + run.stderr)

    def test_setup_writes_no_file_while_another_process_polls(self) -> None:
        run = self.run_setup_while_held()

        self.assertEqual(setup_files_present(self.home), [], run.stderr)


class LockTakenTest(SbTestCase):
    def setUp(self) -> None:
        self.home = self.registered_home("alpha")

    def test_setup_holds_the_poller_lock_while_it_waits_for_the_claim(self) -> None:
        run = run_setup(
            self.home,
            typed=ACCEPTED_TOKEN,
            chats=(GROUP_WITH_TOPICS,),
            owner_writes=CLAIM_IN_GROUP,
            probe_lock=True,
        )

        self.assertEqual(run.lock_probe, ["False"], run.stderr)

    def test_setup_proceeds_after_the_previous_holder_exited(self) -> None:
        subprocess.run(
            [sys.executable, "-P", "-c", HOLDER],
            cwd=self.home.root,
            env=self.home.env(),
            input="\n",
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=True,
        )

        run = run_setup(
            self.home, typed=ACCEPTED_TOKEN, chats=(GROUP_WITH_TOPICS,), owner_writes=CLAIM_IN_GROUP
        )

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(telegram_config(self.home).get("chat_id"), GROUP)


if __name__ == "__main__":
    unittest.main()
