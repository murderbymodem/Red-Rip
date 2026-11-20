"""Running ytdl-sub: command building, headless (scheduled) runs, Jellyfin refresh."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import configgen
from .models import MODE_ALL, AppState, app_dir, bin_dir, logs_dir

CREATE_NO_WINDOW = 0x08000000  # don't flash a console window from the scheduled task

# Safety cap on back-to-back batches in one run (5 videos x 400 = 2000 videos).
MAX_BATCHES = 400

# YouTube refusing service (as opposed to one video being unavailable). yt-dlp keeps going
# with older videos after these, so batches would skip ahead; the app stops and waits instead.
_BLOCK_RE = re.compile(
    r"confirm you.{0,3}re not a bot|rate-limited|rate limited|HTTP Error 429|Too Many Requests",
    re.IGNORECASE,
)
_BEGIN_RE = re.compile(r"Beginning subscription \S+ for (.+?)\s*$")
_NO_CHANGE_RE = re.compile(r"^No files changed for (.+?)\s*$")


class BatchTracker:
    """Reads ytdl-sub output to find 'Everything' channels that stopped at their
    batch limit (MaxDownloadsReached) and therefore have more videos waiting."""

    def __init__(self):
        self.current: str | None = None
        self.truncated: set[str] = set()
        self.unchanged: set[str] = set()
        self.blocked: str | None = None  # first YouTube block/rate-limit error line seen
        self._partial = ""

    def feed(self, text: str) -> None:
        self._partial += text
        *lines, self._partial = self._partial.split("\n")
        for line in lines:
            self._line(line)

    def _line(self, line: str) -> None:
        if self.blocked is None and "ERROR" in line and _BLOCK_RE.search(line):
            self.blocked = line.strip()
        if m := _BEGIN_RE.search(line):
            self.current = m.group(1)
        elif "MaxDownloadsReached" in line and self.current:
            self.truncated.add(self.current)
        elif m := _NO_CHANGE_RE.match(line.strip()):
            self.unchanged.add(m.group(1))

    def next_batch(self, state: AppState) -> list[str]:
        """Channels to run again. A channel that hit the limit but changed no files
        is not repeated (avoids looping forever on videos that keep failing)."""
        self.feed("\n")
        all_mode = {s.name for s in state.subscriptions if s.enabled and s.mode == MODE_ALL}
        return sorted((self.truncated - self.unchanged) & all_mode)


def child_env() -> dict:
    """Environment for ytdl-sub: bin folder on PATH so yt-dlp finds deno/ffmpeg."""
    env = dict(os.environ)
    env["PATH"] = str(bin_dir()) + os.pathsep + env.get("PATH", "")
    # ytdl-sub.exe is Python: make it write UTF-8 so titles/messages aren't garbled (e.g. "you\ufffdre")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def kill_tree(pid: int) -> None:
    """ytdl-sub.exe is a PyInstaller one-file exe: a launcher process plus the real
    worker. Killing only the launcher leaves the worker running, so kill the tree."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, creationflags=CREATE_NO_WINDOW)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def build_command(state: AppState, dry_run: bool = False, match: list[str] | None = None) -> list[str]:
    config_path, subs_path = configgen.write_files(state)
    cmd = [state.settings.ytdlsub_path, "--config", str(config_path), "--suppress-colors"]
    if dry_run:
        cmd.append("--dry-run")
    cmd += ["sub", str(subs_path)]
    if match:
        cmd += ["--match", *match]
    return cmd


def new_log_path(prefix: str) -> Path:
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return logs_dir() / f"{prefix}_{stamp}.log"


def prune_logs(keep: int = 60) -> None:
    logs = sorted(logs_dir().glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in logs[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def refresh_jellyfin(url: str, api_key: str, timeout: float = 15) -> str:
    """Ask Jellyfin to scan all libraries. Returns a human-readable result."""
    req = urllib.request.Request(
        url.rstrip("/") + "/Library/Refresh",
        method="POST",
        data=b"",
        headers={
            "Authorization": f'MediaBrowser Token="{api_key}"',
            "X-Emby-Token": api_key,  # older servers
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return f"Jellyfin library refresh requested (HTTP {resp.status})."


def test_jellyfin(url: str, api_key: str, timeout: float = 10) -> str:
    req = urllib.request.Request(
        url.rstrip("/") + "/System/Info",
        headers={"Authorization": f'MediaBrowser Token="{api_key}"', "X-Emby-Token": api_key},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        info = json.loads(resp.read().decode("utf-8"))
    return f"Connected to {info.get('ServerName', 'Jellyfin')} (version {info.get('Version', '?')})."


def run_headless() -> int:
    """Entry point for the scheduled task. Never shows UI; logs to a file."""
    state = AppState.load()
    log_path = new_log_path("scheduled")
    prune_logs()
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        def say(msg: str) -> None:
            log.write(f"[{dt.datetime.now():%H:%M:%S}] {msg}\n")
            log.flush()

        if state.settings.auto_update_ytdlsub:
            try:
                from . import tools
                msg = tools.update_ytdlsub_if_stale(state.settings, max_age_days=7)
                if msg:
                    say(msg)
                    state.save()
            except Exception as exc:  # update failure must not block the run
                say(f"ytdl-sub auto-update failed (continuing with current version): {exc}")
        if sys.platform == "win32" and not state.settings.deno_path:
            try:
                from . import tools
                state.settings.deno_path = str(tools.download_deno())
                state.save()
                say("Installed deno (JavaScript runtime needed by yt-dlp for YouTube).")
            except Exception as exc:
                say(f"Could not install deno (continuing without it): {exc}")

        errors = configgen.validate(state)
        if errors:
            for e in errors:
                say(f"CONFIG ERROR: {e}")
            return 2

        flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
        match: list[str] | None = None
        code = 0
        s = state.settings
        blocks_in_a_row = 0
        batch = 0
        while batch < MAX_BATCHES:
            batch += 1
            cmd = build_command(state, match=match)
            if batch > 1:
                say(f"--- Batch {batch}: {', '.join(match) if match else 'all channels'} ---")
            say("Running: " + subprocess.list2cmdline(cmd))
            tracker = BatchTracker()
            proc = subprocess.Popen(
                cmd, cwd=str(app_dir()), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, creationflags=flags, env=child_env(),
            )
            assert proc.stdout is not None
            stopped_for_block = False
            for raw in proc.stdout:
                text = raw.decode("utf-8", errors="replace")
                tracker.feed(text)
                log.write(text)
                log.flush()
                if tracker.blocked and s.pause_on_block and not stopped_for_block:
                    stopped_for_block = True
                    say(f"YouTube is blocking requests: {tracker.blocked}")
                    say("Stopping now so ytdl-sub doesn't skip ahead to older videos.")
                    kill_tree(proc.pid)
            code = proc.wait()
            say(f"ytdl-sub exited with code {code}")
            if stopped_for_block:
                blocks_in_a_row += 1
                if blocks_in_a_row > max(0, s.block_max_retries):
                    say(f"Still blocked after {blocks_in_a_row - 1} waits; giving up until the next run.")
                    break
                mins = max(1, s.block_cooldown_min)
                say(f"Waiting {mins} minute{'s' if mins != 1 else ''} before trying again "
                    f"(wait {blocks_in_a_row} of {s.block_max_retries}).")
                time.sleep(mins * 60)
                batch -= 1  # the blocked attempt doesn't count as a batch
                continue    # same channels again; newest-first, so the blocked videos come first
            blocks_in_a_row = 0
            match = tracker.next_batch(state)
            if not match:
                break

        if s.jellyfin_refresh and s.jellyfin_api_key:
            try:
                say(refresh_jellyfin(s.jellyfin_url, s.jellyfin_api_key))
            except Exception as exc:
                say(f"Jellyfin refresh failed: {exc}")
        return code


# --------------------------------------------------------------------------- live progress
# ytdl-sub prints these at its default log level (yt-dlp's percentage lines are debug-only,
# so download progress is measured from the files in the working folder instead).
_PLAYLIST_RE = re.compile(r"\[download\] Downloading playlist: (.+?)\s*$")
_META_RE = re.compile(r"Downloading metadata for (.+?)\s*$")
_ENTRY_RE = re.compile(r"Downloading entry (\d+)/(\d+): (.+?)\s*$")
_ALREADY_RE = re.compile(r"Already downloaded entry \d+/\d+: (.+?)\s*$")
_SLEEP_RE = re.compile(r"Sleeping between (\w+) for ([\d.]+) seconds")

QUEUED, CURRENT, DONE, SKIPPED, FAILED = "queued", "current", "done", "skipped", "failed"


class ProgressTracker:
    """Follows ytdl-sub output to know the batch's videos and which one is being processed."""

    def __init__(self):
        self._partial = ""
        self._reset()

    def _reset(self) -> None:
        """Start of a channel. (Never touches _partial: text already received but not yet
        split into lines must survive, or a line straddling two reads would be lost.)"""
        self.channel = ""
        self.phase = ""            # "", "lookup", "download"
        self.items: list[dict] = []  # {"title", "status"} in download order
        self.current: str | None = None
        self.position = ""         # "2/5" from "Downloading entry 2/5"
        self.stage = ""
        self._playlists: set[str] = set()
        self._streams = 0

    # -- parsing
    def feed(self, text: str) -> None:
        self._partial += text.replace("\r", "\n")
        *lines, self._partial = self._partial.split("\n")
        for line in lines:
            self._line(line)

    def _find(self, title: str) -> dict | None:
        return next((i for i in self.items if i["title"] == title), None)

    def _finish_current(self) -> None:
        item = self._find(self.current) if self.current else None
        if item and item["status"] == CURRENT:
            item["status"] = DONE
        self.current = None

    def _line(self, line: str) -> None:
        if m := _BEGIN_RE.search(line):
            self._finish_current()
            self._reset()
            self.channel, self.phase, self.stage = m.group(1), "lookup", "looking up videos"
        elif m := _PLAYLIST_RE.search(line):
            self._playlists.add(m.group(1))
        elif m := _META_RE.search(line):
            title = m.group(1)
            if self.phase == "lookup" and title not in self._playlists and not self._find(title):
                self.items.append({"title": title, "status": QUEUED})
                self.stage = f"looking up videos ({len(self.items)} found)"
        elif "Beginning downloads for" in line:
            # ytdl-sub downloads a batch in reverse order of its lookup (download_reverse)
            self.items.reverse()
            self.phase, self.stage = "download", "starting downloads"
        elif m := _ENTRY_RE.search(line):
            self._finish_current()
            self.phase = "download"
            self.position, self.current, self._streams = f"{m.group(1)}/{m.group(2)}", m.group(3), 0
            item = self._find(self.current)
            if item is None:
                item = {"title": self.current, "status": QUEUED}
                self.items.append(item)
            item["status"] = CURRENT
            self.stage = "getting video info"
        elif m := _ALREADY_RE.search(line):
            item = self._find(m.group(1))
            if item:
                item["status"] = SKIPPED
        elif "Entry rejected by download match-filter" in line and self.current:
            self._find(self.current)["status"] = SKIPPED
            self.current = None
        elif "[download] Destination:" in line and self.current:
            self._streams += 1
            self.stage = "downloading video" if self._streams == 1 else "downloading audio"
        elif "[Merger] Merging formats" in line and self.current:
            self.stage = "merging video + audio"
        elif "[Metadata] Adding metadata" in line and self.current:
            self.stage = "adding chapters"
        elif m := _SLEEP_RE.search(line):
            self._finish_current()
            self.stage = f"pausing {float(m.group(2)):.0f}s between {m.group(1)} (throttle protection)"
        elif "ERROR:" in line and self.current:
            self._find(self.current)["status"] = FAILED
        elif "Download Summary" in line:
            self.finish()

    def finish(self) -> None:
        self._finish_current()
        self.stage = "finished"

    # -- queries
    def up_next(self) -> list[str]:
        return [i["title"] for i in self.items if i["status"] == QUEUED]


def find_info_json(working_dir: Path, title: str) -> Path | None:
    """The working-folder .info.json of the video with this title (gives its id and sizes)."""
    for p in working_dir.rglob("*.info.json"):
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("title") == title:
                return p
        except (OSError, ValueError):
            continue
    return None


def expected_size(info_json: Path) -> int | None:
    """Total bytes of the formats yt-dlp will download, if YouTube reported them."""
    try:
        info = json.loads(info_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    formats = info.get("requested_formats") or [info]
    sizes = [f.get("filesize") or f.get("filesize_approx") for f in formats]
    return int(sum(sizes)) if sizes and all(sizes) else None


def downloaded_bytes(info_json: Path) -> int:
    """Bytes of this video's media files (finished or partial) in the working folder."""
    vid = info_json.name[: -len(".info.json")]
    total = 0
    for p in info_json.parent.glob(f"{glob_escape(vid)}.*"):
        name = p.name.lower()
        if name.endswith((".json", ".jpg", ".jpeg", ".png", ".webp", ".ytdl")):
            continue
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def glob_escape(s: str) -> str:
    import glob
    return glob.escape(s)
