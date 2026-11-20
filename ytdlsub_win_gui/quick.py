"""Quick download: one video or Short straight through yt-dlp, outside ytdl-sub and batches."""
from __future__ import annotations

import re
from pathlib import Path

from .models import Settings

QUALITIES = {
    "best": ("Best available", ["-f", "bv*+ba/b", "--merge-output-format", "mp4"]),
    "1440": ("Max 1440p", ["-f", "bv*[height<=1440]+ba/b[height<=1440]", "--merge-output-format", "mp4"]),
    "1080": ("Max 1080p", ["-f", "bv*[height<=1080]+ba/b[height<=1080]", "--merge-output-format", "mp4"]),
    "720": ("Max 720p", ["-f", "bv*[height<=720]+ba/b[height<=720]", "--merge-output-format", "mp4"]),
    "mp3": ("Audio only (MP3)", ["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "0"]),
}

DONE_MARK = "QUICKDONE:"  # prefix of the line yt-dlp prints with the final file path


def default_folder() -> Path:
    return Path.home() / "Downloads"


def is_url(text: str) -> bool:
    return bool(re.match(r"^https?://\S+$", text.strip(), re.IGNORECASE))


def build_command(settings: Settings, url: str, quality: str, out_dir: Path) -> list[str]:
    cmd = [
        settings.ytdlp_path,
        "--newline",                # one progress line per update, so it can be read live
        "--color", "never",
        "--no-playlist",            # a watch?v=...&list=... link downloads just that video
        "--embed-metadata", "--embed-chapters",
        "-o", str(out_dir / "%(title)s [%(id)s].%(ext)s"),
        "--print", f"after_move:{DONE_MARK}%(filepath)s",
        "--no-quiet",               # --print would otherwise hide the progress lines
        *QUALITIES.get(quality, QUALITIES["best"])[1],
    ]
    if settings.ffmpeg_path:
        cmd += ["--ffmpeg-location", settings.ffmpeg_path]
    if settings.deno_path:
        cmd += ["--js-runtimes", f"deno:{settings.deno_path}"]
    if settings.cookies_file:
        cmd += ["--cookies", settings.cookies_file]
    if settings.cookies_browser:
        cmd += ["--cookies-from-browser", settings.cookies_browser]
    return cmd + ["--", url.strip()]  # "--": a URL can never be read as an option


_PCT_RE = re.compile(
    r"^\[download\]\s+([\d.]+)% of\s+~?\s*([\d.]+\s*[KMGT]?i?B)"
    r"(?:\s+at\s+([\d.]+\s*[KMGT]?i?B/s))?(?:\s+ETA\s+(\S+))?")
_TITLE_RE = re.compile(r"^\[download\] Destination: (.+)$")


class QuickProgress:
    """Reads yt-dlp's output for one quick download."""

    def __init__(self):
        self.percent: float | None = None
        self.detail = ""
        self.stage = "starting"
        self.file: str | None = None   # final path, once finished
        self.error: str | None = None
        self.name = ""                  # "Title [id]", from the first destination file
        self._streams = 0
        self._partial = ""

    def feed(self, text: str) -> None:
        self._partial += text.replace("\r", "\n")
        *lines, self._partial = self._partial.split("\n")
        for line in lines:
            self._line(line.strip())

    def _line(self, line: str) -> None:
        if line.startswith(DONE_MARK):
            self.file = line[len(DONE_MARK):]
            self.stage, self.percent = "done", 100.0
        elif m := _TITLE_RE.match(line):
            if not self.name:
                base = re.split(r"[\\/]", m.group(1))[-1].rsplit(".", 1)[0]  # either path separator
                self.name = re.sub(r"\.f\d+$", "", base)  # drop the ".f400" format part
            self._streams += 1
            self.stage = "downloading" if self._streams == 1 else "downloading (part 2: audio)"
            self.percent = 0.0
        elif m := _PCT_RE.match(line):
            self.percent = float(m.group(1))
            parts = [f"of {m.group(2)}"]
            if m.group(3):
                parts.append(m.group(3))
            if m.group(4) and m.group(4) != "Unknown":
                parts.append(f"{m.group(4)} left")
            self.detail = " · ".join(parts)
        elif line.startswith("[Merger]"):
            self.stage, self.detail = "merging video + audio", ""
        elif line.startswith("[ExtractAudio]"):
            self.stage, self.detail = "converting to MP3", ""
        elif line.startswith("[Metadata]") or line.startswith("[EmbedThumbnail]"):
            self.stage, self.detail = "adding metadata", ""
        elif line.startswith("ERROR:"):
            self.error = line[len("ERROR:"):].strip()
