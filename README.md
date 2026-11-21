# ytdl-sub-win-gui
Windows GUI for ytdl-sub written in Python focused on YouTube to Jellyfin functionality

An unofficial Windows desktop app on top of [ytdl-sub](https://github.com/jmbannon/ytdl-sub).
Add YouTube channels, choose how much to download, and it will fetch new videos
every day into a Jellyfin-ready TV library. It writes ytdl-sub's YAML for you.

Not affiliated with the ytdl-sub project, and not the same as its `ytdl-sub-gui` container image
(a web-based config editor).

<img width="775" height="818" alt="ytdl-sub-win-gui_2WovSnTUpi" src="https://github.com/user-attachments/assets/7c04e767-b1ee-4b5b-ac81-fee14f77f13c" />

## Features

- **Channel list**: one channel is one Jellyfin TV show. A show can merge several URLs (e.g. a main channel and its second channel).
- **Jellyfin naming and metadata**: built on ytdl-sub's `Jellyfin TV Show by Date` preset.
  ```
  <Library>\NOVA PBS\
      poster.jpg  fanart.jpg  tvshow.nfo
      Season 2026\
          s2026.e031701 - Video Title.mp4
          s2026.e031701 - Video Title.nfo
          s2026.e031701 - Video Title-thumb.jpg
  ```
  You can choose seasons by year (episode = month+day) or by year+month (episode = day). Genre and content rating are set per show.
  The last two digits of an episode number count uploads on the same day (`e1401` = the 14th, first video that day),
  so two videos from one day never collide. For channels with at most one video per date, untick
  "Add a same-day counter" in the channel's settings to get `1115` (or `15` with year+month seasons) instead.
- **File names**: per channel, files can be named `s202202.e1401 - Title` (default) or `2022-02-14 - Title`.
  Season and episode numbers are always in the `Season` folder and the `.nfo`. With a date in front, Jellyfin treats
  the file as a dated episode and takes the numbers from the `.nfo`. A plain `Title` option isn't offered: Jellyfin's
  file-name parser reads titles like `… November 15th 2026 WEEKLY STREAM` as season 20, episode 26, and a season from the
  file name overrides both the folder and the `.nfo`.
- **Episode metadata** (per channel): `.nfo` file only (default, fastest), `.nfo` + tags inside the video, or tags
  only. Writing tags into the video means ffmpeg rewrites the whole file once more, which takes a while for
  multi-hour videos.
- **Download history**: ytdl-sub records every downloaded video in `.ytdl-sub-<channel>-download-archive.json`
  in the show's folder and skips those videos later, even if you delete the files. It never checks what's actually in
  the library. On the Channels tab, **Re-download deleted videos…** forgets only the videos whose files are gone, so
  the next run fetches just those. **Reset download history…** forgets everything: the next run downloads the whole
  channel again and replaces existing files. Both keep a `.bak-<date>` backup of the history file.
- **Files per video**: the video, its `.nfo` and a `-thumb.jpg` thumbnail. `.info.json` files (raw YouTube metadata,
  not used by Jellyfin) are off by default; turn them on in Settings if you want them. Videos stay directly in the
  `Season` folders: Jellyfin's code describes episodes nested in their own subfolders as "not officially supported".
- **Chapter markers** (Settings): embedding chapters is yt-dlp's `Adding metadata to "…"` step, another full rewrite
  of each video that has chapters. Switch it off to save time if you don't use chapters in Jellyfin.
- **Episode metadata inside the video**: per channel, you can skip the per-episode `.nfo` files. The episode
  number, title, description, air date and genre are stored as tags in the `.mp4`, and the season comes from the
  `Season` folder. (MP4 stores its season/episode-number tags in one byte, so date-based numbers like 202202 can't
  go there; the episode number is stored in the text `episode_id` tag instead.) One `tvshow.nfo` per show is still
  written for the show's genre and rating. This mode always uses numbered file names: Jellyfin re-reads the file
  name after the embedded tags, and a date-named file would lose its episode number. In Jellyfin, enable **Prefer embedded episode information over filenames**
  and **Prefer embedded titles over filenames** for the library.
- **Air date from the title**: for channels that re-upload streams or broadcasts, a channel can take its date from
  the video title (`November 15th 2026`, `Nov 15, 2026`, `15th of November 2026`, `2026-11-15`) instead of the
  YouTube upload date. The date drives the season, episode and the Jellyfin "aired" date. Titles without a date
  fall back to the upload date.
- **Download modes** per channel:
  - *Only new videos*: on the first run, takes only the last N days, then adds every new upload and never deletes anything. This is the default and the best fit for daily runs.
  - *Everything*: downloads the full back catalogue **in batches** (default 5 videos), newest first
    working backwards (or oldest first, per channel).
    Each batch is looked up, downloaded and moved into the library before the next one starts, and
    batches repeat until the channel is caught up. Videos appear in Jellyfin as they finish rather
    than after the whole channel has been processed. Stopping is safe; the next run resumes.
  - *Rolling window*: keeps only the last N days (or the last N videos) and deletes older ones. Useful for news channels.
- **Skip Shorts and livestreams**: on by default. It uses the channel's `/videos` tab.
- **Daily schedule** via Windows Task Scheduler. The app doesn't need to be open. If the PC was off or asleep at the scheduled time, the run happens when it comes back. Each run is logged.
- **Quick download** tab: paste a YouTube video or Shorts URL and download just that, straight through yt-dlp,
  separate from your channels and batches (Best / 1440p / 1080p / 720p / MP3 audio, to a folder of your choice,
  with a queue for several URLs).
- **Stop after current video** on the Run & Schedule tab: lets the video that's downloading finish (download,
  merge, move into the library), then stops the rest of the batch. **Stop** still stops immediately.
- **Run now, Dry run, or Download selected**, with a live log and a **Current batch** panel: which video is
  downloading (stage, MB downloaded, speed, progress bar), which are done, and which are up next. The log only
  follows new output while it's scrolled to the bottom, so you can scroll up and read.
- **Jellyfin library refresh** after each run (optional; needs an API key).
- **One-click setup**: downloads `ytdl-sub.exe`, `yt-dlp.exe`, `ffmpeg.exe`, `ffprobe.exe` and `deno.exe` (the JavaScript runtime yt-dlp now needs for YouTube). It can also update ytdl-sub weekly before scheduled runs, because YouTube changes often break old yt-dlp versions.
- Video quality presets (Max 480p – 2160p / best), a cookies.txt option, throttle protection, and a cap on downloads per run.

## Download

Download `ytdl-sub-win-gui-<version>.zip` from the
[Releases page](https://github.com/murderbymodem/ytdl-sub-win-gui/releases), extract it anywhere (for example
`C:\`), and run `ytdl-sub-win-gui\ytdl-sub-win-gui.exe`. The zip contains a single `ytdl-sub-win-gui` folder
because the app creates its `data` folder next to the `.exe` and should have a folder of its own. No Python needed.

Each release is built from this repository's source by GitHub Actions (see the build log linked from the
release), and the release lists SHA-256 checksums of the zip and the `.exe`. The `.exe` isn't code-signed, so Windows
SmartScreen may warn on first launch ("Windows protected your PC" → **More info** → **Run anyway**).

## Running it

From source (**Python 3.10 – 3.13**; 3.14+ may lack prebuilt PySide6/PyYAML packages and fail with
"Microsoft Visual C++ 14.0 or greater is required"):

```bat
pip install -r requirements.txt
python launcher.py
```

As a standalone `.exe`: run `build.bat`. It produces `dist\ytdl-sub-win-gui.exe` (no console window, no Python needed on the target PC).

First launch:
1. Accept the prompt to download ytdl-sub and ffmpeg. You can also set the paths yourself in **Settings**.
2. In **Settings**, choose the **Jellyfin library folder**, e.g. `D:\Media\YouTube`.
3. On **Channels**, click **Add channel…** and paste the channel URL, e.g. `https://www.youtube.com/@novapbs`.
4. Optional: click **Dry run** to check everything, then **Run now**.
5. On **Run & Schedule**, tick *Download new videos automatically every day at…*, pick a time, and click **Apply schedule**.

**Upgrading from the earlier name (`ytdl-sub-gui`):** put `ytdl-sub-win-gui.exe` in the same folder as the
old `.exe` and delete the old one. The `data` folder (channels, settings, tools) is used as is. Open the app
once: it replaces the old "ytdl-sub-gui daily download" scheduled task with the new one.

## Jellyfin setup

1. In Dashboard → Libraries, add a library with content type **Shows**, pointing at the same folder.
2. In that library's settings, the **Nfo** metadata reader is enabled by default; keep it on. Turn off the online metadata downloaders (TheTVDB / TheMovieDb) and image fetchers for this library. Otherwise Jellyfin may match a channel to an unrelated real TV show.
3. Optional: in Dashboard → API Keys, create a key and enter it in **Settings → Jellyfin**. New videos then appear right after each run.

## How it works

**Portable:** everything the app writes lives in a `data` folder next to `ytdl-sub-win-gui.exe`
(or next to `launcher.py` when running from source):

```
ytdl-sub-win-gui.exe
data\
    state.json          your channels and settings
    config.yaml, subscriptions.yaml   generated for ytdl-sub
    bin\                ytdl-sub.exe, deno.exe, ffmpeg.exe, ffprobe.exe
    logs\               run logs, crash.log, ytdl-sub error logs
    working\            temporary downloads (moved into your library when done)
```

To move or back up the app, copy the `.exe` together with its `data` folder. If the app folder
isn't writable (e.g. under `C:\Program Files`), the app falls back to `%APPDATA%\ytdl-sub-win-gui`.
Settings from older versions stored in `%APPDATA%` are copied into `data` automatically on first start.

Before every run the app regenerates:
- `config.yaml`: working directory, ffmpeg paths, log settings, and a `gui_base` preset (library folder, cookies, max downloads, throttle).
- `subscriptions.yaml`: one preset group per channel, for example
  ```yaml
  "Jellyfin TV Show by Date | season_by_year__episode_by_month_day | Max 1080p | Only Recent Archive | gui_base":
    "~NOVA PBS":
      url: "https://www.youtube.com/@novapbs/videos"
      tv_show_genre: "Documentaries"
      tv_show_content_rating: "TV-PG"
      only_recent_date_range: "14days"
  ```
  (Settings → *Preview generated ytdl-sub YAML* shows the actual output.)

Then it runs `ytdl-sub --config config.yaml sub subscriptions.yaml`. ytdl-sub keeps a download archive per show, so later runs only fetch videos it hasn't seen.

The scheduled task is named **"ytdl-sub-win-gui daily download"**. It runs `ytdl-sub-win-gui.exe --headless` as your user, while you're signed in. Logs go to `data\logs\`. If you move the app folder, click **Apply schedule** again so the task points to the new location.

## Tips

- When YouTube blocks or rate-limits (bot check, "rate-limited", HTTP 429), ytdl-sub would carry on with older
  videos, so batches would skip ahead. The app stops instead, waits (default 60 minutes, shown in the Current batch
  panel), and resumes with the blocked videos first, up to 3 times per run (Settings). Unavailable or members-only
  videos are still just skipped.
- If YouTube shows "Sign in to confirm you're not a bot", give yt-dlp a signed-in YouTube session. Easiest:
  sign in to YouTube in Firefox and pick **Settings → Cookies from browser → Firefox**. Chrome/Edge must be fully
  closed and newer versions often can't be read; for those, export a `cookies.txt` instead (yt-dlp's wiki
  "Exporting YouTube cookies": use a private window, export, then close it) and set it as the **Cookies file**.
  A secondary Google account is safer, since YouTube can restrict accounts used for bulk downloading.
- Videos are processed one at a time; batch size doesn't make downloads run in parallel. After downloading,
  each video is rewritten by ffmpeg one or more times (merge, chapters, tags), so long videos spend a few minutes
  in post-processing. That's disk speed, not the network: keep the working folder on a fast drive (SSD).
- *Everything* mode works through a big channel batch by batch in a single run, which can take many hours. A scheduled run picks up where the last one stopped.
- The warning "No supported JavaScript runtime could be found" means deno is missing. Click **Download / update ytdl-sub, deno and ffmpeg** in Settings.
- Keep throttle protection on. Very fast downloading is the easiest way to get rate-limited.

## Making a release

1. Merge the changes you want to release into `main`.
2. On GitHub: **Releases → Draft a new release**, create a new tag such as `v0.1.2` on `main` (`0.1.2` without
   the `v` works too), write notes (or use **Generate release notes**), and **Publish**.
3. The Build workflow runs for that tag, builds the app with that version number, and attaches
   `ytdl-sub-win-gui-<tag>.zip` and `SHA256SUMS.txt` to the release within a few minutes.

The version in `ytdlsub_win_gui/__init__.py` is only used when running from source; release builds take it
from the tag. Always use a new tag: re-using a deleted release's tag rebuilds that tag's old commit.

## Development

The app icon (`assets/icon.ico`, `assets/icon.png`) is generated by `tools/make_icon.py` (needs Pillow):
edit the colours or shapes there and run `python tools/make_icon.py` to regenerate it.

```
ytdlsub_win_gui/
  models.py     settings + subscription dataclasses, JSON persistence
  configgen.py  state -> ytdl-sub config.yaml / subscriptions.yaml
  runner.py     command building, headless run, Jellyfin refresh
  scheduler.py  Windows Task Scheduler via PowerShell
  tools.py      download ytdl-sub.exe / ffmpeg
  gui.py        PySide6 UI
tests/          pytest; also loads generated YAML in ytdl-sub if it's installed
```

```bat
pip install pytest ytdl-sub
python -m pytest tests
```
