"""Turns the GUI's state into ytdl-sub's config.yaml + subscriptions.yaml.

Every subscription gets its own preset group so per-channel options never leak
into each other:

    "Jellyfin TV Show by Date | Max 1080p | Only Recent Archive":
      "~Channel Name":
        url: "https://www.youtube.com/@channel"
        tv_show_genre: "Documentaries"
        tv_show_content_rating: "TV-PG"
        only_recent_date_range: "14days"
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .models import (
    MODE_ALL, MODE_RECENT, MODE_RECENT_ARCHIVE, AppState, Subscription, app_dir,
)

BASE_PRESET = "Jellyfin TV Show by Date"
# Same as ytdl-sub's Jellyfin preset minus "_episode_video_tags", which rewrites every
# downloaded file with ffmpeg just to embed tags that the .nfo already provides.
# Built from ytdl-sub's internal presets (verified identical apart from video_tags).
NFO_ONLY_PRESET = "gui_jellyfin_tv_show_by_date_nfo_only"
SEASON_PRESETS = {
    "year": "season_by_year__episode_by_month_day",
    "year_month": "season_by_year_month__episode_by_day",
}
MAX_URLS = 30  # ytdl-sub supports url .. url30 in the ~override form


def _posix(path: str) -> str:
    """ytdl-sub accepts forward slashes on Windows; they avoid YAML escape issues."""
    return path.replace("\\", "/") if path else path


def build_config(state: AppState) -> dict:
    s = state.settings
    working = s.working_dir or str(app_dir() / "working")
    configuration: dict = {
        "working_directory": _posix(working),
        "persist_logs": {
            "logs_directory": _posix(str(app_dir() / "logs" / "ytdl-sub")),
            "keep_successful_logs": False,
        },
    }
    if s.ffmpeg_path:
        configuration["ffmpeg_path"] = _posix(s.ffmpeg_path)
    if s.ffprobe_path:
        configuration["ffprobe_path"] = _posix(s.ffprobe_path)

    base: dict = {
        "overrides": {"tv_show_directory": _posix(s.library_dir)},
    }
    ytdl_options: dict = {}
    if s.deno_path:
        # yt-dlp needs a JavaScript runtime to solve YouTube's player challenges;
        # without one some formats go missing (or downloads fail entirely).
        ytdl_options["js_runtimes"] = {"deno": {"path": _posix(s.deno_path)}}
    if s.cookies_file:
        ytdl_options["cookiefile"] = _posix(s.cookies_file)
    if s.cookies_browser:
        # yt-dlp --cookies-from-browser: signed-in session avoids "Sign in to confirm you're not a bot"
        ytdl_options["cookiesfrombrowser"] = [s.cookies_browser]
    if s.max_downloads_per_run > 0:
        ytdl_options["max_downloads"] = s.max_downloads_per_run
    if ytdl_options:
        base["ytdl_options"] = ytdl_options
    # ytdl-sub's built-in throttle protection (randomised sleeps between downloads)
    # is on by default and strongly recommended to avoid YouTube rate limits/bans.
    if not s.throttle_protection:
        base["overrides"]["enable_throttle_protection"] = False
    if not s.keep_info_json:
        # Documented by ytdl-sub: an empty info_json_name disables the .info.json files.
        base["output_options"] = {"info_json_name": ""}
    if not s.embed_chapters:
        # yt-dlp's "[Metadata] Adding metadata to ..." step: a full file rewrite for
        # every video that has chapters.
        base["chapters"] = {"embed_chapters": False}

    presets = {
        "gui_base": base,
        # Applied after "Chunk Downloads" to flip it to newest-first. break_on_existing stays
        # False (from Chunk Downloads) so already-downloaded videos are skipped, not a stop.
        "gui_newest_first": {"ytdl_options": {"playlistreverse": False}},
        # Per-episode metadata only as tags inside the .mp4. ytdl-sub's Jellyfin preset
        # already embeds show, title, synopsis, date, genre and episode_id (the episode
        # number, stored as text). Deliberately NOT season_number/episode_sort: MP4 stores
        # those as one byte (0-255), so 202202 / 1401 would be written as 218 / 121.
        # The season comes from the "Season N" folder. tvshow.nfo (one per show) is kept.
        "gui_embedded_metadata": {"nfo_tags": {"enable": False}},
        NFO_ONLY_PRESET: {
            "preset": ["_base", "_episode_base", "_episode_nfo_tags", "_tv_show_by_date"],
            "overrides": {
                "tv_show_poster_file_name": "poster.jpg",
                "tv_show_fanart_file_name": "fanart.jpg",
                "season_poster_file_name": "season{season_number_padded}-poster.jpg",
            },
        },
    }
    return {"configuration": configuration, "presets": presets}


def group_key(sub: Subscription, default_quality: str) -> str:
    parts = [
        NFO_ONLY_PRESET if sub.metadata_mode == "nfo" else BASE_PRESET,
        SEASON_PRESETS.get(sub.season_ordering, SEASON_PRESETS["year"]),
        sub.quality or default_quality,
    ]
    if sub.mode == MODE_RECENT_ARCHIVE:
        parts.append("Only Recent Archive")
    elif sub.mode == MODE_RECENT:
        parts.append("Only Recent")
    parts.append("gui_base")  # after the content presets, so the GUI's global settings win
    if sub.mode == MODE_ALL:
        # Oldest-first, N videos per invocation. Must come after gui_base so its
        # max_downloads beats the global "max downloads per run" setting.
        parts.append("Chunk Downloads")
        if sub.archive_order != "oldest":
            parts.append("gui_newest_first")
    if sub.metadata_mode == "embedded":
        parts.append("gui_embedded_metadata")
    return " | ".join(parts)


_CHANNEL_RE = re.compile(
    r"^(https?://(?:www\.|m\.)?youtube\.com/(?:@[^/?#]+|channel/[^/?#]+|c/[^/?#]+|user/[^/?#]+))/?$",
    re.IGNORECASE,
)


def normalize_url(url: str, videos_only: bool) -> str:
    """For a bare YouTube channel URL, optionally point at its /videos tab.

    A bare channel URL makes yt-dlp walk every tab (Videos, Shorts, Live), which
    usually isn't what you want in a Jellyfin TV library.
    """
    url = url.strip()
    if videos_only:
        m = _CHANNEL_RE.match(url)
        if m:
            return m.group(1) + "/videos"
    return url


def subscription_body(sub: Subscription) -> dict:
    urls = [normalize_url(u, sub.videos_only) for u in sub.urls if u.strip()][:MAX_URLS]
    body: dict = {}
    for i, url in enumerate(urls):
        body["url" if i == 0 else f"url{i + 1}"] = url
    body["tv_show_genre"] = sub.genre or "YouTube"
    body["tv_show_content_rating"] = sub.content_rating or "TV-14"
    if sub.mode in (MODE_RECENT, MODE_RECENT_ARCHIVE):
        body["only_recent_date_range"] = f"{max(1, int(sub.recent_days))}days"
    if sub.mode == MODE_ALL:
        body["chunk_max_downloads"] = max(2, int(sub.batch_size))
    if sub.mode == MODE_RECENT:
        body["only_recent_max_files"] = max(0, int(sub.recent_max_files))
    if sub.date_source == "title":
        body.update(title_date_overrides(sub.season_ordering, sub.same_day_suffix))
    elif not sub.same_day_suffix:
        body["episode_number_and_padded_"] = episode_number_override(
            sub.season_ordering, "upload_month_padded", "upload_day_padded", False)
    # Season/episode always go into the .nfo (Jellyfin reads them from there) and the
    # "Season N" folder; this only changes the file names (video, .nfo, thumbnail).
    if sub.effective_file_naming() == "date_title":
        body["episode_file_name"] = "{episode_date_standardized} - {file_title}"
    return body


def build_subscriptions(state: AppState) -> dict:
    out: dict = {}
    for sub in state.subscriptions:
        if not sub.enabled or not any(u.strip() for u in sub.urls):
            continue
        key = group_key(sub, state.settings.quality)
        out.setdefault(key, {})[f"~{sub.name}"] = subscription_body(sub)
    return out


def validate(state: AppState) -> list[str]:
    """Problems that would make a run fail; shown to the user before running."""
    errors = []
    s = state.settings
    if not s.ytdlsub_path or not Path(s.ytdlsub_path).exists():
        errors.append("ytdl-sub executable not found. Set it in Settings (or use 'Download tools').")
    if not s.library_dir:
        errors.append("Jellyfin library folder is not set (Settings).")
    names = set()
    for sub in state.subscriptions:
        if not sub.name.strip():
            errors.append("A subscription has an empty name.")
        if sub.name in names:
            errors.append(f"Duplicate subscription name: {sub.name}")
        names.add(sub.name)
        if sub.enabled and not any(u.strip() for u in sub.urls):
            errors.append(f"'{sub.name}' has no URL.")
    if not any(sub.enabled for sub in state.subscriptions):
        errors.append("No enabled subscriptions.")
    return errors


class _Dumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')


_Dumper.add_representer(str, _str_presenter)


def dump(data: dict) -> str:
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=1000)


def write_files(state: AppState, directory: Path | None = None) -> tuple[Path, Path]:
    directory = directory or app_dir()
    config_path = directory / "config.yaml"
    subs_path = directory / "subscriptions.yaml"
    header = "# Generated by ytdl-sub-win-gui. Edits here are overwritten on the next run.\n"
    config_path.write_text(header + dump(build_config(state)), encoding="utf-8")
    subs_path.write_text(header + dump(build_subscriptions(state)), encoding="utf-8")
    return config_path, subs_path


# --------------------------------------------------------------------------- dates from titles
# For channels that re-upload streams/broadcasts, the real air date is often in the video
# title ("Streamer - [November 15th 2026] WEEKLY STREAM"). These ytdl-sub script overrides parse
# it and use it for season/episode numbers and the .nfo aired date. If no date is found in
# a title, the upload date is used for that video. (No braces in the regexes: they would
# clash with ytdl-sub's {script} syntax.)
_MON = "(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[.]?"
_TITLE_DATE_PATTERNS = {
    # November 15th 2026 / Nov 15, 2026 / November 15 2026
    "gui_tdate_mdy_": rf"(?i)\b{_MON}\s+(\d\d?)(?:st|nd|rd|th)?,?\s+(\d\d\d\d)\b",
    # 15th November 2026 / 15 Nov 2026 / 15th of November, 2026
    "gui_tdate_dmy_": rf"(?i)\b(\d\d?)(?:st|nd|rd|th)?\s+(?:of\s+)?{_MON},?\s+(\d\d\d\d)\b",
    # 2026-11-15 / 2026.11.15 / 2026/11/15
    "gui_tdate_iso_": r"\b(\d\d\d\d)[-./](\d\d?)[-./](\d\d?)\b",
}
_MONTH_MAP = ('{"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06", '
              '"jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"}')


def _month(expr: str) -> str:
    return f"%map_get({_MONTH_MAP}, %slice(%lower(%string({expr})), 0, 3))"


def _pad2(expr: str) -> str:
    return f"%pad_zero(%int({expr}), 2)"


def episode_number_override(season_ordering: str, month: str, day: str, same_day_suffix: bool) -> str:
    """episode_number_and_padded_ ([number, pad width]) built from month/day expressions.

    ytdl-sub normally appends a 2-digit same-day counter (15 Nov -> 111501) so two videos
    from one day never share an episode number. Without it: 1115 (or 15 for year+month
    seasons); two videos dated the same day then get the same number in Jellyfin.
    """
    m, d = f"%string(%int({month}))", f"%pad_zero(%int({day}), 2)"
    if season_ordering == "year_month":
        if same_day_suffix:
            return f"{{ [ %concat(%string(%int({day})), upload_date_index_padded), 4 ] }}"
        return f"{{ [ %string(%int({day})), 2 ] }}"
    if same_day_suffix:
        return f"{{ [ %concat({m}, {d}, upload_date_index_padded), 6 ] }}"
    return f"{{ [ %concat({m}, {d}), 4 ] }}"


def title_date_overrides(season_ordering: str, same_day_suffix: bool = True) -> dict:
    o: dict = {}
    for name, pattern in _TITLE_DATE_PATTERNS.items():
        o[name] = "{ %regex_search(\"" + pattern + "\", title) }"
    mdy, dmy, iso = "gui_tdate_mdy_", "gui_tdate_dmy_", "gui_tdate_iso_"
    at = lambda v, i: f"%array_at({v}, {i})"  # noqa: E731
    o["gui_tdate_parts_"] = (
        "{ %elif("
        f" %bool({mdy}), [ %string({at(mdy, 3)}), {_month(at(mdy, 1))}, {_pad2(at(mdy, 2))} ],"
        f" %bool({dmy}), [ %string({at(dmy, 3)}), {_month(at(dmy, 2))}, {_pad2(at(dmy, 1))} ],"
        f" %bool({iso}), [ %string({at(iso, 1)}), {_pad2(at(iso, 2))}, {_pad2(at(iso, 3))} ],"
        " [ %string(upload_year), upload_month_padded, upload_day_padded ]"
        ") }"
    )
    o["gui_tdate_y_"] = "{ %string(%array_at(gui_tdate_parts_, 0)) }"
    o["gui_tdate_m_"] = "{ %string(%array_at(gui_tdate_parts_, 1)) }"
    o["gui_tdate_d_"] = "{ %string(%array_at(gui_tdate_parts_, 2)) }"
    if season_ordering == "year_month":
        o["season_number"] = "{ %concat(gui_tdate_y_, gui_tdate_m_) }"
    else:
        o["season_number"] = "{ gui_tdate_y_ }"
    o["episode_number_and_padded_"] = episode_number_override(
        season_ordering, "gui_tdate_m_", "gui_tdate_d_", same_day_suffix)
    o["episode_date_standardized"] = "{ %concat(gui_tdate_y_, \"-\", gui_tdate_m_, \"-\", gui_tdate_d_) }"
    return o
