"""Re-running `sb install-task` updates the one task in place: it succeeds again and registers the
same definition, replacing the task of the same name rather than adding a second one.

No Windows, and so no Task Scheduler, is reachable from this suite, so the task list cannot be
counted. The registration script the command hands to powershell.exe stands in for it: "exactly
one task" is read as a second run registering a script identical to the first, and as the script
replacing any task of the same name instead of failing on it.
"""

import re
import unittest

from tests.sb_harness import SbTestCase
from tests.windows_task import (
    install_inbox,
    install_powershell,
    registration_scripts,
    registration_text,
    windows_env,
)


class ReinstallTest(SbTestCase):
    def setUp(self) -> None:
        self.home = self.make_home()
        powershell = install_powershell(self.home)
        inbox = install_inbox(self.home)
        self.env = windows_env(powershell, inbox.parent)
        self.home.sb_ok("install-task", cwd=self.home.root, env=self.env)
        self.first = registration_scripts(self.home)
        if not self.first:
            raise AssertionError("arrange step `sb install-task` exited 0 but registered nothing")

    def test_second_install_exits_0_reporting_the_task(self) -> None:
        result = self.home.sb("install-task", cwd=self.home.root, env=self.env)

        self.assertEqual(
            (result.returncode, result.stdout.splitlines()),
            (0, ["registered task sb-inbox"]),
            result.stderr,
        )

    def test_second_install_registers_the_same_definition(self) -> None:
        self.home.sb("install-task", cwd=self.home.root, env=self.env)

        self.assertEqual(registration_scripts(self.home)[len(self.first):], self.first)


class ReplaceInPlaceTest(SbTestCase):
    def test_registration_replaces_a_task_of_the_same_name(self) -> None:
        home = self.make_home()
        powershell = install_powershell(home)
        inbox = install_inbox(home)

        home.sb("install-task", cwd=home.root, env=windows_env(powershell, inbox.parent))

        self.assertRegex(
            registration_text(home),
            re.compile(r"-Force\b|Unregister-ScheduledTask|Set-ScheduledTask", re.IGNORECASE),
        )


if __name__ == "__main__":
    unittest.main()
