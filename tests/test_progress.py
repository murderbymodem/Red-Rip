import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ytdlsub_win_gui import runner  # noqa: E402

OUTPUT = """[ytdl-sub] Beginning subscription download for Example VOD Archive\r
[ytdl-sub:yt-dlp] [download] Downloading playlist: Example VOD Archive - Videos\r
[ytdl-sub:downloader] Downloading metadata for Example VOD Archive - Videos\r
[ytdl-sub:downloader] Downloading metadata for Newest video\r
[ytdl-sub:downloader] Downloading metadata for Middle video\r
[ytdl-sub:downloader] Downloading metadata for Oldest video\r
[ytdl-sub:downloader] Beginning downloads for https://www.youtube.com/@x/videos\r
[ytdl-sub:downloader] Downloading entry 1/3: Oldest video\r
[ytdl-sub:yt-dlp] [download] Destination: W/oldest.f400.mp4\r
"""


def feed_in_chunks(t, text, size):
    for i in range(0, len(text), size):
        t.feed(text[i:i + size])


def test_tracker_queue_and_stages():
    for size in (1, 7, 4096):  # output arrives in arbitrary pieces
        t = runner.ProgressTracker()
        feed_in_chunks(t, OUTPUT, size)
        assert t.channel == "Example VOD Archive"
        # channel's own list is skipped; downloads go in reverse lookup order
        assert [i["title"] for i in t.items] == ["Oldest video", "Middle video", "Newest video"]
        assert (t.current, t.position, t.stage) == ("Oldest video", "1/3", "downloading video")
        assert t.up_next() == ["Middle video", "Newest video"]

    t.feed('[ytdl-sub:yt-dlp] [Merger] Merging formats into "W/oldest.mp4"\n')
    assert t.stage == "merging video + audio"
    t.feed("[ytdl-sub:throttle-protection] Sleeping between downloads for 14.2 seconds\n")
    assert t.items[0]["status"] == runner.DONE and t.current is None and "pausing 14s" in t.stage
    t.feed("[ytdl-sub:downloader] Downloading entry 2/3: Middle video\n"
           "[ytdl-sub:yt-dlp] ERROR: [youtube] abc: Sign in to confirm you're not a bot\n"
           "[ytdl-sub:downloader] Downloading entry 3/3: Newest video\n"
           "[ytdl-sub] Download Summary:\n")
    assert [i["status"] for i in t.items] == [runner.DONE, runner.FAILED, runner.DONE]
    assert t.stage == "finished"


def test_download_size_helpers(tmp_path):
    info = tmp_path / "abc.info.json"
    info.write_text(json.dumps({"title": "A video", "requested_formats": [{"filesize": 300}, {"filesize_approx": 100}]}))
    (tmp_path / "abc.f400.mp4.part").write_bytes(b"x" * 150)
    (tmp_path / "abc.f251.webm").write_bytes(b"x" * 50)
    (tmp_path / "abc.jpg").write_bytes(b"x" * 999)         # thumbnail: not counted
    (tmp_path / "other.f400.mp4.part").write_bytes(b"x" * 999)  # another video: not counted
    assert runner.find_info_json(tmp_path, "A video") == info
    assert runner.find_info_json(tmp_path, "Missing") is None
    assert runner.expected_size(info) == 400
    assert runner.downloaded_bytes(info) == 200


def test_block_detection():
    blocking = [
        "[ytdl-sub:yt-dlp] ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies",
        "[ytdl-sub:yt-dlp] ERROR: [youtube] abc: Sign in to confirm you�re not a bot.",  # garbled apostrophe
        "[ytdl-sub:yt-dlp] ERROR: [youtube] abc: The current session has been rate-limited by YouTube for up to an hour",
        "[ytdl-sub:yt-dlp] ERROR: unable to download video data: HTTP Error 429: Too Many Requests",
    ]
    for line in blocking:
        t = runner.BatchTracker()
        t.feed(line + "\n")
        assert t.blocked, line
    not_blocking = [
        "[ytdl-sub:yt-dlp] ERROR: [youtube] abc: Private video. Sign in if you've been granted access",
        "[ytdl-sub:yt-dlp] ERROR: [youtube] abc: Join this channel to get access to members-only content",
        "[ytdl-sub:yt-dlp] WARNING: [youtube] HTTP Error 429: Too Many Requests. Retrying (1/3)...",  # recovers
    ]
    for line in not_blocking:
        t = runner.BatchTracker()
        t.feed(line + "\n")
        assert t.blocked is None, line
