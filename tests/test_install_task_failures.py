"""`sb install-task` fails with a one-line message starting `sb install-task:` and reports no
registration when powershell.exe is missing, when PowerShell exits non-zero, or when no `sb-inbox`
executable is on PATH.
"""

import subprocess
import unittest

from tests.sb_harness import SbTestCase
from tests.windows_task import (
    install_inbox,
    install_powershell,
    install_task,
    registration_scripts,
    windows_env,
)

PREFIX = "sb install-task:"
REGISTERED = "registered task sb-inbox"

# (case, exit code, what PowerShell writes on stdout, what it writes on stderr, the output line)
POWERSHELL_FAILURES = (
    (
        "exit 1 with the error on stderr",
        1,
        "",
        "Register-ScheduledTask : Access is denied.\n",
        "Register-ScheduledTask : Access is denied.",
    ),
    (
        "exit 255 with the error on stdout",
        255,
        "The term 'New-ScheduledTaskTrigger' is not recognized\n",
        "",
        "The term 'New-ScheduledTaskTrigger' is not recognized",
    ),
)


class MissingPowershellTest(SbTestCase):
    def setUp(self) -> None:
        self.home = self.make_home()
        inbox = install_inbox(self.home)
        self.result = install_task(self.home, windows_env(inbox.parent))

    def test_install_without_powershell_exits_non_zero(self) -> None:
        self.assertNotEqual(self.result.returncode, 0, self.result.stderr)

    def test_install_without_powershell_prints_one_line_naming_powershell(self) -> None:
        lines = self.result.stderr.splitlines()

        self.assertEqual(len(lines), 1, self.result.stderr)
        self.assertTrue(lines[0].startswith(PREFIX), lines[0])
        self.assertIn("powershell.exe", lines[0])

    def test_install_without_powershell_reports_no_registration(self) -> None:
        self.assertNotIn(REGISTERED, self.result.stdout)


class PowershellFailureTest(SbTestCase):
    def failed_install(
        self, exit_code: int, stdout: str, stderr: str
    ) -> subprocess.CompletedProcess[str]:
        home = self.make_home()
        powershell = install_powershell(home, exit_code=exit_code, stdout=stdout, stderr=stderr)
        inbox = install_inbox(home)
        return install_task(home, windows_env(powershell, inbox.parent))

    def test_failed_registration_exits_non_zero(self) -> None:
        for case, exit_code, stdout, stderr, _ in POWERSHELL_FAILURES:
            with self.subTest(case):
                result = self.failed_install(exit_code, stdout, stderr)

                self.assertNotEqual(result.returncode, 0, result.stderr)

    def test_failed_registration_names_powershells_output(self) -> None:
        for case, exit_code, stdout, stderr, output_line in POWERSHELL_FAILURES:
            with self.subTest(case):
                result = self.failed_install(exit_code, stdout, stderr)

                self.assertTrue(result.stderr.startswith(PREFIX), result.stderr)
                self.assertIn(output_line, result.stderr)

    def test_failed_registration_reports_no_registration(self) -> None:
        for case, exit_code, stdout, stderr, _ in POWERSHELL_FAILURES:
            with self.subTest(case):
                result = self.failed_install(exit_code, stdout, stderr)

                self.assertNotIn(REGISTERED, result.stdout)


class MissingInboxTest(SbTestCase):
    def setUp(self) -> None:
        self.home = self.make_home()
        powershell = install_powershell(self.home)
        self.result = install_task(self.home, windows_env(powershell))

    def test_install_without_sb_inbox_exits_non_zero(self) -> None:
        self.assertNotEqual(self.result.returncode, 0, self.result.stderr)

    def test_install_without_sb_inbox_prints_one_line(self) -> None:
        lines = self.result.stderr.splitlines()

        self.assertEqual(len(lines), 1, self.result.stderr)
        self.assertTrue(lines[0].startswith(PREFIX), lines[0])

    def test_install_without_sb_inbox_registers_nothing(self) -> None:
        self.assertEqual(registration_scripts(self.home), [])


if __name__ == "__main__":
    unittest.main()
