"""ytdl-sub's per-channel download archive ("what has already been downloaded").

ytdl-sub keeps `.ytdl-sub-<subscription name>-download-archive.json` in the show's
folder. Every video listed there is skipped on later runs, even if its files were
deleted. Format: {video_id: {"upload_date": ..., "extractor": ..., "file_names": [paths
relative to the show folder]}}.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

from .models import AppState, Subscription

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".m4v", ".mov", ".avi"}


@dataclass
class ArchiveInfo:
    path: Path               # the archive json
    show_dir: Path           # folder the file_names are relative to
    total: int               # videos recorded
    missing: list[str]       # video ids whose video file no longer exists


def find_archive(state: AppState, sub: Subscription) -> Path | None:
    """Locate the channel's archive inside the library folder (show folder is one level down)."""
    library = Path(state.settings.library_dir)
    if not library.is_dir():
        return None
    exact = f".ytdl-sub-{sub.name}-download-archive.json"
    candidates = []
    for show_dir in [library, *[p for p in library.iterdir() if p.is_dir()]]:
        for f in show_dir.glob(".ytdl-sub-*-download-archive.json"):
            if f.name == exact:
                return f
            # ytdl-sub may use a sanitized subscription name; fall back to the folder name
            if show_dir.name == sub.name:
                candidates.append(f)
    return candidates[0] if len(candidates) == 1 else None


def inspect(archive: Path) -> ArchiveInfo:
    data = json.loads(archive.read_text(encoding="utf-8"))
    show_dir = archive.parent
    missing = []
    for vid, mapping in data.items():
        videos = [f for f in mapping.get("file_names", []) if Path(f).suffix.lower() in VIDEO_EXTS]
        if videos and not any((show_dir / f).exists() for f in videos):
            missing.append(vid)
    return ArchiveInfo(path=archive, show_dir=show_dir, total=len(data), missing=missing)


def _backup(archive: Path) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate, n = archive.with_name(f"{archive.name}.bak-{stamp}"), 1
    while candidate.exists():  # never overwrite an earlier backup made in the same second
        n += 1
        candidate = archive.with_name(f"{archive.name}.bak-{stamp}-{n}")
    return candidate


def forget_missing(archive: Path) -> tuple[int, Path]:
    """Remove entries whose video file is gone, so the next run downloads them again.
    Leftover sidecar files (.nfo/thumbnail) of those videos are deleted too, so the
    re-download doesn't collide with them. Returns (count removed, backup path)."""
    info = inspect(archive)
    data = json.loads(archive.read_text(encoding="utf-8"))
    backup = _backup(archive)
    backup.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    for vid in info.missing:
        files = data[vid].get("file_names", [])
        # Only sidecars named after the deleted video (e.g. "<video>.nfo", "<video>-thumb.jpg");
        # never show-level files like poster.jpg/tvshow.nfo that may be listed on an entry.
        stems = [str(Path(f).with_suffix("")) for f in files if Path(f).suffix.lower() in VIDEO_EXTS]
        for f in files:
            p = info.show_dir / f
            if p.is_file() and any(str(Path(f)).startswith(stem) for stem in stems):
                try:
                    p.unlink()
                except OSError:
                    pass
        del data[vid]
    tmp = archive.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(archive)
    return len(info.missing), backup


def reset(archive: Path) -> Path:
    """Forget everything: the archive is renamed to a backup (not deleted)."""
    backup = _backup(archive)
    archive.replace(backup)
    return backup
