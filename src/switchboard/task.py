import base64
import subprocess
import sys
from pathlib import Path

TASK_NAME = "sb-inbox"

# Run by Windows PowerShell 5.1 (powershell.exe, the one interop can reach). $distro, $wslUser and
# $inbox are defined ahead of it by definition_script.
DEFINITION = r"""
$ErrorActionPreference = 'Stop'
$owner = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute 'wslg.exe' -Argument ('-d "{0}" -u "{1}" -- "{2}"' -f $distro, $wslUser, $inbox)
# The repeat trigger starts at a fixed past time so that running install again exports the same
# definition; a start of "now" would change the exported StartBoundary on every run.
$triggers = @(
    (New-ScheduledTaskTrigger -AtLogOn -User $owner),
    (New-CimInstance -ClassName MSFT_TaskSessionStateChangeTrigger -Namespace Root/Microsoft/Windows/TaskScheduler -ClientOnly -Property @{ StateChange = 8; UserId = $owner }),
    (New-ScheduledTaskTrigger -Once -At ([datetime]'2000-01-01T00:00:00') -RepetitionInterval (New-TimeSpan -Minutes 10))
)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
$principal = New-ScheduledTaskPrincipal -UserId $owner -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Force | Out-Null
"""


def quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def register(distro: str, wsl_user: str, inbox: Path) -> None:
    variables = "".join(
        f"${name} = {quote(value)}\n"
        for name, value in (
            ("taskName", TASK_NAME),
            ("distro", distro),
            ("wslUser", wsl_user),
            ("inbox", str(inbox)),
        )
    )
    # -EncodedCommand carries non-ASCII names intact; stdin would go through the OEM code page.
    encoded = base64.b64encode((variables + DEFINITION).encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60,
        )
    except FileNotFoundError:
        sys.exit("sb install-task: powershell.exe not found; run this inside WSL")
    if result.returncode != 0:
        sys.exit(f"sb install-task: PowerShell failed: {(result.stderr or result.stdout).strip()}")
