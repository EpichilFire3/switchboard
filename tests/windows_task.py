"""The Windows side of `sb install-task`, for black-box tests on a machine with no Task Scheduler.

The one external boundary is `powershell.exe`, looked up on PATH. A stand-in executable of that
name is placed first on PATH. It answers only the invocation the command makes,
`powershell.exe -NoProfile -NonInteractive -EncodedCommand <base64 of the UTF-16LE script>`,
appends every argv it receives to a file under HOME, and exits as the test configured it. Any
other invocation is unhandled: it exits 64 and says so.

PATH is replaced entirely by test directories, so the machine's real powershell.exe (WSL appends
the Windows PATH) is never reachable from a test. `sb-inbox` is a stub executable that is never run.
"""

import base64
import json
import os
import sys
from pathlib import Path

from tests.sb_harness import Home

DISTRO = "SbTestDistro"
OWNER = "sbowner"

# What Register-ScheduledTask prints on success when run non-interactively.
REGISTERED_TABLE = (
    "\n"
    "TaskPath                                       TaskName                          State\n"
    "--------                                       --------                          -----\n"
    "\\                                              sb-inbox                          Ready\n"
    "\n"
)


def calls_path(home: Home) -> Path:
    return home.root / "powershell-calls.jsonl"


def install_powershell(
    home: Home, exit_code: int = 0, stdout: str = REGISTERED_TABLE, stderr: str = ""
) -> Path:
    """A directory holding a stand-in powershell.exe; returns the directory for PATH."""
    directory = home.root / "windows-bin"
    directory.mkdir()
    fake = directory / "powershell.exe"
    fake.write_text(
        f"#!{sys.executable} -I\n"
        "import json, sys\n"
        f"CALLS = {str(calls_path(home))!r}\n"
        "argv = sys.argv[1:]\n"
        "with open(CALLS, 'a', encoding='utf-8') as calls:\n"
        "    calls.write(json.dumps(argv) + '\\n')\n"
        "if '-EncodedCommand' not in argv:\n"
        "    sys.stderr.write('fake powershell.exe: unhandled invocation\\n')\n"
        "    sys.exit(64)\n"
        f"sys.stdout.write({stdout!r})\n"
        f"sys.stderr.write({stderr!r})\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return directory


def install_inbox(home: Home, directory_name: str = "inbox-bin") -> Path:
    """A stub `sb-inbox` executable in HOME/<directory_name>; returns its absolute path."""
    directory = home.root / directory_name
    directory.mkdir()
    inbox = directory / "sb-inbox"
    inbox.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    inbox.chmod(0o755)
    return inbox


def windows_env(*path_entries: Path | str) -> dict[str, str]:
    """The environment of a WSL shell whose PATH holds only these entries."""
    return {
        "PATH": os.pathsep.join(str(entry) for entry in path_entries),
        "WSL_DISTRO_NAME": DISTRO,
        "LOGNAME": OWNER,
    }


def recorded_invocations(home: Home) -> list[list[str]]:
    """Every argv the stand-in powershell.exe received, in order."""
    path = calls_path(home)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return [json.loads(line) for line in text.splitlines()]


def registration_scripts(home: Home) -> list[str]:
    """The PowerShell script of each -EncodedCommand invocation, decoded from UTF-16LE base64."""
    return [
        base64.b64decode(argv[argv.index("-EncodedCommand") + 1]).decode("utf-16-le")
        for argv in recorded_invocations(home)
        if "-EncodedCommand" in argv
    ]


def registration_text(home: Home) -> str:
    """All registration scripts the command sent, as one text."""
    return "\n".join(registration_scripts(home))
