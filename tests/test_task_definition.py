"""`sb install-task` registers one Windows task that starts `sb-inbox` through `wslg.exe` by its
absolute path, at logon, on workstation unlock and every 10 minutes, with each listed setting set
explicitly, as the current user without admin rights.

No Task Scheduler is reachable from the test run, so the task's definition is read where it
exists: the registration script the command hands to powershell.exe. Each spec item is asserted
by the ScheduledTasks module's or Task Scheduler's own public name for it (see the ledger's
rulings); every pattern is case-insensitive, as PowerShell is.
"""

import re
import unittest

from tests.sb_harness import SbTestCase
from tests.windows_task import (
    DISTRO,
    OWNER,
    install_inbox,
    install_powershell,
    install_task,
    registration_text,
    windows_env,
)

# (spec item, pattern the registration script must contain)
REQUIRED = (
    ("action launches wslg.exe", r"\bwslg\.exe\b"),
    ("trigger at logon", r"-AtLogOn\b|MSFT_TaskLogonTrigger"),
    ("trigger on workstation unlock: session state change trigger", r"MSFT_TaskSessionStateChangeTrigger"),
    # TASK_SESSION_UNLOCK is 8; 7 is lock.
    ("trigger on workstation unlock: state change is unlock", r"StateChange\W+8\b"),
    (
        "trigger repeats every 10 minutes",
        r"New-TimeSpan\s+-Minutes\s+10\b|FromMinutes\(\s*10\s*\)|\bPT10M\b|\b00:10:00\b",
    ),
    ("runs only when the user is logged on", r"LogonType\W+Interactive"),
    (
        "no execution time limit",
        r"ExecutionTimeLimit\W+(\[(System\.)?TimeSpan\]::Zero|PT0S\b|0\b|00:00:00\b"
        r"|\(New-TimeSpan\)|\(New-TimeSpan\s+-Seconds\s+0\))",
    ),
    (
        "starts on battery",
        r"-AllowStartIfOnBatteries\b(?!:\s*\$false)|DisallowStartIfOnBatteries\W+\$false",
    ),
    (
        "keeps running on battery",
        r"-DontStopIfGoingOnBatteries\b(?!:\s*\$false)|(?<![a-z])StopIfGoingOnBatteries\W+\$false",
    ),
    (
        "starts when available after a missed start",
        r"-StartWhenAvailable\b(?!:\s*\$false)|StartWhenAvailable\W+\$true",
    ),
    ("ignores a new instance while one runs", r"MultipleInstances\W+IgnoreNew\b"),
)

# (rejected option, pattern the registration script must not contain)
ABSENT = (
    ("wsl.exe, which opens a console window", r"\bwsl\.exe\b"),
    ("conhost --headless", r"\bconhost\b"),
    ("VBScript wrapper", r"\bwscript\b|\bcscript\b|\.vbs\b"),
    ("hidden PowerShell", r"WindowStyle\W+Hidden"),
    ("restart-on-failure", r"RestartCount|RestartInterval"),
    ("whether logged on or not (session 0)", r"LogonType\W+(S4U|Password|ServiceAccount)\b"),
    ("admin run level", r"RunLevel\W+Highest\b"),
    ("WSL idle-timeout settings or systemd as the keep-alive", r"instanceIdleTimeout|vmIdleTimeout|\bsystemctl\b"),
)


class TaskDefinitionTest(SbTestCase):
    def setUp(self) -> None:
        self.home = self.make_home()
        powershell = install_powershell(self.home)
        self.inbox = install_inbox(self.home)
        self.result = install_task(self.home, windows_env(powershell, self.inbox.parent))
        self.script = registration_text(self.home)

    def test_install_task_reports_the_registered_task(self) -> None:
        self.assertEqual(
            (self.result.returncode, self.result.stdout.splitlines()),
            (0, ["registered task sb-inbox"]),
            self.result.stderr,
        )

    def test_registration_states_each_listed_trigger_and_setting(self) -> None:
        for item, pattern in REQUIRED:
            with self.subTest(item):
                self.assertRegex(self.script, re.compile(pattern, re.IGNORECASE))

    def test_registration_uses_no_rejected_launcher_or_mode(self) -> None:
        self.assertRegex(self.script, re.compile(r"Register-ScheduledTask", re.IGNORECASE))
        for option, pattern in ABSENT:
            with self.subTest(option):
                self.assertNotRegex(self.script, re.compile(pattern, re.IGNORECASE))

    def test_action_launches_sb_inbox_by_its_absolute_path(self) -> None:
        self.assertIn(str(self.inbox), self.script)

    def test_action_targets_the_current_distro(self) -> None:
        self.assertIn(DISTRO, self.script)

    def test_action_runs_as_the_current_wsl_user(self) -> None:
        self.assertIn(OWNER, self.script)


class RelativePathEntryTest(SbTestCase):
    def test_action_names_sb_inbox_by_absolute_path_when_its_path_entry_is_relative(self) -> None:
        home = self.make_home()
        powershell = install_powershell(home)
        install_inbox(home, "relbin")
        expected = str(home.root / "relbin" / "sb-inbox")

        install_task(home, windows_env(powershell, "relbin"))

        self.assertIn(expected, registration_text(home))


if __name__ == "__main__":
    unittest.main()
