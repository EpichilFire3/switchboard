import fcntl
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NamedTuple

API = "https://api.telegram.org"
CALL_TIMEOUT_SECONDS = 30
# Telegram holds a long poll open for up to POLL_SECONDS; the client waits 10 s longer before it
# gives up, so an empty poll ends on Telegram's side and not as a client timeout.
POLL_SECONDS = 50
POLL_READ_SECONDS = 60

# Sends one built request with a read timeout and returns the HTTP status and the body. Tests pass
# switchboard.fake_telegram.FakeBotApi in place of the network.
Transport = Callable[[urllib.request.Request, float], tuple[int, bytes]]


def urlopen_transport(request: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        # The Bot API explains a refusal in the JSON body of the 4xx or 5xx, which the client reads.
        return error.code, error.read()


class TelegramError(Exception):
    pass


class Message(NamedTuple):
    chat_id: int
    chat_type: str
    is_forum: bool
    sender_id: int
    text: str


class Update(NamedTuple):
    id: int
    message: Message | None


class Bot:
    def __init__(self, token: str, transport: Transport) -> None:
        self.url = f"{API}/bot{urllib.parse.quote(token, safe=':')}/"
        self.transport = transport

    # Any is json.loads output; each public method below parses it into a named type.
    def _call(
        self, method: str, read_timeout: float = CALL_TIMEOUT_SECONDS, **params: object
    ) -> Any:
        request = urllib.request.Request(
            self.url + method,
            data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"},
        )
        status, body = self.transport(request, read_timeout)
        reply = json.loads(body)
        if not reply["ok"]:
            raise TelegramError(f"{status} {reply['description']}")
        return reply["result"]

    def get_username(self) -> str:
        return self._call("getMe")["username"]

    def get_updates(self, offset: int, timeout: int = POLL_SECONDS) -> list[Update]:
        updates = []
        for raw in self._call("getUpdates", POLL_READ_SECONDS, offset=offset, timeout=timeout):
            message = raw.get("message")
            if message is not None:
                chat = message["chat"]
                message = Message(
                    chat["id"],
                    chat["type"],
                    chat.get("is_forum", False),
                    message["from"]["id"],
                    message.get("text", ""),
                )
            updates.append(Update(raw["update_id"], message))
        return updates

    def create_forum_topic(self, chat_id: int, name: str) -> int:
        return self._call("createForumTopic", chat_id=chat_id, name=name)["message_thread_id"]


@contextmanager
def poller_lock() -> Iterator[bool]:
    """Yield whether this process now holds the single-poller lock, held until the block ends.

    Telegram serves getUpdates to one consumer per token, so sb-inbox and sb setup telegram poll
    only while holding it.
    """
    path = Path.home() / ".switchboard" / "inbox.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True
