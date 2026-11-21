"""Persistent app state: settings + subscriptions, stored as JSON in the app data dir."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "Red-Rip"
OLD_APP_NAMES = ["ytdl-sub-win-gui", "ytdl-sub-gui"]  # earlier names of this app, newest first

QUALITY_PRESETS = [
    "Max Video Quality",
    "Max 2160p",
    "Max 1440p",
    "Max 1080p",
    "Max 720p",
    "Max 480p",
]

COOKIE_BROWSERS = {
    "": "Don't use browser cookies",
    "firefox": "Firefox (recommended)",
    "chrome": "Chrome (must be fully closed; may fail on newer versions)",
    "edge": "Edge (must be fully closed; may fail on newer versions)",
    "brave": "Brave (must be fully closed)",
}

CONTENT_RATINGS = ["TV-Y", "TV-Y7", "TV-G", "TV-PG", "TV-14", "TV-MA"]

# mode values
MODE_ALL = "all"                    # archive the whole channel, keep everything
MODE_RECENT_ARCHIVE = "recent_archive"  # only fetch videos newer than N days, never delete
MODE_RECENT = "recent"              # only keep videos newer than N days (deletes older)

MODES = {
    MODE_ALL: "Everything (full channel archive, in batches)",
    MODE_RECENT_ARCHIVE: "Only new videos (last N days, keep forever)",
    MODE_RECENT: "Rolling window (last N days, delete older)",
}

ARCHIVE_ORDERS = {
    "newest": "Newest first, working backwards",
    "oldest": "Oldest first, working forwards",
}

DATE_SOURCES = {
    "upload": "YouTube upload date",
    "title": "Date in the video title (e.g. \"[November 15th 2026]\"), else upload date",
}

METADATA_MODES = {
    "nfo": ".nfo file next to each video (fastest)",
    "both": ".nfo file + tags inside the video (one extra rewrite of each file)",
    "embedded": "Only tags inside the video file (no per-episode .nfo)",
}

FILE_NAMINGS = {
    "numbered": "s202202.e1401 - Original Title",
    "date_title": "2022-02-14 - Original Title   (needs .nfo metadata)",
}
# A plain "Original Title" option was removed: Jellyfin's file-name parser turns titles
# like "... November 15th 2026 WEEKLY STREAM" into season 20 / episode 26, and a season
# parsed from the file name overrides both the Season folder and embedded tags.

SEASON_ORDERINGS = {
    "year": "Season = year, episode = month+day  (S2024E0317)",
    "year_month": "Season = year+month, episode = day  (S202403E17)",
}


_APP_DIR: Path | None = None


def install_dir() -> Path:
    """Folder containing the .exe (packaged) or the project root (running from source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _legacy_dir(name: str = APP_NAME) -> Path:
    """%APPDATA%\\<name>: where non-portable versions stored everything (and the fallback now)."""
    base = os.environ.get("APPDATA") if sys.platform == "win32" else None
    return (Path(base) if base else Path.home() / ".config") / name


def _existing_legacy_dir() -> Path | None:
    """Newest-named %APPDATA% folder that has settings, if any (also under the app's old name)."""
    for name in [APP_NAME, *OLD_APP_NAMES]:
        if (_legacy_dir(name) / "state.json").exists():
            return _legacy_dir(name)
    return None


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _migrate_legacy(portable: Path) -> None:
    """One-time copy of settings + downloaded tools from %APPDATA% into the portable folder."""
    legacy = _existing_legacy_dir()
    if legacy is None or (portable / "state.json").exists() or legacy.resolve() == portable.resolve():
        return
    import shutil
    if (legacy / "bin").is_dir():
        shutil.copytree(legacy / "bin", portable / "bin", dirs_exist_ok=True)
    data = json.loads((legacy / "state.json").read_text(encoding="utf-8"))
    # Re-point tool paths that lived in the old folder at their copies in the new one.
    for key, value in list(data.get("settings", {}).items()):
        if not isinstance(value, str) or not value:
            continue
        try:
            rel = Path(value).relative_to(legacy)  # case-insensitive on Windows
        except ValueError:
            continue
        if (portable / rel).exists():
            data["settings"][key] = str(portable / rel)
    (portable / "state.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (portable / "MIGRATED_FROM.txt").write_text(
        f"Settings and tools were copied from {legacy}\n"
        "That folder is no longer used and can be deleted.\n", encoding="utf-8")


def app_dir() -> Path:
    """Portable data folder: <app folder>\\data. Falls back to %APPDATA% if not writable."""
    global _APP_DIR
    if _APP_DIR is None:
        portable = install_dir() / "data"
        if _is_writable(portable):
            try:
                _migrate_legacy(portable)
            except Exception:
                pass  # migration is best effort; never block startup
            _APP_DIR = portable
        else:
            # Not writable: use %APPDATA% (keeping an existing folder from the old app name)
            _APP_DIR = _existing_legacy_dir() or _legacy_dir()
            _APP_DIR.mkdir(parents=True, exist_ok=True)
    return _APP_DIR


def logs_dir() -> Path:
    path = app_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bin_dir() -> Path:
    path = app_dir() / "bin"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Subscription:
    name: str
    urls: list[str]
    enabled: bool = True
    genre: str = "YouTube"
    content_rating: str = "TV-14"
    mode: str = MODE_RECENT_ARCHIVE
    recent_days: int = 14
    recent_max_files: int = 0  # 0 = unlimited (only used by MODE_RECENT)
    season_ordering: str = "year"
    quality: str = ""  # "" = use global default
    videos_only: bool = True  # use the channel's /videos tab: skips Shorts and livestreams
    batch_size: int = 5  # MODE_ALL: videos fetched+downloaded per batch (min 2, yt-dlp quirk)
    archive_order: str = "newest"  # MODE_ALL: "newest" (work backwards) or "oldest" first
    date_source: str = "upload"    # "upload" date, or "title": parse the air date from the title
    file_naming: str = "numbered"  # see FILE_NAMINGS
    metadata_mode: str = "nfo"     # see METADATA_MODES
    same_day_suffix: bool = True   # episode 111501 (unique per day) vs 1115

    @classmethod
    def from_dict(cls, d: dict) -> "Subscription":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        sub = cls(**known)
        if sub.file_naming not in FILE_NAMINGS:  # e.g. the removed "title" option
            sub.file_naming = "date_title"
        return sub

    def effective_file_naming(self) -> str:
        """Jellyfin re-parses the file name after reading embedded tags, and a date-named
        file is treated as a date-based episode, which clears the episode number. With
        no .nfo to restore it, only numbered file names keep season/episode intact."""
        return "numbered" if self.metadata_mode == "embedded" else self.file_naming


@dataclass
class Settings:
    ytdlsub_path: str = ""
    ffmpeg_path: str = ""
    ffprobe_path: str = ""
    deno_path: str = ""          # JS runtime yt-dlp needs for YouTube
    ytdlp_path: str = ""         # yt-dlp.exe, used by the Quick download tab
    quick_folder: str = ""       # Quick download destination; blank = the user's Downloads folder
    quick_quality: str = "best"
    library_dir: str = ""        # Jellyfin "Shows" library folder
    working_dir: str = ""        # temp download dir; blank = inside app dir
    quality: str = "Max 1080p"
    cookies_file: str = ""
    cookies_browser: str = ""    # read YouTube cookies straight from this browser (see COOKIE_BROWSERS)
    throttle_protection: bool = True
    max_downloads_per_run: int = 0  # 0 = unlimited
    auto_update_ytdlsub: bool = True  # YouTube changes often; stale yt-dlp breaks downloads
    embed_chapters: bool = True  # chapter markers; costs one extra rewrite of videos that have chapters
    keep_info_json: bool = False  # <video>.info.json next to each video (raw YouTube metadata)
    # When YouTube blocks/rate-limits ("confirm you're not a bot", HTTP 429), stop instead of
    # skipping ahead to older videos, wait, then resume where it stopped.
    pause_on_block: bool = True
    block_cooldown_min: int = 60
    block_max_retries: int = 3
    schedule_enabled: bool = False
    schedule_time: str = "03:00"
    jellyfin_refresh: bool = False
    jellyfin_url: str = "http://localhost:8096"
    jellyfin_api_key: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class AppState:
    settings: Settings = field(default_factory=Settings)
    subscriptions: list[Subscription] = field(default_factory=list)

    @staticmethod
    def path() -> Path:
        return app_dir() / "state.json"

    @classmethod
    def load(cls) -> "AppState":
        p = cls.path()
        if not p.exists():
            state = cls()
            state.apply_detected_defaults()
            return state
        data = json.loads(p.read_text(encoding="utf-8"))
        state = cls(
            settings=Settings.from_dict(data.get("settings", {})),
            subscriptions=[Subscription.from_dict(s) for s in data.get("subscriptions", [])],
        )
        state.apply_detected_defaults()
        return state

    def save(self) -> None:
        data = {
            "settings": asdict(self.settings),
            "subscriptions": [asdict(s) for s in self.subscriptions],
        }
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path())

    def apply_detected_defaults(self) -> None:
        """Fill in tool paths if the bundled downloader put them in bin_dir()."""
        exe = ".exe" if sys.platform == "win32" else ""
        s = self.settings
        for attr, name in (("ytdlsub_path", "ytdl-sub"), ("ffmpeg_path", "ffmpeg"),
                           ("ffprobe_path", "ffprobe"), ("deno_path", "deno"),
                           ("ytdlp_path", "yt-dlp")):
            if not getattr(s, attr):
                candidate = bin_dir() / f"{name}{exe}"
                if candidate.exists():
                    setattr(s, attr, str(candidate))
