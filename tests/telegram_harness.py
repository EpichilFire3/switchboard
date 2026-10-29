"""Black-box harness for `sb setup telegram` against the fake Bot API.

Setup runs in a subprocess with a throwaway HOME. A driver calls `switchboard.cli.main` with a transport that
forwards every request to a `FakeBotApi` and plays the owner: after each getUpdates answer it posts the next
scripted message into the fake. Once the script is spent, setup that keeps polling is stopped by an exception
raised through it, which the driver records as "still waiting". The driver writes what it saw to a JSON file:
every Bot API method called, the topics created during the run, and an optional probe of the poller lock.
"""

import errno
import fcntl
import json
import os
import pty
import select
import stat
import subprocess
import sys
import termios
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from tests.sb_harness import COMMAND_TIMEOUT_SECONDS, Home

ACCEPTED_TOKEN = "7000000001:AAF-first-token-for-tests"
ACCEPTED_TOKEN_SECRET = "AAF-first-token-for-tests"
SECOND_TOKEN = "7000000002:AAG-second-token-for-tests"
UNKNOWN_TOKEN = "7000000009:AAZ-token-telegram-never-issued"
BOT_USERNAME = "switchboard_test_bot"

GROUP = -1001234567890
OWNER = 7123456789
OTHER_GROUP = -1009876543210
OTHER_OWNER = 5151515151

GROUP_WITH_TOPICS = (GROUP, "supergroup", True)
OTHER_GROUP_WITH_TOPICS = (OTHER_GROUP, "supergroup", True)

STILL_WAITING_EXIT = 75
ECHO_OFF_WAIT_SECONDS = 15

DRIVER = '''
import json
import subprocess
import sys

from switchboard.cli import main
from switchboard.fake_telegram import FakeBotApi
from switchboard.telegram import Bot

PATIENCE = 5
STILL_WAITING_EXIT = 75
PROBE = "from switchboard.telegram import poller_lock\\nwith poller_lock() as held:\\n    print(held)\\n"
BAD_GATEWAY = json.dumps({"ok": False, "error_code": 502, "description": "Bad Gateway"}).encode()


class OwnerStoppedWriting(BaseException):
    """The scripted owner has sent everything, or stopped setup, while setup is still running."""


with open(sys.argv[1], encoding="utf-8") as handle:
    scenario = json.load(handle)

fake = FakeBotApi(scenario["token"])
existing = {}
for chat_id, chat_type, is_forum in scenario["chats"]:
    existing[chat_id] = set(fake.add_chat(chat_id, chat_type, is_forum).topics)
for message in scenario["queued_before"]:
    fake.post(*message)
pending = [tuple(message) for message in scenario["owner_writes"]]
outcome = {
    "calls": [],
    "lock_probe": [],
    "still_waiting": False,
    "idle_polls": 0,
    "get_updates_calls": 0,
    "get_updates_params": [],
}


def method_of(request):
    return request.full_url.split("?", 1)[0].rsplit("/", 1)[-1].lower()


def probe_lock():
    probe = subprocess.run(
        [sys.executable, "-P", "-c", PROBE], capture_output=True, text=True, timeout=60
    )
    return probe.stdout.strip()


def telegram(request, timeout):
    method = method_of(request)
    outcome["calls"].append(method)
    if scenario["probe_every_call"]:
        outcome["lock_probe"].append(probe_lock())
    if method == "getupdates":
        outcome["get_updates_calls"] += 1
        if outcome["get_updates_calls"] == scenario["stop_at_get_updates_call"]:
            raise OwnerStoppedWriting()
        if outcome["get_updates_calls"] == scenario["fail_get_updates_call"]:
            return 502, BAD_GATEWAY
        outcome["get_updates_params"].append(json.loads(request.data) if request.data else {})
    answer = fake(request, timeout)
    if method == "getupdates":
        if scenario["probe_lock"] and not outcome["lock_probe"]:
            outcome["lock_probe"].append(probe_lock())
        if pending:
            fake.post(*pending.pop(0))
        else:
            outcome["idle_polls"] += 1
            if outcome["idle_polls"] > PATIENCE:
                raise OwnerStoppedWriting()
    return answer


try:
    main(["setup", "telegram"], transport=telegram)
except OwnerStoppedWriting:
    outcome["still_waiting"] = True
finally:
    outcome["topics_created"] = {
        str(chat_id): sorted(
            [name, topic_id]
            for topic_id, name in chat.topics.items()
            if topic_id not in existing.get(chat_id, set())
        )
        for chat_id, chat in fake.chats.items()
    }
    outcome["still_queued"] = [
        update.message.text if update.message else None
        for update in Bot(scenario["token"], fake).get_updates(0, timeout=0)
    ]
    with open(sys.argv[2], "w", encoding="utf-8") as handle:
        json.dump(outcome, handle, default=repr)

if outcome["still_waiting"]:
    sys.exit(STILL_WAITING_EXIT)
'''

HOLDER = (
    "import sys\n"
    "from switchboard.telegram import poller_lock\n"
    "with poller_lock() as held:\n"
    "    print(held, flush=True)\n"
    "    sys.stdin.readline()\n"
)

Chat = tuple[int, str, bool]
OwnerMessage = tuple[int, int, str]


@dataclass(frozen=True)
class SetupRun:
    """What one `sb setup telegram` run showed: its exit, its output, and what the fake saw."""

    exit_code: int
    stdout: str
    stderr: str
    still_waiting: bool
    calls: list[str]
    lock_probe: list[str]
    topics_created: dict[int, list[tuple[str, int]]]
    get_updates_params: list[dict]
    still_queued: list[str | None]

    def topic_names(self, chat_id: int) -> list[str]:
        """Names of the topics this run created in the chat, sorted."""
        return sorted(name for name, _ in self.topics_created.get(chat_id, []))

    def topic_ids(self, chat_id: int) -> dict[str, int]:
        """Topic id by name for the topics this run created in the chat."""
        return {name: topic_id for name, topic_id in self.topics_created.get(chat_id, [])}


@dataclass(frozen=True)
class Telegram:
    """What the fake Bot API holds and does around one setup run.

    queued_before: messages queued at Telegram before setup starts.
    owner_writes: messages the owner sends while setup runs, one after each getUpdates answer.
    probe_lock: probe the poller lock at the first getUpdates; probe_every_call: at every Telegram call.
    fail_get_updates_call: the N-th getUpdates call (from 1) is answered HTTP 502 and reaches no fake.
    stop_at_get_updates_call: the owner stops setup at the N-th getUpdates call.
    """

    accepts: str
    chats: tuple[Chat, ...]
    owner_writes: tuple[OwnerMessage, ...]
    queued_before: tuple[OwnerMessage, ...] = ()
    probe_lock: bool = False
    probe_every_call: bool = False
    fail_get_updates_call: int | None = None
    stop_at_get_updates_call: int | None = None


def _scenario(home: Home, telegram: Telegram) -> tuple[list[str], Path]:
    folder = home.root / "fake-telegram"
    folder.mkdir(exist_ok=True)
    scenario_path = folder / "scenario.json"
    outcome_path = folder / "outcome.json"
    scenario_path.write_text(
        json.dumps(
            {
                "token": telegram.accepts,
                "chats": [list(chat) for chat in telegram.chats],
                "owner_writes": [list(message) for message in telegram.owner_writes],
                "queued_before": [list(message) for message in telegram.queued_before],
                "probe_lock": telegram.probe_lock,
                "probe_every_call": telegram.probe_every_call,
                "fail_get_updates_call": telegram.fail_get_updates_call,
                "stop_at_get_updates_call": telegram.stop_at_get_updates_call,
            }
        ),
        encoding="utf-8",
    )
    outcome_path.unlink(missing_ok=True)
    command = [sys.executable, "-P", "-c", DRIVER, str(scenario_path), str(outcome_path)]
    return command, outcome_path


def _read_outcome(outcome_path: Path, exit_code: int, stdout: str, stderr: str) -> SetupRun:
    if not outcome_path.exists():
        raise AssertionError(f"the setup driver recorded nothing (exit {exit_code}): {stderr}")
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    return SetupRun(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        still_waiting=outcome["still_waiting"],
        calls=outcome["calls"],
        lock_probe=outcome["lock_probe"],
        topics_created={
            int(chat_id): [(name, int(topic_id)) for name, topic_id in topics]
            for chat_id, topics in outcome["topics_created"].items()
        },
        get_updates_params=outcome["get_updates_params"],
        still_queued=outcome["still_queued"],
    )


def run_setup(
    home: Home,
    *,
    typed: str,
    chats: tuple[Chat, ...],
    owner_writes: tuple[OwnerMessage, ...],
    accepts: str = ACCEPTED_TOKEN,
    queued_before: tuple[OwnerMessage, ...] = (),
    probe_lock: bool = False,
    probe_every_call: bool = False,
    fail_get_updates_call: int | None = None,
    stop_at_get_updates_call: int | None = None,
) -> SetupRun:
    """Run `sb setup telegram` once, typing `typed` as one stdin line, against a fake holding `accepts`."""
    command, outcome_path = _scenario(
        home,
        Telegram(
            accepts=accepts,
            chats=chats,
            owner_writes=owner_writes,
            queued_before=queued_before,
            probe_lock=probe_lock,
            probe_every_call=probe_every_call,
            fail_get_updates_call=fail_get_updates_call,
            stop_at_get_updates_call=stop_at_get_updates_call,
        ),
    )
    result = subprocess.run(
        command,
        cwd=home.root,
        env=home.env(),
        input=typed + "\n",
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
        start_new_session=True,
    )
    return _read_outcome(outcome_path, result.returncode, result.stdout, result.stderr)


def run_setup_ok(
    home: Home,
    *,
    typed: str,
    chats: tuple[Chat, ...],
    owner_writes: tuple[OwnerMessage, ...],
    accepts: str = ACCEPTED_TOKEN,
) -> SetupRun:
    """An arrange step: `run_setup`, failing the test setup unless setup exits 0."""
    run = run_setup(home, typed=typed, chats=chats, owner_writes=owner_writes, accepts=accepts)
    if run.exit_code != 0:
        raise AssertionError(f"arrange step `sb setup telegram` exited {run.exit_code}: {run.stderr}")
    return run


def _take_controlling_terminal() -> None:
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def _read_terminal(master: int, deadline: float) -> bytes:
    ready, _, _ = select.select([master], [], [], max(0.0, deadline - time.monotonic()))
    if not ready:
        return b""
    try:
        return os.read(master, 4096)
    except OSError as error:
        if error.errno != errno.EIO:
            raise
        return b""


def run_setup_on_a_terminal(
    home: Home,
    *,
    typed: str,
    chats: tuple[Chat, ...],
    owner_writes: tuple[OwnerMessage, ...],
    accepts: str = ACCEPTED_TOKEN,
) -> tuple[SetupRun, str]:
    """Run `sb setup telegram` on a pseudo-terminal and type `typed` once the terminal stops echoing.

    Returns the run and everything the terminal showed. A setup that never turns echo off gets the token
    typed after ECHO_OFF_WAIT_SECONDS, so the echo lands in the transcript.
    """
    command, outcome_path = _scenario(
        home, Telegram(accepts=accepts, chats=chats, owner_writes=owner_writes)
    )
    master, terminal = pty.openpty()
    process = subprocess.Popen(
        command,
        cwd=home.root,
        env=home.env(),
        stdin=terminal,
        stdout=terminal,
        stderr=terminal,
        start_new_session=True,
        preexec_fn=_take_controlling_terminal,
    )
    transcript = bytearray()
    try:
        echo_deadline = time.monotonic() + ECHO_OFF_WAIT_SECONDS
        while termios.tcgetattr(terminal)[3] & termios.ECHO and time.monotonic() < echo_deadline:
            transcript += _read_terminal(master, echo_deadline)
        os.write(master, typed.encode() + b"\n")
        os.close(terminal)
        terminal = -1
        deadline = time.monotonic() + COMMAND_TIMEOUT_SECONDS
        while chunk := _read_terminal(master, deadline):
            transcript += chunk
        exit_code = process.wait(timeout=COMMAND_TIMEOUT_SECONDS)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if terminal >= 0:
            os.close(terminal)
        os.close(master)
    shown = transcript.decode(errors="replace")
    return _read_outcome(outcome_path, exit_code, shown, shown), shown


def hold_poller_lock(home: Home) -> subprocess.Popen[str]:
    """Start a process that holds the single-poller lock until `release_poller_lock`."""
    holder = subprocess.Popen(
        [sys.executable, "-P", "-c", HOLDER],
        cwd=home.root,
        env=home.env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    held = holder.stdout.readline().strip() if holder.stdout else ""
    if held != "True":
        release_poller_lock(holder)
        raise AssertionError(f"arrange step: the holder did not take the poller lock: {held!r}")
    return holder


def release_poller_lock(holder: subprocess.Popen[str]) -> None:
    holder.communicate(input="\n", timeout=COMMAND_TIMEOUT_SECONDS)


def switchboard_dir(home: Home) -> Path:
    return home.root / ".switchboard"


def telegram_config(home: Home) -> dict:
    """The `[telegram]` table of $HOME/.switchboard/config.toml."""
    text = (switchboard_dir(home) / "config.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)["telegram"]


def config_text(home: Home) -> str:
    return (switchboard_dir(home) / "config.toml").read_text(encoding="utf-8")


def secrets_lines(home: Home) -> list[str]:
    return (switchboard_dir(home) / "secrets.env").read_text(encoding="utf-8").splitlines()


def secrets_mode(home: Home) -> int:
    return stat.S_IMODE((switchboard_dir(home) / "secrets.env").stat().st_mode)


def setup_files_present(home: Home) -> list[str]:
    """Which of the two files setup writes exist."""
    return sorted(
        name for name in ("config.toml", "secrets.env") if (switchboard_dir(home) / name).exists()
    )


def repo_topic_ids(home: Home) -> list[tuple[str, int | None]]:
    return home.rows("SELECT name, topic_id FROM repos ORDER BY name")


def harness_topic_ids(home: Home) -> list[int]:
    return [int(value) for (value,) in home.rows("SELECT value FROM kv WHERE key = 'harness_topic_id'")]
