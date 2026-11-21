import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from redrip import configgen  # noqa: E402
from redrip.models import (  # noqa: E402
    MODE_ALL, MODE_RECENT, AppState, Subscription,
)


def make_state(tmp_path) -> AppState:
    st = AppState()
    st.settings.library_dir = str(tmp_path / "tv")
    st.settings.ytdlsub_path = sys.executable  # any existing file passes validation
    st.subscriptions = [
        Subscription("NOVA PBS", ["https://www.youtube.com/@novapbs"], genre="Documentaries"),
        Subscription("Rick Beato", ["https://www.youtube.com/@RickBeato", "https://youtube.com/@rickbeato240/"],
                     mode=MODE_ALL, season_ordering="year_month", quality="Max 720p"),
        Subscription("BBC News", ["https://www.youtube.com/@BBCNews"], mode=MODE_RECENT,
                     recent_days=7, recent_max_files=20, videos_only=False),
        Subscription("Off", ["https://www.youtube.com/@x"], enabled=False),
    ]
    return st


def test_normalize_url():
    n = configgen.normalize_url
    assert n("https://www.youtube.com/@foo", True) == "https://www.youtube.com/@foo/videos"
    assert n("https://www.youtube.com/@foo/", True) == "https://www.youtube.com/@foo/videos"
    assert n("https://www.youtube.com/channel/UC123", True) == "https://www.youtube.com/channel/UC123/videos"
    assert n("https://www.youtube.com/@foo/streams", True) == "https://www.youtube.com/@foo/streams"
    assert n("https://www.youtube.com/playlist?list=PL1", True) == "https://www.youtube.com/playlist?list=PL1"
    assert n("https://www.youtube.com/@foo", False) == "https://www.youtube.com/@foo"


def test_subscriptions(tmp_path):
    subs = configgen.build_subscriptions(make_state(tmp_path))
    flat = {name: (group, body) for group, entries in subs.items() for name, body in entries.items()}
    assert set(flat) == {"~NOVA PBS", "~Rick Beato", "~BBC News"}  # disabled one skipped

    group, body = flat["~NOVA PBS"]
    assert group.startswith(configgen.NFO_ONLY_PRESET + " | season_by_year__episode_by_month_day | Max 1080p")
    assert "Only Recent Archive" in group and group.endswith("gui_base")
    assert body["url"] == "https://www.youtube.com/@novapbs/videos"
    assert body["only_recent_date_range"] == "14days"

    group, body = flat["~Rick Beato"]
    assert "season_by_year_month__episode_by_day" in group and "Max 720p" in group
    assert "Only Recent" not in group
    assert group.endswith("gui_base | Chunk Downloads | gui_newest_first")  # newest-first default
    assert body["chunk_max_downloads"] == 5
    assert body["url2"] == "https://youtube.com/@rickbeato240/videos"

    group, body = flat["~BBC News"]
    assert "| Only Recent |" in group
    assert body["only_recent_max_files"] == 20
    assert body["url"] == "https://www.youtube.com/@BBCNews"


def test_config_and_validation(tmp_path):
    st = make_state(tmp_path)
    assert configgen.validate(st) == []
    st.settings.throttle_protection = False
    st.settings.max_downloads_per_run = 5
    st.settings.cookies_file = r"C:\Users\me\cookies.txt"
    cfg = configgen.build_config(st)
    base = cfg["presets"]["gui_base"]
    assert base["overrides"]["enable_throttle_protection"] is False
    assert base["ytdl_options"] == {"max_downloads": 5, "cookiefile": "C:/Users/me/cookies.txt"}
    st.settings.deno_path = r"C:\bin\deno.exe"
    assert configgen.build_config(st)["presets"]["gui_base"]["ytdl_options"]["js_runtimes"] == {
        "deno": {"path": "C:/bin/deno.exe"}}

    st.settings.library_dir = ""
    st.subscriptions.append(Subscription("NOVA PBS", ["https://x"]))
    errs = configgen.validate(st)
    assert any("library" in e for e in errs) and any("Duplicate" in e for e in errs)


def test_files_load_in_ytdl_sub(tmp_path):
    """If ytdl-sub is importable, make sure it accepts the generated files."""
    try:
        from ytdl_sub.config.config_file import ConfigFile
        from ytdl_sub.subscriptions.subscription import Subscription as YSub
    except ImportError:
        return
    os.environ.setdefault("APPDATA", str(tmp_path))
    cfg_path, subs_path = configgen.write_files(make_state(tmp_path), tmp_path)
    cfg = ConfigFile.from_file_path(str(cfg_path))
    loaded = {s.name: s for s in YSub.from_file_path(config=cfg, subscription_path=str(subs_path))}
    assert set(loaded) == {"NOVA PBS", "Rick Beato", "BBC News"}
    ov = loaded["Rick Beato"].overrides
    assert ov.script.get("tv_show_by_date_season_ordering").native == "upload-year-month"
    assert ov.script.get("tv_show_genre").native == "YouTube"


def test_batch_tracker():
    from redrip.runner import BatchTracker
    st = AppState()
    st.subscriptions = [
        Subscription("Big", ["u"], mode=MODE_ALL),
        Subscription("Stuck", ["u"], mode=MODE_ALL),
        Subscription("Recent", ["u"]),
    ]
    t = BatchTracker()
    out = (
        "[ytdl-sub] Beginning subscription download for Big\n"
        "[ytdl-sub:downloader] MaxDownloadsReached, stopping additional downloads.\n"
        "[ytdl-sub] Beginning subscription download for Stuck\n"
        "[ytdl-sub:downloader] MaxDownloadsReached, stopping additional downloads.\n"
        "[ytdl-sub] Beginning subscription download for Recent\n"
        "[ytdl-sub:downloader] MaxDownloadsReached, stopping additional downloads.\n"
        "[ytdl-sub] \nNo files changed for Stuck\n"
    )
    for i in range(0, len(out), 7):  # arrives in arbitrary chunks
        t.feed(out[i:i + 7])
    assert t.next_batch(st) == ["Big"]


def test_archive_order_presets():
    newest = Subscription("N", ["u"], mode=MODE_ALL)
    oldest = Subscription("O", ["u"], mode=MODE_ALL, archive_order="oldest")
    assert configgen.group_key(newest, "Max 1080p").endswith("Chunk Downloads | gui_newest_first")
    assert configgen.group_key(oldest, "Max 1080p").endswith("Chunk Downloads")
    st = AppState()
    st.settings.library_dir = "x"
    assert configgen.build_config(st)["presets"]["gui_newest_first"] == {
        "ytdl_options": {"playlistreverse": False}}


def test_title_date_overrides():
    try:
        from ytdl_sub.script.script import Script
    except ImportError:
        return
    cases = {
        "Streamer - [November 15th 2026] WEEKLY STREAM": ("202611", "1501", "2026-11-15"),
        "Stream Feb 3, 2022 part 2": ("202202", "0301", "2022-02-03"),
        "VOD 14th of February 2022": ("202202", "1401", "2022-02-14"),
        "Highlights 2021-07-04": ("202107", "0401", "2021-07-04"),
        "May the force (May 4th 2021)": ("202105", "0401", "2021-05-04"),
        "No date here": ("202503", "0901", "2025-03-09"),  # falls back to upload date
    }
    for title, (season, episode, aired) in cases.items():
        sc = {"title": title, "upload_year": "{ %int(2025) }", "upload_month_padded": "03",
              "upload_day_padded": "09", "upload_date_index_padded": "01"}
        sc.update(configgen.title_date_overrides("year_month"))
        sc["ep"] = "{ %pad_zero(%int(%array_at(episode_number_and_padded_, 0)), 4) }"
        r = Script(sc).resolve()
        assert (r.get("season_number").native, r.get("ep").native,
                r.get("episode_date_standardized").native) == (season, episode, aired), title


def test_file_naming():
    body = configgen.subscription_body
    assert "episode_file_name" not in body(Subscription("A", ["u"]))
    assert body(Subscription("A", ["u"], file_naming="date_title"))["episode_file_name"] == \
        "{episode_date_standardized} - {file_title}"
    # Embedded-only metadata forces numbered names: Jellyfin clears the episode number of
    # date-named files and re-parses seasons from file names after reading embedded tags.
    assert "episode_file_name" not in body(
        Subscription("A", ["u"], file_naming="date_title", metadata_mode="embedded"))
    # The removed title-only option migrates to date + title.
    assert Subscription.from_dict({"name": "A", "urls": ["u"], "file_naming": "title"}).file_naming == "date_title"


def test_embedded_metadata_mode():
    sub = Subscription("E", ["u"], metadata_mode="embedded")
    assert configgen.group_key(sub, "Max 1080p").endswith("gui_embedded_metadata")
    assert "gui_embedded_metadata" not in configgen.group_key(Subscription("N", ["u"]), "Max 1080p")
    st = AppState()
    st.settings.library_dir = "x"
    preset = configgen.build_config(st)["presets"]["gui_embedded_metadata"]
    assert preset == {"nfo_tags": {"enable": False}}  # never season_number/episode_sort (1-byte in MP4)



def test_metadata_modes_and_chapters():
    gk = configgen.group_key
    assert gk(Subscription("A", ["u"]), "Max 1080p").startswith(configgen.NFO_ONLY_PRESET + " |")
    assert gk(Subscription("A", ["u"], metadata_mode="both"), "Max 1080p").startswith(configgen.BASE_PRESET + " |")
    emb = gk(Subscription("A", ["u"], metadata_mode="embedded"), "Max 1080p")
    assert emb.startswith(configgen.BASE_PRESET + " |") and emb.endswith("gui_embedded_metadata")
    # "both" keeps the .nfo, so date-prefixed names stay allowed
    assert Subscription("A", ["u"], metadata_mode="both", file_naming="date_title").effective_file_naming() == "date_title"
    st = AppState()
    st.settings.library_dir = "x"
    cfg = configgen.build_config(st)
    assert "_episode_video_tags" not in cfg["presets"][configgen.NFO_ONLY_PRESET]["preset"]
    assert "chapters" not in cfg["presets"]["gui_base"]
    st.settings.embed_chapters = False
    assert configgen.build_config(st)["presets"]["gui_base"]["chapters"] == {"embed_chapters": False}


def test_info_json_toggle():
    st = AppState()
    st.settings.library_dir = "x"
    assert configgen.build_config(st)["presets"]["gui_base"]["output_options"] == {"info_json_name": ""}
    st.settings.keep_info_json = True
    assert "output_options" not in configgen.build_config(st)["presets"]["gui_base"]


def test_same_day_suffix():
    body = configgen.subscription_body
    assert "episode_number_and_padded_" not in body(Subscription("A", ["u"]))  # ytdl-sub default
    no_suffix = body(Subscription("A", ["u"], same_day_suffix=False))["episode_number_and_padded_"]
    assert "upload_date_index_padded" not in no_suffix and "upload_month_padded" in no_suffix
    titled = body(Subscription("A", ["u"], date_source="title", same_day_suffix=False))
    assert "upload_date_index_padded" not in titled["episode_number_and_padded_"]
    try:
        from ytdl_sub.script.script import Script
    except ImportError:
        return
    for order, expected in (("year", "1105"), ("year_month", "05")):
        sc = {"title": "x [November 5th 2026]", "upload_year": "{ %int(2025) }", "upload_month_padded": "03",
              "upload_day_padded": "09", "upload_date_index_padded": "01"}
        sc.update(configgen.title_date_overrides(order, same_day_suffix=False))
        sc["ep"] = "{ %pad_zero(%int(%array_at(episode_number_and_padded_, 0)), " \
                   "%int(%array_at(episode_number_and_padded_, 1))) }"
        assert Script(sc).resolve().get("ep").native == expected


def test_cookies_from_browser():
    st = AppState()
    st.settings.library_dir = "x"
    assert "cookiesfrombrowser" not in configgen.build_config(st)["presets"]["gui_base"].get("ytdl_options", {})
    st.settings.cookies_browser = "firefox"
    assert configgen.build_config(st)["presets"]["gui_base"]["ytdl_options"]["cookiesfrombrowser"] == ["firefox"]
