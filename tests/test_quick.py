import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ytdlsub_win_gui import quick, runner  # noqa: E402
from ytdlsub_win_gui.models import Settings  # noqa: E402


def test_build_command():
    s = Settings()
    s.ytdlp_path, s.ffmpeg_path, s.deno_path = r"C:\app\bin\yt-dlp.exe", r"C:\app\bin\ffmpeg.exe", r"C:\app\bin\deno.exe"
    s.cookies_browser = "firefox"
    cmd = quick.build_command(s, " https://www.youtube.com/shorts/abc123 ", "1080", Path("D:/Downloads"))
    assert cmd[0] == s.ytdlp_path
    assert cmd[-2:] == ["--", "https://www.youtube.com/shorts/abc123"]  # URL can't be read as an option
    for flag in ("--newline", "--no-playlist", "--no-quiet", "--ffmpeg-location", "--cookies-from-browser"):
        assert flag in cmd
    assert "bv*[height<=1080]+ba/b[height<=1080]" in cmd
    assert f"deno:{s.deno_path}" in cmd
    mp3 = quick.build_command(s, "https://youtu.be/x", "mp3", Path("D:/Downloads"))
    assert "-x" in mp3 and "mp3" in mp3 and "--merge-output-format" not in mp3


def test_is_url():
    assert quick.is_url("https://www.youtube.com/watch?v=abc")
    assert quick.is_url("http://youtu.be/abc")
    assert not quick.is_url("not a url") and not quick.is_url("-f evil") and not quick.is_url("")


def test_progress_parsing():
    p = quick.QuickProgress()
    out = ("[youtube] abc: Downloading webpage\r\n"
           "[download] Destination: D:\\Downloads\\My Video [abc].f400.mp4\r\n"
           "[download]  42.5% of  120.50MiB at    5.20MiB/s ETA 00:13\r\n")
    for i in range(0, len(out), 5):
        p.feed(out[i:i + 5])
    assert (p.stage, p.percent, p.name) == ("downloading", 42.5, "My Video [abc]")
    assert p.detail == "of 120.50MiB · 5.20MiB/s · 00:13 left"
    p.feed("[download] Destination: D:\\Downloads\\My Video [abc].f251.webm\n")
    assert p.stage == "downloading (part 2: audio)" and p.percent == 0.0
    p.feed('[Merger] Merging formats into "D:\\Downloads\\My Video [abc].mp4"\n')
    assert p.stage == "merging video + audio"
    p.feed("QUICKDONE:D:\\Downloads\\My Video [abc].mp4\n")
    assert (p.stage, p.file) == ("done", "D:\\Downloads\\My Video [abc].mp4")
    e = quick.QuickProgress()
    e.feed("ERROR: [youtube] abc: Video unavailable\n")
    assert e.error == "[youtube] abc: Video unavailable"


def test_safe_points_for_stop_after_current():
    t = runner.ProgressTracker()
    t.feed("[ytdl-sub] Beginning subscription download for X\n"
           "[ytdl-sub:downloader] Downloading entry 1/3: A\n")
    mark = t.safe_points  # "stop after current video" pressed while A downloads
    t.feed('[ytdl-sub:yt-dlp] [Merger] Merging formats into "a.mp4"\n')
    assert t.safe_points == mark  # still finishing A
    t.feed("[ytdl-sub:throttle-protection] Sleeping between downloads for 14.20 seconds\n")
    assert t.safe_points > mark  # A is in the library and recorded: safe to stop
    t2 = runner.ProgressTracker()
    t2.feed("[ytdl-sub:downloader] Downloading entry 1/3: A\n")
    mark = t2.safe_points
    t2.feed("[ytdl-sub:downloader] Downloading entry 2/3: B\n")  # throttle protection off
    assert t2.safe_points > mark
    t2.feed("[ytdl-sub:throttle-protection] Sleeping between subscriptions for 20 seconds\n")
    assert t2.safe_points == mark + 1  # subscription pauses aren't per-video points
