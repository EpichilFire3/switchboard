"""A fake Telegram Bot API that stands in for the network as the client's transport.

It reads the HTTP requests the client builds and answers in the Bot API's JSON shape, keeping
chats, topics, messages, reactions and an update queue. It refuses what Telegram refuses and a
renderer can get wrong: text over 4096 characters, callback data over 64 bytes, and HTML that does
not parse. A long poll returns at once with whatever is queued.
"""

import html
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from switchboard.telegram import API

BOT_ID = 1000
MAX_TEXT = 4096
MAX_CALLBACK_DATA_BYTES = 64
# Telegram's HTML parse mode: these tags and the four named entities, nothing else.
TAGS = frozenset(
    "a b blockquote code del em i ins pre s span strike strong tg-emoji tg-spoiler u".split()
)
MARKUP = re.compile(
    r"<(/?)([a-z-]+)(?:\s[^<>]*)?>|&(?:lt|gt|amp|quot|#[0-9]+|#x[0-9a-fA-F]+);|[<>&]"
)

Json = dict[str, object]


class BadRequest(Exception):
    pass


@dataclass
class FakeMessage:
    id: int
    sender_id: int
    text: str
    thread_id: int | None = None
    reply_markup: Json | None = None
    reactions: list[str] = field(default_factory=list)


@dataclass
class FakeChat:
    id: int
    type: str
    is_forum: bool
    topics: dict[int, str] = field(default_factory=dict)
    messages: dict[int, FakeMessage] = field(default_factory=dict)
    # A topic's id is the id of the service message that created it, so both share one sequence.
    last_message_id: int = 0

    def next_message_id(self) -> int:
        self.last_message_id += 1
        return self.last_message_id


def visible_text(text: str) -> str:
    """The text an HTML-mode message shows, or BadRequest where Telegram cannot parse it."""
    open_tags = []
    for match in MARKUP.finditer(text):
        closing, tag = match.group(1, 2)
        if tag is None:
            if len(match.group()) == 1:
                where = match.start()
                raise BadRequest(f"can't parse entities: unescaped {match.group()!r} at {where}")
        elif tag not in TAGS:
            raise BadRequest(f'can\'t parse entities: unsupported start tag "{tag}"')
        elif not closing:
            open_tags.append(tag)
        elif not open_tags or open_tags.pop() != tag:
            raise BadRequest(f'can\'t parse entities: unexpected end tag "{tag}"')
    if open_tags:
        raise BadRequest(f'can\'t parse entities: can\'t find end tag "{open_tags[-1]}"')
    return html.unescape(re.sub(r"<[^<>]*>", "", text))


def param[T](params: Json, name: str, kind: type[T]) -> T | None:
    """A request parameter, None when absent, or BadRequest when it has the wrong JSON type."""
    value = params.get(name)
    if value is None or isinstance(value, kind):
        return value
    raise BadRequest(f'field "{name}" must be of type {kind.__name__}')


class FakeBotApi:
    def __init__(self, token: str, username: str = "switchboard_test_bot") -> None:
        self.token = token
        self.username = username
        self.chats: dict[int, FakeChat] = {}
        self.updates: list[tuple[int, Json]] = []
        self.last_update_id = 0

    def add_chat(
        self, chat_id: int, chat_type: str = "supergroup", is_forum: bool = True
    ) -> FakeChat:
        self.chats[chat_id] = FakeChat(chat_id, chat_type, is_forum)
        return self.chats[chat_id]

    def post(
        self, chat_id: int, sender_id: int, text: str, thread_id: int | None = None
    ) -> FakeMessage:
        """A person writes in a chat: the message is stored and queued as an update for the bot."""
        chat = self.chats[chat_id]
        message = FakeMessage(chat.next_message_id(), sender_id, text, thread_id)
        chat.messages[message.id] = message
        self.last_update_id += 1
        update = {"update_id": self.last_update_id, "message": self._message_json(chat, message)}
        self.updates.append((self.last_update_id, update))
        return message

    def __call__(self, request: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
        token, _, method = request.full_url.removeprefix(f"{API}/bot").rpartition("/")
        body = json.loads(request.data) if isinstance(request.data, bytes) else {}
        params: Json = body if isinstance(body, dict) else {}
        if urllib.parse.unquote(token) != self.token:
            return self._refusal(401, "Unauthorized")
        handler = {
            "getMe": self._get_me,
            "getUpdates": self._get_updates,
            "createForumTopic": self._create_forum_topic,
            "sendMessage": self._send_message,
            "setMessageReaction": self._set_message_reaction,
        }.get(method)
        if handler is None:
            return self._refusal(404, "Not Found")
        try:
            result = handler(params)
        except BadRequest as error:
            return self._refusal(400, f"Bad Request: {error}")
        return 200, json.dumps({"ok": True, "result": result}).encode()

    def _refusal(self, status: int, description: str) -> tuple[int, bytes]:
        body = {"ok": False, "error_code": status, "description": description}
        return status, json.dumps(body).encode()

    def _chat(self, params: Json) -> FakeChat:
        chat_id = param(params, "chat_id", int)
        chat = None if chat_id is None else self.chats.get(chat_id)
        if chat is None:
            raise BadRequest("chat not found")
        return chat

    def _message_json(self, chat: FakeChat, message: FakeMessage) -> Json:
        chat_json: Json = {"id": chat.id, "type": chat.type}
        if chat.is_forum:
            chat_json["is_forum"] = True
        body: Json = {
            "message_id": message.id,
            "date": 0,
            "chat": chat_json,
            "from": {"id": message.sender_id, "is_bot": message.sender_id == BOT_ID},
            "text": message.text,
        }
        if message.thread_id is not None:
            body |= {"message_thread_id": message.thread_id, "is_topic_message": True}
        if message.reply_markup is not None:
            body["reply_markup"] = message.reply_markup
        return body

    def _get_me(self, params: Json) -> Json:
        return {"id": BOT_ID, "is_bot": True, "username": self.username}

    def _get_updates(self, params: Json) -> list[Json]:
        # A higher offset confirms every update below it, and Telegram forgets those.
        offset = param(params, "offset", int) or 0
        self.updates = [(number, update) for number, update in self.updates if number >= offset]
        return [update for _, update in self.updates]

    def _create_forum_topic(self, params: Json) -> Json:
        chat = self._chat(params)
        if not chat.is_forum:
            raise BadRequest("the chat is not a forum")
        name = param(params, "name", str)
        if not name:
            raise BadRequest("topic name is empty")
        topic = chat.next_message_id()
        chat.topics[topic] = name
        return {"message_thread_id": topic, "name": name, "icon_color": 7322096}

    def _send_message(self, params: Json) -> Json:
        chat = self._chat(params)
        thread_id = param(params, "message_thread_id", int)
        if thread_id is not None and thread_id not in chat.topics:
            raise BadRequest("message thread not found")
        text = param(params, "text", str) or ""
        shown = visible_text(text) if params.get("parse_mode") == "HTML" else text
        if not shown.strip():
            raise BadRequest("message text is empty")
        # Telegram counts UTF-16 code units of the text left after entity parsing.
        if len(shown.encode("utf-16-le")) // 2 > MAX_TEXT:
            raise BadRequest("message is too long")
        markup = param(params, "reply_markup", dict)
        for row in (markup or {}).get("inline_keyboard", []):
            for button in row:
                data = button.get("callback_data")
                if data is not None and not 1 <= len(data.encode()) <= MAX_CALLBACK_DATA_BYTES:
                    raise BadRequest("BUTTON_DATA_INVALID")
        message = FakeMessage(chat.next_message_id(), BOT_ID, shown, thread_id, markup)
        chat.messages[message.id] = message
        return self._message_json(chat, message)

    def _set_message_reaction(self, params: Json) -> bool:
        messages = self._chat(params).messages
        message_id = param(params, "message_id", int)
        message = None if message_id is None else messages.get(message_id)
        if message is None:
            raise BadRequest("message to react not found")
        reactions = param(params, "reaction", list) or []
        message.reactions = [reaction["emoji"] for reaction in reactions]
        return True
