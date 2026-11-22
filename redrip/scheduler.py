"""Daily schedule.

Windows: a Task Scheduler task (driven through PowerShell). Linux: a systemd user timer
(~/.config/systemd/user/red-rip.timer), which every KDE Plasma distro has.

Either way it runs this app with --headless as the current user while that user is
logged in, and a run missed because the PC was off or asleep happens as soon as
possible afterwards ("StartWhenAvailable" / systemd "Persistent=true").
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .oscompat import IS_WINDOWS, appimage_path, xdg_config_home

TASK_NAME = "Red Rip daily download"
# Earlier names (replaced automatically): the task points at the old .exe / gets renamed
OLD_TASK_NAMES = ["Red-Rip daily download", "ytdl-sub-win-gui daily download", "ytdl-sub-gui daily download"]
CREATE_NO_WINDOW = 0x08000000


UNIT = "red-rip"  # systemd unit names: red-rip.service / red-rip.timer


def is_supported() -> bool:
    return IS_WINDOWS or (sys.platform.startswith("linux") and shutil.which("systemctl") is not None)


def backend_name() -> str:
    return "Windows Task Scheduler" if IS_WINDOWS else "systemd user timer"


def headless_command() -> tuple[str, str, str]:
    """(executable, arguments, working_dir) that launch a headless run without a console."""
    if (app := appimage_path()) is not None:
        # AppImage: sys.executable is inside a temporary mount; schedule the .AppImage file
        return str(app), "--headless", str(app.parent)
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


def _win_install(time_hhmm: str) -> None:
    exe, args, cwd = headless_command()
    script = f"""
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute {_ps_quote(exe)} -Argument {_ps_quote(args)} -WorkingDirectory {_ps_quote(cwd)}
$trigger = New-ScheduledTaskTrigger -Daily -At {_ps_quote(time_hhmm)}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RunOnlyIfNetworkAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12)
Register-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} -Action $action -Trigger $trigger `
    -Settings $settings -Description 'Red Rip: downloads new videos for your channels.' -Force | Out-Null
{_remove_tasks_script(OLD_TASK_NAMES)}
"""
    result = _powershell(script)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Register-ScheduledTask failed")


def _win_uninstall() -> None:
    result = _powershell(_remove_tasks_script([TASK_NAME, *OLD_TASK_NAMES]))
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Unregister-ScheduledTask failed")


def _win_status() -> str:
    """One-line description of the task's state for the UI."""
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


def _win_run_now() -> None:
    result = _powershell(f"Start-ScheduledTask -TaskName {_ps_quote(TASK_NAME)}")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Start-ScheduledTask failed")


def _win_migrate_old_task(schedule_enabled: bool, time_hhmm: str) -> str | None:
    """Replace a scheduled task left over from the app's old name (it points at the old
    .exe). Returns a message if something was migrated."""
    check = " -or ".join(
        f"(Get-ScheduledTask -TaskName {_ps_quote(n)} -ErrorAction SilentlyContinue)" for n in OLD_TASK_NAMES)
    result = _powershell(f"if ({check}) {{ 'yes' }}")
    if result.stdout.strip() != "yes":
        return None
    if schedule_enabled:
        _win_install(time_hhmm)  # registers the new task and removes the old one
        return "Updated the daily schedule to the app's new name."
    _powershell(_remove_tasks_script(OLD_TASK_NAMES))
    return "Removed a scheduled task from the app's old name."


# ------------------------------------------------------------------ Linux: systemd user timer
def _unit_dir() -> Path:
    return xdg_config_home() / "systemd" / "user"


def _systemd_quote(arg: str) -> str:
    """Quote one ExecStart argument (spaces, quotes, backslashes; % is a specifier)."""
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'"{escaped}"'


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def unit_files(time_hhmm: str) -> tuple[str, str]:
    exe, args, cwd = headless_command()
    exec_start = " ".join([_systemd_quote(exe), *[_systemd_quote(a) for a in args.split()]])
    service = (
        "[Unit]\n"
        "Description=Red Rip: download new videos for your channels\n"
        "\n[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={exec_start}\n"
        f"WorkingDirectory={cwd.replace('%', '%%')}\n"  # rest of the line is the path; no quoting
        "TimeoutStartSec=12h\n"   # like the Windows task's 12 hour limit
        "Nice=10\n"
    )
    timer = (
        "[Unit]\n"
        "Description=Red Rip daily download\n"
        "\n[Timer]\n"
        f"OnCalendar=*-*-* {time_hhmm}:00\n"
        "Persistent=true\n"        # run a missed run as soon as possible (PC was off/asleep)
        "\n[Install]\n"
        "WantedBy=timers.target\n"
    )
    return service, timer


def _linux_install(time_hhmm: str) -> None:
    d = _unit_dir()
    d.mkdir(parents=True, exist_ok=True)
    service, timer = unit_files(time_hhmm)
    (d / f"{UNIT}.service").write_text(service, encoding="utf-8")
    (d / f"{UNIT}.timer").write_text(timer, encoding="utf-8")
    for args in (("daemon-reload",), ("enable", "--now", f"{UNIT}.timer"), ("restart", f"{UNIT}.timer")):
        r = _systemctl(*args)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or f"systemctl --user {' '.join(args)} failed")


def _linux_uninstall() -> None:
    _systemctl("disable", "--now", f"{UNIT}.timer")
    for ext in ("timer", "service"):
        try:
            (_unit_dir() / f"{UNIT}.{ext}").unlink()
        except FileNotFoundError:
            pass
    _systemctl("daemon-reload")


def _linux_status() -> str:
    if not (_unit_dir() / f"{UNIT}.timer").exists():
        return "Not scheduled"
    r = _systemctl("show", f"{UNIT}.timer", "-p", "ActiveState", "-p", "NextElapseUSecRealtime",
                   "-p", "LastTriggerUSec")
    props = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
    res = _systemctl("show", f"{UNIT}.service", "-p", "Result")
    result = dict(line.split("=", 1) for line in res.stdout.splitlines() if "=" in line).get("Result", "")
    nxt = props.get("NextElapseUSecRealtime") or "n/a"
    last = props.get("LastTriggerUSec") or ""
    last = "never" if last in ("", "n/a", "0") else f"{last} (result {result or '?'})"
    return f"State: {props.get('ActiveState', 'unknown')}   Next run: {nxt}   Last run: {last}"


def _linux_run_now() -> None:
    r = _systemctl("start", "--no-block", f"{UNIT}.service")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "systemctl --user start failed")


# ------------------------------------------------------------------ public API
def install(time_hhmm: str) -> None:
    _win_install(time_hhmm) if IS_WINDOWS else _linux_install(time_hhmm)


def uninstall() -> None:
    _win_uninstall() if IS_WINDOWS else _linux_uninstall()


def status() -> str:
    """One-line description of the schedule's state for the UI."""
    if not is_supported():
        return "Scheduling needs Windows, or Linux with systemd."
    return _win_status() if IS_WINDOWS else _linux_status()


def run_now() -> None:
    _win_run_now() if IS_WINDOWS else _linux_run_now()


def migrate_old_task(schedule_enabled: bool, time_hhmm: str) -> str | None:
    """Windows only: replace tasks left over from the app's earlier names."""
    return _win_migrate_old_task(schedule_enabled, time_hhmm) if IS_WINDOWS else None
