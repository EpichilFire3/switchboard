"""Re-running `sb install-task` updates the one task in place: it succeeds again and registers the
same definition, replacing the task of the same name rather than adding a second one.

The task list is not observable without Windows, so "exactly one task" is read from the
registration script (see the ledger's rulings).
"""

import re
import unittest

from tests.sb_harness import SbTestCase
from tests.windows_task import (
    install_inbox,
    install_powershell,
    install_task,
    install_task_ok,
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
        install_task_ok(self.home, self.env)
        self.first = registration_scripts(self.home)
        if not self.first:
            raise AssertionError("arrange step `sb install-task` exited 0 but registered nothing")

    def test_second_install_exits_0_reporting_the_task(self) -> None:
        result = install_task(self.home, self.env)

        self.assertEqual(
            (result.returncode, result.stdout.splitlines()),
            (0, ["registered task sb-inbox"]),
            result.stderr,
        )

    def test_second_install_registers_the_same_definition(self) -> None:
        install_task(self.home, self.env)

        self.assertEqual(registration_scripts(self.home)[len(self.first):], self.first)


class ReplaceInPlaceTest(SbTestCase):
    def test_registration_replaces_a_task_of_the_same_name(self) -> None:
        home = self.make_home()
        powershell = install_powershell(home)
        inbox = install_inbox(home)

        install_task(home, windows_env(powershell, inbox.parent))

        self.assertRegex(
            registration_text(home),
            re.compile(r"-Force\b|Unregister-ScheduledTask|Set-ScheduledTask", re.IGNORECASE),
        )


if __name__ == "__main__":
    unittest.main()
