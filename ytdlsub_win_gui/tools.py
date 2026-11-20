"""Downloads ytdl-sub.exe and ffmpeg/ffprobe into the app's bin folder (Windows)."""
from __future__ import annotations

import datetime as dt
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from .models import Settings, bin_dir

YTDLSUB_URL = "https://github.com/jmbannon/ytdl-sub/releases/latest/download/ytdl-sub.exe"
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
DENO_URL = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
FFMPEG_URL = ("https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/"
              "ffmpeg-master-latest-win64-gpl.zip")

Progress = Callable[[str, int, int], None]  # (label, bytes_done, bytes_total)


def _download(url: str, dest: Path, label: str, progress: Progress | None) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "ytdl-sub-win-gui"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(256 * 1024):
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(label, done, total)
    tmp.replace(dest)


def download_ytdlsub(progress: Progress | None = None) -> Path:
    dest = bin_dir() / "ytdl-sub.exe"
    _download(YTDLSUB_URL, dest, "ytdl-sub.exe", progress)
    return dest


def download_ffmpeg(progress: Progress | None = None) -> tuple[Path, Path]:
    out_dir = bin_dir()
    with tempfile.TemporaryDirectory() as td:
        zip_path = Path(td) / "ffmpeg.zip"
        _download(FFMPEG_URL, zip_path, "ffmpeg (~150 MB)", progress)
        if progress:
            progress("Extracting ffmpeg", 0, 0)
        results = {}
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                name = Path(member).name.lower()
                if name in ("ffmpeg.exe", "ffprobe.exe") and "/bin/" in member.replace("\\", "/"):
                    target = out_dir / name
                    with zf.open(member) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    results[name] = target
    if len(results) != 2:
        raise RuntimeError("ffmpeg.exe / ffprobe.exe not found in the downloaded archive")
    return results["ffmpeg.exe"], results["ffprobe.exe"]


def download_deno(progress: Progress | None = None) -> Path:
    """deno is the JavaScript runtime yt-dlp uses to solve YouTube's player challenges."""
    dest = bin_dir() / "deno.exe"
    with tempfile.TemporaryDirectory() as td:
        zip_path = Path(td) / "deno.zip"
        _download(DENO_URL, zip_path, "deno (JavaScript runtime)", progress)
        with zipfile.ZipFile(zip_path) as zf, zf.open("deno.exe") as src, open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return dest


def download_ytdlp(progress: Progress | None = None) -> Path:
    dest = bin_dir() / "yt-dlp.exe"
    _download(YTDLP_URL, dest, "yt-dlp.exe", progress)
    return dest


def install_all(settings: Settings, progress: Progress | None = None) -> None:
    settings.ytdlsub_path = str(download_ytdlsub(progress))
    settings.ytdlp_path = str(download_ytdlp(progress))
    settings.deno_path = str(download_deno(progress))
    ffmpeg, ffprobe = download_ffmpeg(progress)
    settings.ffmpeg_path, settings.ffprobe_path = str(ffmpeg), str(ffprobe)


def update_ytdlsub_if_stale(settings: Settings, max_age_days: int = 7) -> str | None:
    """Refresh a GUI-managed ytdl-sub.exe if it is older than max_age_days.

    Only touches the copy inside our bin folder, never a user-supplied path.
    """
    managed = bin_dir() / "ytdl-sub.exe"
    if not settings.ytdlsub_path or Path(settings.ytdlsub_path) != managed or not managed.exists():
        return None
    age = dt.datetime.now() - dt.datetime.fromtimestamp(managed.stat().st_mtime)
    if age.days < max_age_days:
        return None
    download_ytdlsub()
    return f"Updated ytdl-sub.exe (previous copy was {age.days} days old)."


def update_ytdlp_if_stale(settings: Settings, max_age_days: int = 7) -> str | None:
    """Refresh a GUI-managed yt-dlp.exe older than max_age_days (YouTube changes often)."""
    managed = bin_dir() / "yt-dlp.exe"
    if not settings.ytdlp_path or Path(settings.ytdlp_path) != managed or not managed.exists():
        return None
    age = dt.datetime.now() - dt.datetime.fromtimestamp(managed.stat().st_mtime)
    if age.days < max_age_days:
        return None
    download_ytdlp()
    return f"Updated yt-dlp.exe (previous copy was {age.days} days old)."
