"""Daily schedule via Windows Task Scheduler (driven through PowerShell).

The task runs this app with --headless as the current user, only while that user
is logged on (no stored password). "StartWhenAvailable" makes Windows run a
missed run (PC was off/asleep at the scheduled time) as soon as it can.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TASK_NAME = "Red-Rip daily download"
OLD_TASK_NAMES = ["ytdl-sub-win-gui daily download", "ytdl-sub-gui daily download"]  # earlier app names
CREATE_NO_WINDOW = 0x08000000


def is_supported() -> bool:
    return sys.platform == "win32"


def headless_command() -> tuple[str, str, str]:
    """(executable, arguments, working_dir) that launch a headless run without a console."""
    if getattr(sys, "frozen", False):  # PyInstaller build: the exe is windowed already
        exe = Path(sys.executable)
        return str(exe), "--headless", str(exe.parent)
    # Running from source: prefer pythonw.exe so no console window appears.
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    project_root = Path(__file__).resolve().parent.parent
    return str(pyw if pyw.exists() else py), "-m redrip --headless", str(project_root)


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _powershell(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", script],
        capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
    )


def _remove_tasks_script(names: list[str]) -> str:
    return "; ".join(
        f"if (Get-ScheduledTask -TaskName {_ps_quote(n)} -ErrorAction SilentlyContinue) "
        f"{{ Unregister-ScheduledTask -TaskName {_ps_quote(n)} -Confirm:$false }}"
        for n in names)


def install(time_hhmm: str) -> None:
    exe, args, cwd = headless_command()
    script = f"""
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute {_ps_quote(exe)} -Argument {_ps_quote(args)} -WorkingDirectory {_ps_quote(cwd)}
$trigger = New-ScheduledTaskTrigger -Daily -At {_ps_quote(time_hhmm)}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RunOnlyIfNetworkAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12)
Register-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} -Action $action -Trigger $trigger `
    -Settings $settings -Description 'Red-Rip: downloads new videos for your channels.' -Force | Out-Null
{_remove_tasks_script(OLD_TASK_NAMES)}
"""
    result = _powershell(script)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Register-ScheduledTask failed")


def uninstall() -> None:
    result = _powershell(_remove_tasks_script([TASK_NAME, *OLD_TASK_NAMES]))
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Unregister-ScheduledTask failed")


def status() -> str:
    """One-line description of the task's state for the UI."""
    if not is_supported():
        return "Scheduling is only available on Windows."
    script = f"""
$t = Get-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} -ErrorAction SilentlyContinue
if (-not $t) {{ 'Not scheduled'; exit }}
$i = $t | Get-ScheduledTaskInfo
$next = if ($i.NextRunTime) {{ $i.NextRunTime.ToString('ddd yyyy-MM-dd HH:mm') }} else {{ 'n/a' }}
$last = if ($i.LastRunTime -and $i.LastRunTime.Year -gt 2000) {{ $i.LastRunTime.ToString('yyyy-MM-dd HH:mm') + ' (result ' + $i.LastTaskResult + ')' }} else {{ 'never' }}
"State: $($t.State)   Next run: $next   Last run: $last"
"""
    result = _powershell(script)
    return (result.stdout.strip() or result.stderr.strip() or "Unknown").splitlines()[0]


def run_now() -> None:
    result = _powershell(f"Start-ScheduledTask -TaskName {_ps_quote(TASK_NAME)}")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Start-ScheduledTask failed")


def migrate_old_task(schedule_enabled: bool, time_hhmm: str) -> str | None:
    """Replace a scheduled task left over from the app's old name (it points at the old
    .exe). Returns a message if something was migrated."""
    if not is_supported():
        return None
    check = " -or ".join(
        f"(Get-ScheduledTask -TaskName {_ps_quote(n)} -ErrorAction SilentlyContinue)" for n in OLD_TASK_NAMES)
    result = _powershell(f"if ({check}) {{ 'yes' }}")
    if result.stdout.strip() != "yes":
        return None
    if schedule_enabled:
        install(time_hhmm)  # registers the new task and removes the old one
        return "Updated the daily schedule to the app's new name."
    _powershell(_remove_tasks_script(OLD_TASK_NAMES))
    return "Removed a scheduled task from the app's old name."
