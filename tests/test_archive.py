import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ytdlsub_win_gui import archive  # noqa: E402
from ytdlsub_win_gui.models import AppState, Subscription  # noqa: E402


def make_library(tmp_path):
    show = tmp_path / "lib" / "Example VOD Archive"
    (show / "Season 2026").mkdir(parents=True)
    kept, gone = "Season 2026/2026-11-15 - Kept", "Season 2026/2026-11-14 - Gone"
    for f in (f"{kept}.mp4", f"{kept}.nfo", f"{kept}-thumb.jpg", f"{gone}.nfo", f"{gone}-thumb.jpg",
              "poster.jpg", "tvshow.nfo"):
        (show / f).write_text("x")
    data = {
        "keep1": {"upload_date": "2026-11-15", "extractor": "youtube",
                  "file_names": [f"{kept}.mp4", f"{kept}.nfo", f"{kept}-thumb.jpg"]},
        # deleted video; its entry also lists show-level files, which must survive
        "gone1": {"upload_date": "2026-11-14", "extractor": "youtube",
                  "file_names": [f"{gone}.mp4", f"{gone}.nfo", f"{gone}-thumb.jpg", "poster.jpg", "tvshow.nfo"]},
    }
    arc = show / ".ytdl-sub-Example VOD Archive-download-archive.json"
    arc.write_text(json.dumps(data))
    st = AppState()
    st.settings.library_dir = str(tmp_path / "lib")
    return st, show, arc, gone


def test_find_and_forget_missing(tmp_path):
    st, show, arc, gone = make_library(tmp_path)
    assert archive.find_archive(st, Subscription("Example VOD Archive", ["u"])) == arc
    assert archive.find_archive(st, Subscription("Other", ["u"])) is None
    info = archive.inspect(arc)
    assert (info.total, info.missing) == (2, ["gone1"])

    count, backup = archive.forget_missing(arc)
    assert count == 1 and backup.exists()
    assert set(json.loads(arc.read_text())) == {"keep1"}
    assert not (show / f"{gone}.nfo").exists() and not (show / f"{gone}-thumb.jpg").exists()
    assert (show / "poster.jpg").exists() and (show / "tvshow.nfo").exists()  # show-level files kept

    try:  # the edited archive must still load in ytdl-sub itself
        from ytdl_sub.ytdl_additions.enhanced_download_archive import DownloadMappings
    except ImportError:
        return
    assert list(DownloadMappings.from_file(str(arc)).entry_mappings) == ["keep1"]


def test_reset(tmp_path):
    st, show, arc, _ = make_library(tmp_path)
    backup = archive.reset(arc)
    assert not arc.exists() and backup.exists()


def test_backups_never_overwrite(tmp_path):
    st, show, arc, _ = make_library(tmp_path)
    archive.forget_missing(arc)
    archive.reset(arc)
    assert len(list(show.glob("*.bak-*"))) == 2
