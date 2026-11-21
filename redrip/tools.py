"""Downloads ytdl-sub, yt-dlp, deno and ffmpeg/ffprobe into the app's bin folder.

Windows: the .exe builds. Linux: the official Linux builds (x86_64 or aarch64); if ffmpeg
is already installed system-wide (most KDE/Linux distros ship it), that copy is used.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from .models import Settings, bin_dir
from .oscompat import IS_WINDOWS, exe, is_arm64, which

_GH = "https://github.com"
if IS_WINDOWS:
    YTDLSUB_URL = f"{_GH}/jmbannon/ytdl-sub/releases/latest/download/ytdl-sub.exe"
    YTDLP_URL = f"{_GH}/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
    DENO_URL = f"{_GH}/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
    FFMPEG_URL = f"{_GH}/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
elif is_arm64():
    YTDLSUB_URL = f"{_GH}/jmbannon/ytdl-sub/releases/latest/download/ytdl-sub_aarch64"
    YTDLP_URL = f"{_GH}/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux_aarch64"
    DENO_URL = f"{_GH}/denoland/deno/releases/latest/download/deno-aarch64-unknown-linux-gnu.zip"
    FFMPEG_URL = f"{_GH}/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linuxarm64-gpl.tar.xz"
else:
    YTDLSUB_URL = f"{_GH}/jmbannon/ytdl-sub/releases/latest/download/ytdl-sub"
    YTDLP_URL = f"{_GH}/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux"
    DENO_URL = f"{_GH}/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip"
    FFMPEG_URL = f"{_GH}/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"

Progress = Callable[[str, int, int], None]  # (label, bytes_done, bytes_total)


def _download(url: str, dest: Path, label: str, progress: Progress | None) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Red-Rip"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(256 * 1024):
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(label, done, total)
    tmp.replace(dest)


def _make_executable(path: Path) -> Path:
    if not IS_WINDOWS:
        path.chmod(path.stat().st_mode | 0o755)
    return path


def download_ytdlsub(progress: Progress | None = None) -> Path:
    dest = bin_dir() / exe("ytdl-sub")
    _download(YTDLSUB_URL, dest, dest.name, progress)
    return _make_executable(dest)


def download_ffmpeg(progress: Progress | None = None) -> tuple[Path, Path]:
    out_dir = bin_dir()
    wanted = {exe("ffmpeg"), exe("ffprobe")}
    results: dict[str, Path] = {}
    with tempfile.TemporaryDirectory() as td:
        archive = Path(td) / ("ffmpeg.zip" if IS_WINDOWS else "ffmpeg.tar.xz")
        _download(FFMPEG_URL, archive, "ffmpeg (~150 MB)", progress)
        if progress:
            progress("Extracting ffmpeg", 0, 0)
        if IS_WINDOWS:
            with zipfile.ZipFile(archive) as zf:
                for member in zf.namelist():
                    name = Path(member).name.lower()
                    if name in wanted and "/bin/" in member.replace("\\", "/"):
                        with zf.open(member) as src, open(out_dir / name, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        results[name] = out_dir / name
        else:
            with tarfile.open(archive, "r:xz") as tf:
                for member in tf.getmembers():
                    name = Path(member.name).name
                    if name in wanted and "/bin/" in member.name and member.isfile():
                        src = tf.extractfile(member)
                        assert src is not None
                        with src, open(out_dir / name, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        results[name] = _make_executable(out_dir / name)
    if len(results) != 2:
        raise RuntimeError("ffmpeg / ffprobe not found in the downloaded archive")
    return results[exe("ffmpeg")], results[exe("ffprobe")]


def download_deno(progress: Progress | None = None) -> Path:
    """deno is the JavaScript runtime yt-dlp uses to solve YouTube's player challenges."""
    dest = bin_dir() / exe("deno")
    with tempfile.TemporaryDirectory() as td:
        zip_path = Path(td) / "deno.zip"
        _download(DENO_URL, zip_path, "deno (JavaScript runtime)", progress)
        with zipfile.ZipFile(zip_path) as zf, zf.open(exe("deno")) as src, open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return _make_executable(dest)


def download_ytdlp(progress: Progress | None = None) -> Path:
    dest = bin_dir() / exe("yt-dlp")
    _download(YTDLP_URL, dest, dest.name, progress)
    return _make_executable(dest)


def install_all(settings: Settings, progress: Progress | None = None) -> None:
    settings.ytdlsub_path = str(download_ytdlsub(progress))
    settings.ytdlp_path = str(download_ytdlp(progress))
    settings.deno_path = str(download_deno(progress))
    system_ffmpeg, system_ffprobe = (None, None) if IS_WINDOWS else (which("ffmpeg"), which("ffprobe"))
    if system_ffmpeg and system_ffprobe:
        # Linux: the distro's ffmpeg is kept up to date by the package manager
        settings.ffmpeg_path, settings.ffprobe_path = system_ffmpeg, system_ffprobe
    else:
        ffmpeg, ffprobe = download_ffmpeg(progress)
        settings.ffmpeg_path, settings.ffprobe_path = str(ffmpeg), str(ffprobe)


def _update_if_stale(current: str, name: str, download, max_age_days: int) -> str | None:
    """Refresh a GUI-managed tool older than max_age_days. Only touches the copy inside
    our bin folder, never a user-supplied or system path."""
    managed = bin_dir() / exe(name)
    if not current or Path(current) != managed or not managed.exists():
        return None
    age = dt.datetime.now() - dt.datetime.fromtimestamp(managed.stat().st_mtime)
    if age.days < max_age_days:
        return None
    download()
    return f"Updated {managed.name} (previous copy was {age.days} days old)."


def update_ytdlsub_if_stale(settings: Settings, max_age_days: int = 7) -> str | None:
    return _update_if_stale(settings.ytdlsub_path, "ytdl-sub", download_ytdlsub, max_age_days)


def update_ytdlp_if_stale(settings: Settings, max_age_days: int = 7) -> str | None:
    """YouTube changes often; a week-old yt-dlp can already be broken."""
    return _update_if_stale(settings.ytdlp_path, "yt-dlp", download_ytdlp, max_age_days)


def is_executable(path: str) -> bool:
    return bool(path) and Path(path).is_file() and (IS_WINDOWS or os.access(path, os.X_OK))
