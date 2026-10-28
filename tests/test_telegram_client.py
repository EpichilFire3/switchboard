"""The Telegram client takes an injected HTTP transport, and tests run it against a fake Bot API through that
transport. The fake keeps chats, topics, messages and an update queue, and answers a token it does not hold
with an error the client raises as TelegramError."""

import sys
import unittest

from tests.sb_harness import SRC

sys.dont_write_bytecode = True
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from switchboard.fake_telegram import FakeBotApi  # the declared external fake, not an application double
from switchboard.telegram import Bot, Message, TelegramError

TOKEN = "7000000001:AAF-first-token-for-tests"
UNKNOWN_TOKEN = "7000000009:AAZ-token-telegram-never-issued"
GROUP = -1001234567890
OWNER = 7123456789


class BotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeBotApi(TOKEN, username="inbox_probe_bot")
        self.fake.add_chat(GROUP, "supergroup", True)

    def test_get_username_returns_the_bots_username(self) -> None:
        bot = Bot(TOKEN, self.fake)

        self.assertEqual(bot.get_username(), "inbox_probe_bot")

    def test_bot_with_a_token_telegram_does_not_hold_raises_telegram_error(self) -> None:
        bot = Bot(UNKNOWN_TOKEN, self.fake)

        with self.assertRaises(TelegramError):
            bot.get_username()

    def test_get_updates_returns_a_posted_message_with_its_chat_sender_and_text(self) -> None:
        self.fake.post(GROUP, OWNER, "/claim")
        bot = Bot(TOKEN, self.fake)

        updates = bot.get_updates(0)

        self.assertEqual(
            [update.message for update in updates],
            [Message(GROUP, "supergroup", True, OWNER, "/claim")],
        )

    def test_get_updates_from_past_an_update_leaves_it_out(self) -> None:
        self.fake.post(GROUP, OWNER, "first")
        first_update_id = self.fake.last_update_id
        self.fake.post(GROUP, OWNER, "second")
        bot = Bot(TOKEN, self.fake)

        updates = bot.get_updates(first_update_id + 1)

        self.assertEqual([update.message.text for update in updates], ["second"])

    def test_create_forum_topic_creates_a_topic_with_that_name(self) -> None:
        bot = Bot(TOKEN, self.fake)

        topic_id = bot.create_forum_topic(GROUP, "Harness")

        self.assertEqual(self.fake.chats[GROUP].topics.get(topic_id), "Harness")

    def test_create_forum_topic_with_a_wrong_token_creates_no_topic(self) -> None:
        topics_before = dict(self.fake.chats[GROUP].topics)
        bot = Bot(UNKNOWN_TOKEN, self.fake)

        with self.assertRaises(TelegramError):
            bot.create_forum_topic(GROUP, "Harness")
        self.assertEqual(self.fake.chats[GROUP].topics, topics_before)


if __name__ == "__main__":
    unittest.main()
