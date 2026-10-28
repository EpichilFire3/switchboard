"""The fake Bot API is the test seam for every Telegram call. It keeps chats, messages and reactions, and
refuses what Telegram refuses: text over 4096 characters, callback data over 64 bytes, and HTML that does not
parse. A refusal answers with the HTTP status and the Bot API's error body
`{"ok": false, "error_code": <status>, "description": "Bad Request: ..."}`.

Requests are built as the Bot API defines them: POST https://api.telegram.org/bot<token>/<method> with a JSON
body, handed to the fake as the client's transport.
"""

import json
import sys
import unittest
import urllib.request

from tests.sb_harness import SRC

sys.dont_write_bytecode = True
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from switchboard.fake_telegram import FakeBotApi

TOKEN = "7000000001:AAF-first-token-for-tests"
UNKNOWN_TOKEN = "7000000009:AAZ-token-telegram-never-issued"
GROUP = -1001234567890
UNKNOWN_CHAT = -1005555555555
OWNER = 7123456789

REFUSED = (400, False, 400, True)


def call(
    fake: FakeBotApi, method: str, params: dict, token: str = TOKEN
) -> tuple[int, dict]:
    """One Bot API call through the fake: the HTTP status and the decoded JSON body."""
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    status, body = fake(request, 60)
    return status, json.loads(body)


def refusal(status: int, body: dict) -> tuple[int, object, object, bool]:
    """A refusal's shape: status, ok, error_code, and whether the description starts `Bad Request: `."""
    return (
        status,
        body.get("ok"),
        body.get("error_code"),
        str(body.get("description", "")).startswith("Bad Request: "),
    )


def keyboard(*callback_data: str) -> dict:
    return {
        "inline_keyboard": [
            [{"text": f"Option {index}", "callback_data": data}]
            for index, data in enumerate(callback_data, start=1)
        ]
    }


class FakeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeBotApi(TOKEN)
        self.chat = self.fake.add_chat(GROUP, "supergroup", True)

    def kept_texts(self) -> list[str]:
        return [message.text for message in self.chat.messages.values()]


class SendMessageTest(FakeTestCase):
    def test_text_up_to_4096_characters_is_sent(self) -> None:
        for case, text in (
            ("4096 ascii characters", "a" * 4096),
            ("4096 accented characters", "é" * 4096),
            ("one character", "a"),
        ):
            with self.subTest(case):
                self.setUp()

                status, body = call(self.fake, "sendMessage", {"chat_id": GROUP, "text": text})

                self.assertEqual((status, body.get("ok")), (200, True), body)
                self.assertEqual(self.kept_texts(), [text])

    def test_text_over_4096_characters_is_refused(self) -> None:
        for case, text in (
            ("4097 ascii characters", "a" * 4097),
            ("4097 accented characters", "é" * 4097),
            ("10000 characters", "a" * 10000),
        ):
            with self.subTest(case):
                status, body = call(self.fake, "sendMessage", {"chat_id": GROUP, "text": text})

                self.assertEqual(refusal(status, body), REFUSED, body)

    def test_refused_text_is_not_kept(self) -> None:
        call(self.fake, "sendMessage", {"chat_id": GROUP, "text": "a" * 4097})

        self.assertEqual(self.kept_texts(), [])

    def test_html_tags_do_not_count_toward_the_text_limit(self) -> None:
        text = "<b>" + "a" * 4096 + "</b>"

        status, body = call(
            self.fake, "sendMessage", {"chat_id": GROUP, "text": text, "parse_mode": "HTML"}
        )

        self.assertEqual((status, body.get("ok")), (200, True), body)

    def test_empty_text_is_refused(self) -> None:
        status, body = call(self.fake, "sendMessage", {"chat_id": GROUP, "text": ""})

        self.assertEqual(refusal(status, body), REFUSED, body)

    def test_send_to_an_unknown_chat_is_refused(self) -> None:
        status, body = call(self.fake, "sendMessage", {"chat_id": UNKNOWN_CHAT, "text": "hello"})

        self.assertEqual(refusal(status, body), REFUSED, body)

    def test_send_with_a_wrong_token_is_refused_with_401(self) -> None:
        status, body = call(
            self.fake, "sendMessage", {"chat_id": GROUP, "text": "hello"}, token=UNKNOWN_TOKEN
        )

        self.assertEqual(
            (status, body.get("ok"), body.get("error_code"), self.kept_texts()), (401, False, 401, [])
        )

    def test_unknown_method_is_refused_with_404(self) -> None:
        status, body = call(self.fake, "sendDice", {"chat_id": GROUP})

        self.assertEqual((status, body.get("ok"), body.get("error_code")), (404, False, 404))


class CallbackDataTest(FakeTestCase):
    def test_callback_data_up_to_64_bytes_is_sent(self) -> None:
        for case, data in (
            ("64 ascii bytes", "a" * 64),
            ("32 two-byte characters, 64 bytes", "é" * 32),
            ("one byte", "a"),
        ):
            with self.subTest(case):
                status, body = call(
                    self.fake,
                    "sendMessage",
                    {"chat_id": GROUP, "text": "Pick one", "reply_markup": keyboard(data)},
                )

                self.assertEqual((status, body.get("ok")), (200, True), body)

    def test_callback_data_over_64_bytes_is_refused(self) -> None:
        for case, buttons in (
            ("65 ascii bytes", ("a" * 65,)),
            ("33 two-byte characters, 66 bytes", ("é" * 33,)),
            ("64 two-byte characters, 128 bytes", ("é" * 64,)),
            ("second button over the limit", ("a", "a" * 65)),
        ):
            with self.subTest(case):
                self.setUp()

                status, body = call(
                    self.fake,
                    "sendMessage",
                    {"chat_id": GROUP, "text": "Pick one", "reply_markup": keyboard(*buttons)},
                )

                self.assertEqual(
                    (refusal(status, body), self.kept_texts()), (REFUSED, []), body
                )


class HtmlTest(FakeTestCase):
    def test_html_that_parses_is_sent(self) -> None:
        for case, text in (
            ("bold", "<b>Harness</b> is ready"),
            ("link", '<a href="https://example.com/issues/5">ticket 5</a>'),
            ("escaped less-than", "a &lt; b &amp;&amp; c &gt; d"),
            ("nested", "<b>bold <i>and italic</i></b>"),
        ):
            with self.subTest(case):
                status, body = call(
                    self.fake, "sendMessage", {"chat_id": GROUP, "text": text, "parse_mode": "HTML"}
                )

                self.assertEqual((status, body.get("ok")), (200, True), body)

    def test_html_that_does_not_parse_is_refused(self) -> None:
        for case, text in (
            ("unclosed tag", "<b>Harness is ready"),
            ("mismatched closing tag", "<b>Harness</i> is ready"),
        ):
            with self.subTest(case):
                self.setUp()

                status, body = call(
                    self.fake, "sendMessage", {"chat_id": GROUP, "text": text, "parse_mode": "HTML"}
                )

                self.assertEqual(
                    (refusal(status, body), self.kept_texts()), (REFUSED, []), body
                )

    def test_markup_is_plain_text_without_html_parse_mode(self) -> None:
        status, body = call(self.fake, "sendMessage", {"chat_id": GROUP, "text": "<b>Harness is ready"})

        self.assertEqual((status, body.get("ok"), self.kept_texts()), (200, True, ["<b>Harness is ready"]))


class ReactionTest(FakeTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.message = self.fake.post(GROUP, OWNER, "an idea")

    def kept_reactions(self) -> list[str]:
        return self.chat.messages[self.message.id].reactions

    def react(self, *emoji: str) -> tuple[int, dict]:
        return call(
            self.fake,
            "setMessageReaction",
            {
                "chat_id": GROUP,
                "message_id": self.message.id,
                "reaction": [{"type": "emoji", "emoji": symbol} for symbol in emoji],
            },
        )

    def test_reaction_is_kept_on_the_message(self) -> None:
        for case, emoji in (
            ("one emoji", ("\N{THUMBS UP SIGN}",)),
            ("two emoji in order", ("\N{FIRE}", "\N{THUMBS UP SIGN}")),
            ("no emoji", ()),
        ):
            with self.subTest(case):
                self.setUp()

                status, body = self.react(*emoji)

                self.assertEqual((status, body.get("ok")), (200, True), body)
                self.assertEqual(self.kept_reactions(), list(emoji))

    def test_reaction_replaces_the_previous_reaction(self) -> None:
        self.react("\N{THUMBS UP SIGN}")

        status, body = self.react("\N{FIRE}")

        self.assertEqual((status, body.get("ok")), (200, True), body)
        self.assertEqual(self.kept_reactions(), ["\N{FIRE}"])


if __name__ == "__main__":
    unittest.main()
