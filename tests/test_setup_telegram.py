"""`sb setup telegram` verifies the token, takes the chat id and owner id from the owner's `/claim` in a
supergroup with topics enabled, writes the token to the secrets file (mode 600) and the ids to the config file,
and creates the Harness topic and one topic per registered repo, recording each topic id. Running it again
replaces the values and creates no topic twice.
"""

import unittest

from tests.sb_harness import SbTestCase
from tests.telegram_harness import (
    ACCEPTED_TOKEN,
    BOT_USERNAME,
    GROUP,
    GROUP_WITH_TOPICS,
    OTHER_GROUP,
    OTHER_GROUP_WITH_TOPICS,
    OTHER_OWNER,
    OWNER,
    SECOND_TOKEN,
    config_text,
    harness_topic_ids,
    repo_topic_ids,
    run_setup,
    run_setup_ok,
    secrets_lines,
    secrets_mode,
    switchboard_dir,
    telegram_config,
)

CLAIM_IN_GROUP = ((GROUP, OWNER, "/claim"),)


class FirstSetupTest(SbTestCase):
    """Two registered repos; the owner sends `/claim` in a topics-enabled supergroup."""

    def setUp(self) -> None:
        self.home = self.registered_home("alpha", "beta")

    def run_first_setup(self):
        return run_setup(
            self.home, typed=ACCEPTED_TOKEN, chats=(GROUP_WITH_TOPICS,), owner_writes=CLAIM_IN_GROUP
        )

    def test_setup_records_the_claims_chat_and_sender_in_the_config(self) -> None:
        run = self.run_first_setup()

        self.assertEqual(run.exit_code, 0, run.stderr)
        telegram = telegram_config(self.home)
        self.assertEqual(
            {"chat_id": telegram.get("chat_id"), "owner_id": telegram.get("owner_id")},
            {"chat_id": GROUP, "owner_id": OWNER},
        )

    def test_setup_writes_the_token_as_the_secrets_files_only_line(self) -> None:
        run = self.run_first_setup()

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(secrets_lines(self.home), [f"TELEGRAM_BOT_TOKEN={ACCEPTED_TOKEN}"])

    def test_setup_makes_the_secrets_file_mode_600(self) -> None:
        run = self.run_first_setup()

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(secrets_mode(self.home), 0o600)

    def test_setup_keeps_the_token_out_of_the_config_file(self) -> None:
        run = self.run_first_setup()

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertNotIn(ACCEPTED_TOKEN, config_text(self.home))

    def test_setup_creates_the_harness_topic_and_one_topic_per_registered_repo(self) -> None:
        run = self.run_first_setup()

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(run.topic_names(GROUP), ["Harness", "alpha", "beta"])

    def test_setup_records_each_repos_topic_id(self) -> None:
        run = self.run_first_setup()

        self.assertEqual(run.exit_code, 0, run.stderr)
        created = run.topic_ids(GROUP)
        self.assertEqual(
            repo_topic_ids(self.home),
            [("alpha", created.get("alpha")), ("beta", created.get("beta"))],
        )

    def test_setup_records_the_harness_topic_id(self) -> None:
        run = self.run_first_setup()

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(harness_topic_ids(self.home), [run.topic_ids(GROUP).get("Harness")])


class ClaimTest(SbTestCase):
    def test_setup_accepts_the_claim_command_in_either_form(self) -> None:
        for claim in ("/claim", f"/claim@{BOT_USERNAME}"):
            with self.subTest(claim):
                home = self.registered_home("alpha")

                run = run_setup(
                    home,
                    typed=ACCEPTED_TOKEN,
                    chats=(GROUP_WITH_TOPICS,),
                    owner_writes=((GROUP, OWNER, claim),),
                )

                self.assertEqual(run.exit_code, 0, run.stderr)
                self.assertEqual(
                    (telegram_config(home).get("chat_id"), telegram_config(home).get("owner_id")),
                    (GROUP, OWNER),
                )

    def test_setup_ignores_a_message_that_is_not_a_claim(self) -> None:
        home = self.registered_home("alpha")

        run = run_setup(
            home,
            typed=ACCEPTED_TOKEN,
            chats=(OTHER_GROUP_WITH_TOPICS, GROUP_WITH_TOPICS),
            owner_writes=((OTHER_GROUP, OTHER_OWNER, "hello"), (GROUP, OWNER, "/claim")),
        )

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(
            (telegram_config(home).get("chat_id"), telegram_config(home).get("owner_id")),
            (GROUP, OWNER),
        )

    def test_setup_with_no_registered_repo_creates_only_the_harness_topic(self) -> None:
        home = self.registered_home()

        run = run_setup(
            home, typed=ACCEPTED_TOKEN, chats=(GROUP_WITH_TOPICS,), owner_writes=CLAIM_IN_GROUP
        )

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(run.topic_names(GROUP), ["Harness"])

    def test_setup_names_a_repo_topic_after_a_directory_with_spaces_and_accents(self) -> None:
        home = self.registered_home("café notes")

        run = run_setup(
            home, typed=ACCEPTED_TOKEN, chats=(GROUP_WITH_TOPICS,), owner_writes=CLAIM_IN_GROUP
        )

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(run.topic_names(GROUP), ["Harness", "café notes"])


class RerunTest(SbTestCase):
    """Setup already ran once with the first token in GROUP, claimed by OWNER."""

    def setUp(self) -> None:
        self.home = self.registered_home("alpha", "beta")
        run_setup_ok(
            self.home, typed=ACCEPTED_TOKEN, chats=(GROUP_WITH_TOPICS,), owner_writes=CLAIM_IN_GROUP
        )
        self.first_repo_topics = repo_topic_ids(self.home)
        self.first_harness_topic = harness_topic_ids(self.home)

    def rerun_in_the_other_group(self):
        return run_setup(
            self.home,
            typed=SECOND_TOKEN,
            accepts=SECOND_TOKEN,
            chats=(OTHER_GROUP_WITH_TOPICS,),
            owner_writes=((OTHER_GROUP, OTHER_OWNER, "/claim"),),
        )

    def rerun_in_the_same_group(self):
        return run_setup(
            self.home,
            typed=SECOND_TOKEN,
            accepts=SECOND_TOKEN,
            chats=(GROUP_WITH_TOPICS,),
            owner_writes=CLAIM_IN_GROUP,
        )

    def test_rerun_replaces_the_token(self) -> None:
        run = self.rerun_in_the_other_group()

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(secrets_lines(self.home), [f"TELEGRAM_BOT_TOKEN={SECOND_TOKEN}"])

    def test_rerun_replaces_the_chat_and_owner_ids(self) -> None:
        run = self.rerun_in_the_other_group()

        self.assertEqual(run.exit_code, 0, run.stderr)
        telegram = telegram_config(self.home)
        self.assertEqual(
            {"chat_id": telegram.get("chat_id"), "owner_id": telegram.get("owner_id")},
            {"chat_id": OTHER_GROUP, "owner_id": OTHER_OWNER},
        )

    def test_rerun_keeps_the_secrets_file_mode_600(self) -> None:
        run = self.rerun_in_the_other_group()

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(secrets_mode(self.home), 0o600)

    def test_rerun_in_the_same_group_creates_no_topic(self) -> None:
        run = self.rerun_in_the_same_group()

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(run.topic_names(GROUP), [])

    def test_rerun_in_the_same_group_keeps_the_recorded_topic_ids(self) -> None:
        run = self.rerun_in_the_same_group()

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(
            (repo_topic_ids(self.home), harness_topic_ids(self.home)),
            (self.first_repo_topics, self.first_harness_topic),
        )

    def test_rerun_creates_a_topic_only_for_a_repo_registered_since(self) -> None:
        self.home.make_checkout("side-projects/gamma")
        self.home.sb_ok("repos", "scan", cwd=self.home.root)

        run = self.rerun_in_the_same_group()

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(run.topic_names(GROUP), ["gamma"])


class ExistingSecretsTest(SbTestCase):
    """A secrets file already exists, readable by everyone, holding something else."""

    def setUp(self) -> None:
        self.home = self.registered_home("alpha")
        secrets = switchboard_dir(self.home) / "secrets.env"
        secrets.write_text("TELEGRAM_BOT_TOKEN=stale\n", encoding="utf-8")
        secrets.chmod(0o644)

    def test_setup_makes_an_existing_secrets_file_mode_600(self) -> None:
        run = run_setup(
            self.home, typed=ACCEPTED_TOKEN, chats=(GROUP_WITH_TOPICS,), owner_writes=CLAIM_IN_GROUP
        )

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(secrets_mode(self.home), 0o600)

    def test_setup_replaces_the_contents_of_an_existing_secrets_file(self) -> None:
        run = run_setup(
            self.home, typed=ACCEPTED_TOKEN, chats=(GROUP_WITH_TOPICS,), owner_writes=CLAIM_IN_GROUP
        )

        self.assertEqual(run.exit_code, 0, run.stderr)
        self.assertEqual(secrets_lines(self.home), [f"TELEGRAM_BOT_TOKEN={ACCEPTED_TOKEN}"])


if __name__ == "__main__":
    unittest.main()
