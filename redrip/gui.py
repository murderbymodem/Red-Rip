"""PySide6 main window."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Qt, QThread, QTime, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QListWidget, QPlainTextEdit, QProgressBar, QProgressDialog, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QTabWidget, QTimeEdit, QVBoxLayout, QWidget,
)

from . import __version__, archive, configgen, quick, runner, scheduler, tools
from .models import (
    ARCHIVE_ORDERS, COOKIE_BROWSERS, DATE_SOURCES, FILE_NAMINGS, METADATA_MODES, CONTENT_RATINGS, MODE_RECENT, MODES, QUALITY_PRESETS, SEASON_ORDERINGS, AppState,
    Subscription, app_dir, logs_dir,
)

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def path_row(edit: QLineEdit, parent: QWidget, mode: str, caption: str, filt: str = "") -> QWidget:
    """A line edit with a Browse... button. mode: 'dir' or 'file'."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    btn = QPushButton("Browse…")

    def browse():
        if mode == "dir":
            p = QFileDialog.getExistingDirectory(parent, caption, edit.text())
        else:
            p, _ = QFileDialog.getOpenFileName(parent, caption, edit.text(), filt)
        if p:
            edit.setText(os.path.normpath(p))

    btn.clicked.connect(browse)
    lay.addWidget(edit, 1)
    lay.addWidget(btn)
    return w


# --------------------------------------------------------------------------- dialogs

class SubscriptionDialog(QDialog):
    def __init__(self, parent: QWidget, sub: Subscription | None, existing_names: set[str]):
        super().__init__(parent)
        self.setWindowTitle("Edit channel" if sub else "Add channel")
        self.setMinimumWidth(560)
        self.existing_names = existing_names
        sub = sub or Subscription(name="", urls=[])

        self.name = QLineEdit(sub.name)
        self.name.setPlaceholderText("Show name as it will appear in Jellyfin")
        self.urls = QPlainTextEdit("\n".join(sub.urls))
        self.urls.setPlaceholderText("https://www.youtube.com/@ChannelHandle\n(one URL per line; extra URLs merge into the same show)")
        self.urls.setFixedHeight(80)
        self.videos_only = QCheckBox("Skip Shorts and livestreams (use the channel's Videos tab)")
        self.videos_only.setChecked(sub.videos_only)

        self.mode = QComboBox()
        for key, label in MODES.items():
            self.mode.addItem(label, key)
        self.mode.setCurrentIndex(max(0, self.mode.findData(sub.mode)))
        self.days = QSpinBox()
        self.days.setRange(1, 3650)
        self.days.setSuffix(" days")
        self.days.setValue(sub.recent_days)
        self.max_files = QSpinBox()
        self.max_files.setRange(0, 10000)
        self.max_files.setSpecialValueText("unlimited")
        self.max_files.setValue(sub.recent_max_files)
        self.order = QComboBox()
        for key, label in ARCHIVE_ORDERS.items():
            self.order.addItem(label, key)
        self.order.setCurrentIndex(max(0, self.order.findData(sub.archive_order)))
        self.date_source = QComboBox()
        for key, label in DATE_SOURCES.items():
            self.date_source.addItem(label, key)
        self.date_source.setCurrentIndex(max(0, self.date_source.findData(sub.date_source)))
        self.date_source.setToolTip(
            "Use the title option for channels that re-upload streams or broadcasts: the air date "
            "in the title then drives the season/episode numbers and the Jellyfin 'aired' date.\n"
            "Recognised: 'November 15th 2026', 'Nov 15, 2026', '15th of November 2026', '2026-11-15'.")
        self.naming = QComboBox()
        for key, label in FILE_NAMINGS.items():
            self.naming.addItem(label, key)
        self.naming.setCurrentIndex(max(0, self.naming.findData(sub.file_naming)))
        self.metadata = QComboBox()
        for key, label in METADATA_MODES.items():
            self.metadata.addItem(label, key)
        self.metadata.setCurrentIndex(max(0, self.metadata.findData(sub.metadata_mode)))
        self.metadata.setToolTip(
            "Embedded-only needs two Jellyfin library settings (Dashboard → Libraries → this\n"
            "library → Manage library): 'Prefer embedded episode information over filenames'\n"
            "and 'Prefer embedded titles over filenames'.\n\n"
            "The episode number, title, description, air date and genre are stored in the .mp4.\n"
            "The season comes from the 'Season' folder (MP4 can't store numbers like 202202).\n"
            "One tvshow.nfo per show is still written for the show's genre and rating.")
        self.batch = QSpinBox()
        self.batch.setRange(2, 100)
        self.batch.setSuffix(" videos")
        self.batch.setValue(max(2, sub.batch_size))
        self.batch.setToolTip("How many videos to look up and download before moving them into "
                              "the library and starting the next batch. Smaller = videos show up "
                              "sooner, slightly more overhead. (2 is the minimum yt-dlp allows.)")

        self.genre = QLineEdit(sub.genre)
        self.rating = QComboBox()
        self.rating.setEditable(True)
        self.rating.addItems(CONTENT_RATINGS)
        self.rating.setCurrentText(sub.content_rating)
        self.season = QComboBox()
        for key, label in SEASON_ORDERINGS.items():
            self.season.addItem(label, key)
        self.season.setCurrentIndex(max(0, self.season.findData(sub.season_ordering)))
        self.suffix = QCheckBox("Add a same-day counter to episode numbers (111501 instead of 1115)")
        self.suffix.setChecked(sub.same_day_suffix)
        self.suffix.setToolTip(
            "The last two digits number videos dated the same day (01, 02, ...), so they never\n"
            "share an episode number. Untick it if a channel never has two videos with the same date.\n"
            "Changing this only affects videos downloaded from now on.")
        self.quality = QComboBox()
        self.quality.addItem("Use default (Settings)", "")
        for q in QUALITY_PRESETS:
            self.quality.addItem(q, q)
        self.quality.setCurrentIndex(max(0, self.quality.findData(sub.quality)))
        self.enabled = QCheckBox("Enabled")
        self.enabled.setChecked(sub.enabled)

        form = QFormLayout()
        form.addRow("Show name:", self.name)
        form.addRow("Channel / playlist URL(s):", self.urls)
        form.addRow("", self.videos_only)
        form.addRow("What to download:", self.mode)
        form.addRow("Date range:", self.days)
        form.addRow("Keep at most:", self.max_files)
        form.addRow("Order:", self.order)
        form.addRow("Batch size:", self.batch)
        form.addRow("Genre (Jellyfin):", self.genre)
        form.addRow("Content rating:", self.rating)
        form.addRow("Season / episode numbering:", self.season)
        form.addRow("", self.suffix)
        form.addRow("Air date from:", self.date_source)
        form.addRow("File names:", self.naming)
        form.addRow("Episode metadata:", self.metadata)
        form.addRow("Video quality:", self.quality)
        form.addRow("", self.enabled)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: gray;")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.hint)
        lay.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self._update_mode)
        self.metadata.currentIndexChanged.connect(self._update_naming)
        self._update_naming()
        self._update_mode()

    def _update_naming(self):
        """Embedded-only metadata needs numbered file names (see Subscription.effective_file_naming)."""
        embedded = self.metadata.currentData() == "embedded"
        if embedded:
            self.naming.setCurrentIndex(self.naming.findData("numbered"))
        self.naming.setEnabled(not embedded)
        self.naming.setToolTip(
            "With metadata only inside the video, Jellyfin re-reads season/episode from the file\n"
            "name, so files must be named s2026.e111501 - Title." if embedded else
            "Season/episode are written to the .nfo and the Season folder. A date in front\n"
            "makes Jellyfin treat it as a dated episode; the .nfo supplies the numbers.")

    def _update_mode(self):
        mode = self.mode.currentData()
        self.days.setEnabled(mode != "all")
        self.max_files.setEnabled(mode == MODE_RECENT)
        self.batch.setEnabled(mode == "all")
        self.order.setEnabled(mode == "all")
        self.hint.setText({
            "all": "Downloads the whole channel a batch at a time: each batch is "
                   "downloaded and moved into the library before the next one starts, and runs "
                   "continue batch after batch until the channel is caught up. Stopping is safe; "
                   "the next run resumes where it left off.",
            "recent_archive": "First run grabs only videos from the last N days. Every later run "
                              "adds new uploads. Nothing is ever deleted — ideal for daily runs.",
            "recent": "Keeps a rolling window: videos older than N days (or beyond the max count) "
                      "are deleted from the library. Good for news channels.",
        }[mode])

    def accept(self):
        name = self.name.text().strip()
        urls = [u.strip() for u in self.urls.toPlainText().splitlines() if u.strip()]
        if not name:
            QMessageBox.warning(self, "Missing name", "Please enter a show name.")
            return
        if name in self.existing_names:
            QMessageBox.warning(self, "Duplicate", f"A channel named '{name}' already exists.")
            return
        if any(c in name for c in '<>:"/\\|?*'):
            QMessageBox.warning(self, "Invalid name", 'The name cannot contain < > : " / \\ | ? *')
            return
        if not urls or not all(u.lower().startswith(("http://", "https://")) for u in urls):
            QMessageBox.warning(self, "Invalid URL", "Enter at least one URL starting with https://")
            return
        super().accept()

    def result_subscription(self) -> Subscription:
        return Subscription(
            name=self.name.text().strip(),
            urls=[u.strip() for u in self.urls.toPlainText().splitlines() if u.strip()],
            enabled=self.enabled.isChecked(),
            genre=self.genre.text().strip() or "YouTube",
            content_rating=self.rating.currentText().strip() or "TV-14",
            mode=self.mode.currentData(),
            recent_days=self.days.value(),
            recent_max_files=self.max_files.value(),
            batch_size=self.batch.value(),
            archive_order=self.order.currentData(),
            date_source=self.date_source.currentData(),
            file_naming=self.naming.currentData(),
            metadata_mode=self.metadata.currentData(),
            season_ordering=self.season.currentData(),
            same_day_suffix=self.suffix.isChecked(),
            quality=self.quality.currentData(),
            videos_only=self.videos_only.isChecked(),
        )


class TextViewer(QDialog):
    def __init__(self, parent, title: str, text: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 600)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        view.setFont(QFont("Consolas", 9))
        lay = QVBoxLayout(self)
        lay.addWidget(view)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class ToolsWorker(QObject):
    progress = Signal(str, object, object)  # object: byte counts can exceed 32-bit int
    finished = Signal(str)  # empty string = success, else error message

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state

    def run(self):
        try:
            tools.install_all(self.state.settings, lambda l, d, t: self.progress.emit(l, d, t))
            self.finished.emit("")
        except Exception as exc:
            self.finished.emit(str(exc))


# --------------------------------------------------------------------------- main window

class MainWindow(QMainWindow):
    COLS = ["On", "Show name", "URL", "Download", "Genre", "Quality"]
    log_line = Signal(str)
    sched_status_text = Signal(str)
    tools_progress = Signal(str, object, object)
    tools_finished = Signal(str)
    q_update_done = Signal()
    q_log_line = Signal(str)

    def __init__(self):
        super().__init__()
        self.state = AppState.load()
        self.proc: QProcess | None = None
        self.log_file = None
        self._tools_thread = None
        self._tools_dlg = None
        self.setWindowTitle(f"Red-Rip {__version__} — YouTube to Jellyfin")
        self.resize(1050, 720)

        tabs = QTabWidget()
        tabs.addTab(self._build_channels_tab(), "Channels")
        tabs.addTab(self._build_run_tab(), "Run && Schedule")
        tabs.addTab(self._build_quick_tab(), "Quick download")
        tabs.addTab(self._build_settings_tab(), "Settings")
        self.setCentralWidget(tabs)
        self.log_line.connect(self._append_log)
        self.sched_status_text.connect(self.sched_status.setText)
        self.tools_progress.connect(self._on_tools_progress)
        self.tools_finished.connect(self._on_tools_finished)
        self.q_log_line.connect(self._q_append)

        self._refresh_table()
        self._load_settings_into_form()
        QTimer.singleShot(200, self._first_run_check)

    # ---- Channels tab
    def _build_channels_tab(self) -> QWidget:
        w = QWidget()
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._edit_sub)
        self.table.itemChanged.connect(self._on_item_changed)

        add = QPushButton("Add channel…")
        edit = QPushButton("Edit…")
        remove = QPushButton("Remove")
        run_sel = QPushButton("Download selected now")
        add.clicked.connect(self._add_sub)
        edit.clicked.connect(self._edit_sub)
        remove.clicked.connect(self._remove_sub)
        run_sel.clicked.connect(lambda: self._start_run(dry_run=False, selected_only=True))
        redl = QPushButton("Re-download deleted videos…")
        redl.setToolTip("ytdl-sub skips every video it has downloaded before, even if you deleted the file.\n"
                        "This makes it forget only the videos whose files are gone.")
        redl.clicked.connect(self._forget_deleted)
        reset = QPushButton("Reset download history…")
        reset.setToolTip("Forget everything downloaded for this channel. The next run downloads the\n"
                         "whole channel again and replaces existing files.")
        reset.clicked.connect(self._reset_history)

        btns = QHBoxLayout()
        for b in (add, edit, remove):
            btns.addWidget(b)
        btns.addStretch(1)
        btns.addWidget(redl)
        btns.addWidget(reset)
        btns.addWidget(run_sel)

        info = QLabel(
            "Each channel becomes a TV show in your Jellyfin library: seasons by year, episodes "
            "by upload date, with poster, fanart, thumbnails and .nfo metadata. "
            "Point a Jellyfin <b>Shows</b> library at the folder set in Settings."
        )
        info.setWordWrap(True)
        lay = QVBoxLayout(w)
        lay.addWidget(info)
        lay.addWidget(self.table, 1)
        lay.addLayout(btns)
        return w

    def _refresh_table(self):
        selected = self._selected_rows()
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for sub in self.state.subscriptions:
            r = self.table.rowCount()
            self.table.insertRow(r)
            on = QTableWidgetItem()
            on.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            on.setCheckState(Qt.Checked if sub.enabled else Qt.Unchecked)
            self.table.setItem(r, 0, on)
            order = "newest first" if sub.archive_order != "oldest" else "oldest first"
            mode = {"all": f"Everything, {order} ({sub.batch_size}/batch)", "recent_archive": f"New (last {sub.recent_days}d)",
                    "recent": f"Rolling {sub.recent_days}d"}[sub.mode]
            vals = [sub.name, "  ".join(sub.urls), mode, sub.genre,
                    sub.quality or f"Default ({self.state.settings.quality})"]
            for c, v in enumerate(vals, start=1):
                self.table.setItem(r, c, QTableWidgetItem(v))
        for r in selected:
            if r < self.table.rowCount():
                self.table.selectionModel().select(
                    self.table.model().index(r, 0),
                    self.table.selectionModel().SelectionFlag.Select
                    | self.table.selectionModel().SelectionFlag.Rows)
        self.table.blockSignals(False)

    def _on_item_changed(self, item: QTableWidgetItem):
        if item.column() == 0:
            self.state.subscriptions[item.row()].enabled = item.checkState() == Qt.Checked
            self.state.save()

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def _add_sub(self):
        dlg = SubscriptionDialog(self, None, {s.name for s in self.state.subscriptions})
        if dlg.exec():
            self.state.subscriptions.append(dlg.result_subscription())
            self.state.save()
            self._refresh_table()

    def _edit_sub(self, *_):
        rows = self._selected_rows()
        if not rows:
            return
        sub = self.state.subscriptions[rows[0]]
        names = {s.name for s in self.state.subscriptions} - {sub.name}
        dlg = SubscriptionDialog(self, sub, names)
        if dlg.exec():
            self.state.subscriptions[rows[0]] = dlg.result_subscription()
            self.state.save()
            self._refresh_table()

    def _archive_for_selected(self):
        """(subscription, archive path) for the single selected channel, or None after telling the user."""
        rows = self._selected_rows()
        if len(rows) != 1:
            QMessageBox.information(self, "Select a channel", "Select one channel first.")
            return None
        if self.proc is not None:
            QMessageBox.information(self, "Busy", "Wait for the current download to finish (or stop it) first.")
            return None
        self._save_settings_from_form()
        sub = self.state.subscriptions[rows[0]]
        path = archive.find_archive(self.state, sub)
        if path is None:
            QMessageBox.information(
                self, "No download history",
                f"No download history was found for '{sub.name}' in\n{self.state.settings.library_dir}\n\n"
                "Nothing has been downloaded for it yet, or the library folder setting changed.")
            return None
        return sub, path

    def _forget_deleted(self):
        found = self._archive_for_selected()
        if not found:
            return
        sub, path = found
        try:
            info = archive.inspect(path)
        except Exception as exc:
            QMessageBox.critical(self, "Download history", f"Could not read {path}:\n{exc}")
            return
        if not info.missing:
            QMessageBox.information(self, "Nothing to re-download",
                                    f"All {info.total} recorded videos for '{sub.name}' are still on disk.")
            return
        if QMessageBox.question(
            self, "Re-download deleted videos",
            f"{len(info.missing)} of {info.total} recorded videos for '{sub.name}' are no longer on disk.\n\n"
            "Forget them so the next run downloads them again? Their leftover .nfo/thumbnail files "
            "are removed too. Videos still on disk are not touched."
        ) != QMessageBox.Yes:
            return
        try:
            count, backup = archive.forget_missing(path)
        except Exception as exc:
            QMessageBox.critical(self, "Download history", f"Could not update {path}:\n{exc}")
            return
        note = ""
        if sub.mode != "all":
            note = (f"\n\nNote: this channel only downloads videos from the last {sub.recent_days} days, "
                    "so older deleted videos won't come back unless you switch it to 'Everything'.")
        QMessageBox.information(self, "Done",
                                f"Forgot {count} deleted videos. They'll be downloaded on the next run.\n\n"
                                f"Backup of the old history: {backup.name}{note}")

    def _reset_history(self):
        found = self._archive_for_selected()
        if not found:
            return
        sub, path = found
        if QMessageBox.question(
            self, "Reset download history",
            f"Forget ALL downloads for '{sub.name}'?\n\n"
            "ytdl-sub doesn't look at what's already in your library: the next run downloads every "
            "video again and replaces the existing files.\n\n"
            "To only get back videos you deleted, use 'Re-download deleted videos' instead.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            backup = archive.reset(path)
        except Exception as exc:
            QMessageBox.critical(self, "Download history", f"Could not reset {path}:\n{exc}")
            return
        QMessageBox.information(self, "Done", f"Download history reset. Backup: {backup.name}")

    def _remove_sub(self):
        rows = self._selected_rows()
        if not rows:
            return
        names = ", ".join(self.state.subscriptions[r].name for r in rows)
        if QMessageBox.question(
            self, "Remove", f"Remove {names}?\n\nAlready-downloaded videos stay on disk."
        ) != QMessageBox.Yes:
            return
        for r in reversed(rows):
            del self.state.subscriptions[r]
        self.state.save()
        self._refresh_table()

    # ---- Run & Schedule tab
    def _build_run_tab(self) -> QWidget:
        w = QWidget()
        sched = QGroupBox("Daily schedule (Windows Task Scheduler)")
        self.sched_enabled = QCheckBox("Download new videos automatically every day at")
        self.sched_time = QTimeEdit()
        self.sched_time.setDisplayFormat("HH:mm")
        apply_btn = QPushButton("Apply schedule")
        apply_btn.clicked.connect(self._apply_schedule)
        self.sched_status = QLabel()
        self.sched_status.setStyleSheet("color: gray;")
        note = QLabel("Runs in the background while you're signed in to Windows — the app itself "
                      "doesn't need to be open. If the PC was off or asleep, the run happens as soon "
                      "as it's back.")
        note.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self.sched_enabled)
        row.addWidget(self.sched_time)
        row.addStretch(1)
        row.addWidget(apply_btn)
        sl = QVBoxLayout(sched)
        sl.addLayout(row)
        sl.addWidget(self.sched_status)
        sl.addWidget(note)
        if not scheduler.is_supported():
            sched.setEnabled(False)

        self.run_btn = QPushButton("▶  Run now")
        self.dry_btn = QPushButton("Dry run (preview, no downloads)")
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setEnabled(False)
        self.run_btn.clicked.connect(lambda: self._start_run(dry_run=False))
        self.dry_btn.clicked.connect(lambda: self._start_run(dry_run=True))
        self.stop_btn.clicked.connect(self._stop_run)
        self.stop_after_btn = QPushButton("■  Stop after current video")
        self.stop_after_btn.setToolTip("Let the video that's downloading now finish (download, merge, move into\n"
                                       "the library), then stop and skip the rest of the batch.")
        self.stop_after_btn.setEnabled(False)
        self.stop_after_btn.clicked.connect(self._stop_after_current)
        logs_btn = QPushButton("Open logs folder")
        logs_btn.clicked.connect(lambda: open_path(logs_dir()))
        last_btn = QPushButton("View last scheduled log")
        last_btn.clicked.connect(self._view_last_scheduled_log)
        btns = QHBoxLayout()
        for b in (self.run_btn, self.dry_btn, self.stop_btn, self.stop_after_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        btns.addWidget(last_btn)
        btns.addWidget(logs_btn)

        prog = QGroupBox("Current batch")
        self.p_title = QLabel("Not running")
        self.p_title.setStyleSheet("font-weight: bold;")
        self.p_stage = QLabel("")
        self.p_stage.setWordWrap(True)
        self.p_bar = QProgressBar()
        self.p_bar.setRange(0, 1000)
        self.p_bar.setTextVisible(False)
        self.p_bar.setMaximumHeight(10)
        self.p_bar.hide()
        self.p_list = QListWidget()
        self.p_list.setMaximumHeight(140)
        self.p_list.setToolTip("Videos in this batch, in download order:\n"
                               "▶ downloading now   ✓ done   · up next   ↷ skipped   ✗ failed")
        pl = QVBoxLayout(prog)
        pl.addWidget(self.p_title)
        pl.addWidget(self.p_stage)
        pl.addWidget(self.p_bar)
        pl.addWidget(self.p_list)
        self.progress = runner.ProgressTracker()
        self._size_cache: dict[str, Path | None] = {}
        self._last_bytes: tuple[float, int] | None = None
        self.cooldown_timer = QTimer(self)
        self.cooldown_timer.setInterval(1000)
        self.cooldown_timer.timeout.connect(self._tick_cooldown)
        self.p_timer = QTimer(self)
        self.p_timer.setInterval(1000)
        self.p_timer.timeout.connect(self._render_progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setMaximumBlockCount(20000)

        lay = QVBoxLayout(w)
        lay.addWidget(sched)
        lay.addLayout(btns)
        lay.addWidget(prog)
        lay.addWidget(self.log, 1)
        return w

    def _refresh_schedule_status(self):
        def work():
            try:
                text = scheduler.status()
            except Exception as exc:
                text = f"Could not query Task Scheduler: {exc}"
            self.sched_status_text.emit(text)
        threading.Thread(target=work, daemon=True).start()

    def _apply_schedule(self):
        s = self.state.settings
        s.schedule_enabled = self.sched_enabled.isChecked()
        s.schedule_time = self.sched_time.time().toString("HH:mm")
        try:
            if s.schedule_enabled:
                errors = configgen.validate(self.state)
                if errors and QMessageBox.question(
                    self, "Configuration problems",
                    "Scheduled runs will fail until these are fixed:\n\n• " + "\n• ".join(errors)
                    + "\n\nSchedule anyway?") != QMessageBox.Yes:
                    return
                scheduler.install(s.schedule_time)
            else:
                scheduler.uninstall()
        except Exception as exc:
            QMessageBox.critical(self, "Task Scheduler", f"Could not update the scheduled task:\n{exc}")
            return
        self.state.save()
        self._refresh_schedule_status()

    def _view_last_scheduled_log(self):
        logs = sorted(logs_dir().glob("scheduled_*.log"), key=lambda p: p.stat().st_mtime)
        if not logs:
            QMessageBox.information(self, "Logs", "No scheduled run has happened yet.")
            return
        TextViewer(self, logs[-1].name, logs[-1].read_text(encoding="utf-8", errors="replace")).exec()

    def _append_log(self, text: str):
        # Only follow new output while the view is at the bottom, so you can scroll up and
        # read without being yanked back down. Scrolling to the bottom resumes following.
        sb = self.log.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 3
        cursor = QTextCursor(self.log.document())  # separate cursor: keeps the user's selection
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        if at_bottom:
            sb.setValue(sb.maximum())

    def _start_run(self, dry_run: bool, selected_only: bool = False):
        if self.proc is not None or self.cooldown_timer.isActive():
            QMessageBox.information(self, "Busy", "A download is already running (or waiting to resume).")
            return
        self._save_settings_from_form()
        errors = configgen.validate(self.state)
        if errors:
            QMessageBox.warning(self, "Can't run yet", "• " + "\n• ".join(errors))
            return
        match = None
        if selected_only:
            rows = self._selected_rows()
            if not rows:
                QMessageBox.information(self, "Select channels", "Select one or more channels first.")
                return
            match = [self.state.subscriptions[r].name for r in rows]
            disabled = [n for r, n in zip(rows, match) if not self.state.subscriptions[r].enabled]
            if disabled:
                QMessageBox.information(self, "Disabled", "Enable these first: " + ", ".join(disabled))
                return

        runner.prune_logs()
        log_path = runner.new_log_path("dryrun" if dry_run else "manual")
        self.log_file = open(log_path, "w", encoding="utf-8", errors="replace")
        self.log.clear()
        self._dry = dry_run
        self._stopped = False
        self._batch = 0
        self._size_cache = {}
        self._block_waits = 0
        self._stop_after_pending = False
        self._stop_after_mark = 0
        self._launch(match)

    def _launch(self, match: list[str] | None):
        """Start one ytdl-sub invocation (one batch)."""
        self._batch += 1
        self._current_match = match
        self._block_stop = False
        self.progress = runner.ProgressTracker()
        self._last_bytes = None
        self.p_timer.start()
        cmd = runner.build_command(self.state, dry_run=self._dry, match=match)
        header = ""
        if self._batch > 1:
            header = (f"\n=== Batch {self._batch}: continuing full archive for "
                      f"{', '.join(match or [])} ===\n")
        header += f"$ {subprocess.list2cmdline(cmd)}\n\n"
        self._log_write(header)
        self.tracker = runner.BatchTracker()

        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(str(app_dir()))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PATH", runner.child_env()["PATH"])
        self.proc.setProcessEnvironment(env)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read_proc)
        self.proc.finished.connect(self._proc_finished)
        self.proc.errorOccurred.connect(self._proc_error)
        self.proc.start(cmd[0], cmd[1:])
        self._set_running(True)

    def _log_write(self, text: str):
        self._append_log(text)
        if self.log_file:
            self.log_file.write(text)
            self.log_file.flush()

    def _read_proc(self):
        if not self.proc:
            return
        text = ANSI_RE.sub("", bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace"))
        text = text.replace("\r\n", "\n")
        self.tracker.feed(text)
        self.progress.feed(text)
        self._log_write(text)
        if (self._stop_after_pending and self.proc is not None
                and self.progress.safe_points > self._stop_after_mark):
            # The video that was downloading is now in the library and recorded; stop here.
            self._stopped = True
            self._stop_after_pending = False
            self._log_write("\n=== Current video finished. Stopping the rest of the batch.\n")
            runner.kill_tree(self.proc.processId())
            self.proc.kill()
            return
        s = self.state.settings
        if self.tracker.blocked and s.pause_on_block and not self._block_stop and not self._dry:
            # yt-dlp would carry on with older videos; stop so the order is kept
            self._block_stop = True
            self._log_write(f"\n=== YouTube is blocking requests: {self.tracker.blocked}\n"
                            "=== Stopping now so it doesn't skip ahead to older videos.\n")
            runner.kill_tree(self.proc.processId())
            self.proc.kill()

    def _proc_error(self, err):
        if err == QProcess.FailedToStart:
            self._log_write(f"\nFailed to start ytdl-sub: {self.proc.errorString()}\n")
            self._proc_finished(-1, None)

    def _proc_finished(self, code, _status):
        if self.proc is None:
            return
        self._read_proc()
        self._log_write(f"\n=== ytdl-sub finished with exit code {code} ===\n")
        self.proc.deleteLater()
        self.proc = None

        if self._stop_after_pending:
            # The batch ended on its own while we were waiting for the current video: done.
            self._stopped = True
            self._stop_after_pending = False
        s = self.state.settings
        if self._block_stop and not self._stopped:
            self._block_waits += 1
            if self._block_waits <= max(0, s.block_max_retries):
                self._start_cooldown()
                return
            self._log_write(f"\n=== Still blocked after {self._block_waits - 1} waits; "
                            "giving up until the next run.\n")
            self._finish_run()
            return
        self._block_waits = 0

        # 'Everything' channels that stopped at their batch limit: run the next batch.
        if not self._dry and not self._stopped and self._batch < runner.MAX_BATCHES:
            more = self.tracker.next_batch(self.state)
            if more:
                self._launch(more)
                return
        self._finish_run()

    def _start_cooldown(self):
        minutes = max(1, self.state.settings.block_cooldown_min)
        self._resume_at = time.monotonic() + minutes * 60
        self._batch -= 1  # the blocked attempt doesn't count as a batch
        self._log_write(f"=== Waiting {minutes} minutes, then trying the same channels again "
                        f"(wait {self._block_waits} of {self.state.settings.block_max_retries}). "
                        "Press Stop to cancel.\n")
        self.cooldown_timer.start()
        self._tick_cooldown()

    def _tick_cooldown(self):
        left = int(self._resume_at - time.monotonic())
        if left <= 0:
            self.cooldown_timer.stop()
            self._log_write("\n=== Trying again\n")
            self._launch(self._current_match)  # newest-first, so the blocked videos come first
            return
        self.progress.current = None
        self.progress.stage = (f"Paused: YouTube is blocking requests. Trying again in "
                               f"{left // 60}:{left % 60:02d} (wait {self._block_waits} of "
                               f"{self.state.settings.block_max_retries})")
        self._render_progress()

    def _finish_run(self):
        if self.log_file:
            self.log_file.close()
            self.log_file = None
        self._set_running(False)
        self.progress.finish()
        if self._stopped:
            self.progress.stage = "stopped"
        self._render_progress()
        s = self.state.settings
        if not self._dry and s.jellyfin_refresh and s.jellyfin_api_key:
            def work():
                try:
                    self.log_line.emit(runner.refresh_jellyfin(s.jellyfin_url, s.jellyfin_api_key) + "\n")
                except Exception as exc:
                    self.log_line.emit(f"Jellyfin refresh failed: {exc}\n")
            threading.Thread(target=work, daemon=True).start()

    def _stop_run(self):
        if self.proc is None and self.cooldown_timer.isActive():
            self.cooldown_timer.stop()
            self._stopped = True
            self._log_write("\n=== Stopped while waiting\n")
            self._finish_run()
            return
        if self.proc:
            self._stopped = True
            self._log_write("\nStopping… (videos already moved into the library are kept)\n")
            runner.kill_tree(self.proc.processId())
            self.proc.kill()

    # ---- live progress panel
    @staticmethod
    def _fmt_bytes(n: float) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} GB"

    def _working_dir(self) -> Path:
        return Path(self.state.settings.working_dir or (app_dir() / "working"))

    def _render_progress(self):
        t = self.progress
        running = self.proc is not None
        if not t.channel:
            self.p_title.setText(f"Batch {self._batch}: starting…" if running else "Not running")
        else:
            pos = f" · video {t.position}" if t.position and t.current else ""
            self.p_title.setText(f"{t.channel} · batch {self._batch}{pos}")

        # Download progress from the files growing in the working folder
        detail, fraction = "", None
        if running and t.current and t.stage.startswith("downloading"):
            if t.current not in self._size_cache or self._size_cache[t.current] is None:
                self._size_cache[t.current] = runner.find_info_json(self._working_dir(), t.current)
            info = self._size_cache[t.current]
            if info is not None:
                done = runner.downloaded_bytes(info)
                total = runner.expected_size(info)
                now = time.monotonic()
                speed = ""
                if self._last_bytes and now > self._last_bytes[0] and done >= self._last_bytes[1]:
                    rate = (done - self._last_bytes[1]) / (now - self._last_bytes[0])
                    speed = f" · {self._fmt_bytes(rate)}/s"
                self._last_bytes = (now, done)
                detail = f" · {self._fmt_bytes(done)}" + (f" of ~{self._fmt_bytes(total)}" if total else "") + speed
                if total:
                    fraction = min(done / total, 1.0)
        else:
            self._last_bytes = None
        current = f"▶ {t.current} — " if t.current else ""
        if getattr(self, "_stop_after_pending", False) and self.proc is not None:
            current = current.replace(" — ", " — stopping after this video · ", 1) if current else ""
        self.p_stage.setText(f"{current}{t.stage}{detail}" if (t.stage or current) else "")
        self.p_bar.setVisible(fraction is not None)
        if fraction is not None:
            self.p_bar.setValue(int(fraction * 1000))

        marks = {runner.CURRENT: "▶", runner.DONE: "✓", runner.QUEUED: "·",
                 runner.SKIPPED: "↷", runner.FAILED: "✗"}
        rows = [f"{marks[i['status']]}  {i['title']}" for i in t.items]
        if rows != [self.p_list.item(k).text() for k in range(self.p_list.count())]:
            self.p_list.clear()
            self.p_list.addItems(rows)
            for k, i in enumerate(t.items):
                if i["status"] == runner.CURRENT:
                    self.p_list.scrollToItem(self.p_list.item(k))
        if not running:
            self.p_timer.stop()

    def _set_running(self, running: bool):
        self.run_btn.setEnabled(not running)
        self.dry_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.stop_after_btn.setEnabled(running)
        if not running:
            self.stop_after_btn.setText("■  Stop after current video")

    def _stop_after_current(self):
        t = self.progress
        if self.proc is None or t.phase != "download" or not t.current:
            # Nothing is downloading (looking up videos, between batches, or waiting
            # out a YouTube block): stopping now loses nothing.
            self._stop_run()
            return
        self._stop_after_mark = t.safe_points
        self._stop_after_pending = True
        self.stop_after_btn.setEnabled(False)
        self.stop_after_btn.setText("Stopping after current video…")
        self._log_write(f"\n=== Will stop after '{t.current}' is finished\n")
        self._render_progress()
    # ---- Quick download tab
    def _build_quick_tab(self) -> QWidget:
        w = QWidget()
        intro = QLabel("Download a single video or Short with yt-dlp. This is separate from your channels "
                       "and batches: the file is saved as-is (title as file name, no Jellyfin naming).")
        intro.setWordWrap(True)
        self.q_url = QLineEdit()
        self.q_url.setPlaceholderText("Paste a YouTube video or Shorts URL, e.g. https://www.youtube.com/shorts/…")
        self.q_url.returnPressed.connect(self._q_add)
        paste = QPushButton("Paste")
        paste.clicked.connect(lambda: self.q_url.setText(QApplication.clipboard().text().strip()))
        add = QPushButton("⬇  Download")
        add.clicked.connect(self._q_add)
        row = QHBoxLayout()
        row.addWidget(self.q_url, 1)
        row.addWidget(paste)
        row.addWidget(add)

        self.q_quality = QComboBox()
        for key, (label, _) in quick.QUALITIES.items():
            self.q_quality.addItem(label, key)
        self.q_quality.setCurrentIndex(max(0, self.q_quality.findData(self.state.settings.quick_quality)))
        self.q_folder = QLineEdit(self.state.settings.quick_folder or str(quick.default_folder()))
        opts = QFormLayout()
        opts.addRow("Quality:", self.q_quality)
        opts.addRow("Save to:", path_row(self.q_folder, w, "dir", "Quick download folder"))

        self.q_list = QListWidget()
        self.q_list.setToolTip("· queued   ▶ downloading   ✓ saved (double-click to open its folder)   ✗ failed/cancelled")
        self.q_list.itemDoubleClicked.connect(self._q_open_item)
        self.q_status = QLabel("Idle")
        self.q_bar = QProgressBar()
        self.q_bar.setRange(0, 1000)
        self.q_bar.setTextVisible(False)
        self.q_bar.setMaximumHeight(10)
        cancel = QPushButton("■  Cancel current")
        cancel.clicked.connect(self._q_cancel)
        clear = QPushButton("Clear queued")
        clear.clicked.connect(self._q_clear)
        open_dir = QPushButton("Open folder")
        open_dir.clicked.connect(lambda: open_path(Path(self.q_folder.text().strip() or quick.default_folder())))
        brow = QHBoxLayout()
        brow.addWidget(cancel)
        brow.addWidget(clear)
        brow.addStretch(1)
        brow.addWidget(open_dir)
        self.q_log = QPlainTextEdit()
        self.q_log.setReadOnly(True)
        self.q_log.setFont(QFont("Consolas", 9))
        self.q_log.setMaximumBlockCount(5000)

        self.q_items: list[dict] = []
        self.q_proc: QProcess | None = None
        self.q_progress = quick.QuickProgress()
        self._q_update_checked = False
        self.q_update_done.connect(self._q_next)

        lay = QVBoxLayout(w)
        lay.addWidget(intro)
        lay.addLayout(row)
        lay.addLayout(opts)
        lay.addWidget(self.q_list, 1)
        lay.addWidget(self.q_status)
        lay.addWidget(self.q_bar)
        lay.addLayout(brow)
        lay.addWidget(self.q_log, 1)
        return w

    def _q_add(self):
        url = self.q_url.text().strip()
        if not quick.is_url(url):
            QMessageBox.warning(self, "Quick download", "Paste a full video URL starting with https://")
            return
        s = self.state.settings
        if not s.ytdlp_path or not Path(s.ytdlp_path).exists():
            if sys.platform == "win32" and QMessageBox.question(
                    self, "yt-dlp needed",
                    "Quick download uses yt-dlp, which isn't installed yet.\n\nDownload the tools now?"
            ) == QMessageBox.Yes:
                self._download_tools()
            elif sys.platform != "win32":
                QMessageBox.information(self, "yt-dlp needed", "Set the yt-dlp path in Settings.")
            return
        folder = Path(self.q_folder.text().strip() or quick.default_folder())
        s.quick_folder = str(folder) if folder != quick.default_folder() else ""
        s.quick_quality = self.q_quality.currentData()
        self.state.save()
        item = {"url": url, "quality": s.quick_quality, "folder": folder, "status": "queued",
                "name": url, "file": None, "error": None}
        self.q_items.append(item)
        self.q_url.clear()
        self._q_render()
        if self.q_proc is None:
            self._q_next()

    def _q_next(self):
        if self.q_proc is not None:
            return
        item = next((i for i in self.q_items if i["status"] == "queued"), None)
        if item is None:
            self.q_status.setText("Idle")
            self.q_bar.setValue(0)
            return
        s = self.state.settings
        if s.auto_update_ytdlsub and not self._q_update_checked:
            # Once per app session: refresh a week-old yt-dlp first (YouTube breaks old versions)
            self._q_update_checked = True
            self.q_status.setText("Checking for a yt-dlp update…")

            def work():
                try:
                    msg = tools.update_ytdlp_if_stale(s)
                    if msg:
                        self.state.save()
                        self.q_log_line.emit(msg + "\n")
                except Exception as exc:
                    self.q_log_line.emit(f"yt-dlp update failed (using the current version): {exc}\n")
                self.q_update_done.emit()
            threading.Thread(target=work, daemon=True).start()
            return
        try:
            item["folder"].mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            item["status"], item["error"] = "failed", f"can't create folder: {exc}"
            self._q_render()
            self._q_next()
            return
        cmd = quick.build_command(s, item["url"], item["quality"], item["folder"])
        self.q_progress = quick.QuickProgress()
        self.q_current = item
        item["status"] = "current"
        self._q_append(f"\n$ {subprocess.list2cmdline(cmd)}\n")
        self.q_proc = QProcess(self)
        self.q_proc.setWorkingDirectory(str(item["folder"]))
        env = QProcessEnvironment.systemEnvironment()
        for k, v in runner.child_env().items():
            if k in ("PATH", "PYTHONIOENCODING", "PYTHONUTF8"):
                env.insert(k, v)
        self.q_proc.setProcessEnvironment(env)
        self.q_proc.setProcessChannelMode(QProcess.MergedChannels)
        self.q_proc.readyReadStandardOutput.connect(self._q_read)
        self.q_proc.finished.connect(self._q_finished)
        self.q_proc.errorOccurred.connect(self._q_error)
        self.q_proc.start(cmd[0], cmd[1:])
        self._q_render()

    def _q_read(self):
        if not self.q_proc:
            return
        text = ANSI_RE.sub("", bytes(self.q_proc.readAllStandardOutput()).decode("utf-8", "replace"))
        text = text.replace("\r\n", "\n")
        self.q_progress.feed(text)
        self._q_append(text)
        if self.q_progress.name:
            self.q_current["name"] = self.q_progress.name
        self._q_render()

    def _q_error(self, err):
        if err == QProcess.FailedToStart and self.q_proc is not None:
            self.q_current["error"] = f"couldn't start yt-dlp: {self.q_proc.errorString()}"
            self._q_finished(-1, None)

    def _q_finished(self, code, _status):
        if self.q_proc is None:
            return
        self._q_read()
        p, item = self.q_progress, self.q_current
        if item["status"] == "cancelled":
            pass
        elif p.file and code == 0:
            item["status"], item["file"] = "done", p.file
            item["name"] = Path(p.file).name
        else:
            item["status"] = "failed"
            item["error"] = item["error"] or p.error or f"yt-dlp exited with code {code}"
        self._q_append(f"=== {item['status']}: {item['file'] or item['error'] or ''}\n")
        self.q_proc.deleteLater()
        self.q_proc = None
        self._q_render()
        self._q_next()

    def _q_cancel(self):
        if self.q_proc is not None:
            self.q_current["status"] = "cancelled"
            runner.kill_tree(self.q_proc.processId())
            self.q_proc.kill()

    def _q_clear(self):
        self.q_items = [i for i in self.q_items if i["status"] != "queued"]
        self._q_render()

    def _q_open_item(self, list_item):
        idx = self.q_list.row(list_item)
        if 0 <= idx < len(self.q_items):
            i = self.q_items[idx]
            open_path(Path(i["file"]).parent if i["file"] else i["folder"])

    def _q_append(self, text: str):
        sb = self.q_log.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 3
        cursor = QTextCursor(self.q_log.document())
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        if at_bottom:
            sb.setValue(sb.maximum())

    def _q_render(self):
        marks = {"queued": "·", "current": "▶", "done": "✓", "failed": "✗", "cancelled": "✗"}
        rows = []
        for i in self.q_items:
            extra = {"failed": f" — failed: {i['error']}", "cancelled": " — cancelled",
                     "done": f" — saved to {Path(i['file']).parent}" if i["file"] else ""}.get(i["status"], "")
            rows.append(f"{marks[i['status']]}  {i['name']}{extra}")
        if rows != [self.q_list.item(k).text() for k in range(self.q_list.count())]:
            self.q_list.clear()
            self.q_list.addItems(rows)
        if self.q_proc is not None:
            p = self.q_progress
            pct = f" {p.percent:.1f}%" if p.percent is not None and p.stage.startswith("downloading") else ""
            detail = f" · {p.detail}" if p.detail and p.stage.startswith("downloading") else ""
            self.q_status.setText(f"▶ {self.q_current['name']} — {p.stage}{pct}{detail}")
            self.q_bar.setValue(int((p.percent or 0) * 10) if p.stage.startswith("downloading") else
                                (1000 if p.stage in ("merging video + audio", "adding metadata",
                                                     "converting to MP3", "done") else 0))

    def _build_settings_tab(self) -> QWidget:
        w = QWidget()
        self.f_library = QLineEdit()
        self.f_library.setPlaceholderText(r"e.g. D:\Media\YouTube  (add this folder as a Jellyfin 'Shows' library)")
        self.f_working = QLineEdit()
        self.f_working.setPlaceholderText("Optional. Temporary download folder (blank = app data folder)")
        self.f_ytdlsub = QLineEdit()
        self.f_ffmpeg = QLineEdit()
        self.f_ffprobe = QLineEdit()
        self.f_ytdlp = QLineEdit()
        self.f_ytdlp.setPlaceholderText("Used by the Quick download tab (installed by the button below)")
        self.f_deno = QLineEdit()
        self.f_deno.setPlaceholderText("JavaScript runtime yt-dlp needs for YouTube (installed by the button below)")
        self.f_quality = QComboBox()
        self.f_quality.addItems(QUALITY_PRESETS)
        self.f_cookies = QLineEdit()
        self.f_cookies.setPlaceholderText("Optional. Netscape cookies.txt — helps with age-restricted videos / bot checks")
        self.f_throttle = QCheckBox("Throttle protection (random pauses between downloads — recommended)")
        self.f_autoupdate = QCheckBox("Keep ytdl-sub up to date automatically (checked before scheduled runs, weekly)")
        self.f_maxdl = QSpinBox()
        self.f_maxdl.setRange(0, 10000)
        self.f_maxdl.setSpecialValueText("unlimited")
        self.f_maxdl.setToolTip("Applies to 'Only new videos' and 'Rolling window' channels. "
                                "'Everything' channels use their own batch size instead.")

        exe_filter = "Executables (*.exe);;All files (*)"
        paths = QGroupBox("Library && tools")
        pf = QFormLayout(paths)
        pf.addRow("Jellyfin library folder:", path_row(self.f_library, w, "dir", "Jellyfin library folder"))
        pf.addRow("Working folder:", path_row(self.f_working, w, "dir", "Working folder"))
        pf.addRow("ytdl-sub.exe:", path_row(self.f_ytdlsub, w, "file", "ytdl-sub executable", exe_filter))
        pf.addRow("ffmpeg.exe:", path_row(self.f_ffmpeg, w, "file", "ffmpeg", exe_filter))
        pf.addRow("ffprobe.exe:", path_row(self.f_ffprobe, w, "file", "ffprobe", exe_filter))
        pf.addRow("deno.exe:", path_row(self.f_deno, w, "file", "deno", exe_filter))
        pf.addRow("yt-dlp.exe:", path_row(self.f_ytdlp, w, "file", "yt-dlp", exe_filter))
        dl_btn = QPushButton("Download / update ytdl-sub, yt-dlp, deno and ffmpeg")
        dl_btn.clicked.connect(self._download_tools)
        pf.addRow("", dl_btn)

        dl = QGroupBox("Downloading")
        df = QFormLayout(dl)
        df.addRow("Default video quality:", self.f_quality)
        df.addRow("Max new videos per channel per run:", self.f_maxdl)
        df.addRow("Cookies file:", path_row(self.f_cookies, w, "file", "cookies.txt", "Text files (*.txt);;All files (*)"))
        self.f_cookie_browser = QComboBox()
        for key, label in COOKIE_BROWSERS.items():
            self.f_cookie_browser.addItem(label, key)
        self.f_cookie_browser.setToolTip(
            "Fixes YouTube's 'Sign in to confirm you're not a bot' by using the YouTube login of a\n"
            "browser on this PC. Sign in to YouTube in that browser first.\n\n"
            "Consider a secondary Google account: YouTube can restrict accounts used for bulk downloading.")
        df.addRow("Cookies from browser:", self.f_cookie_browser)
        df.addRow("", self.f_throttle)
        df.addRow("", self.f_autoupdate)
        self.f_infojson = QCheckBox("Keep a .info.json file next to each video (raw YouTube metadata; not used by Jellyfin)")
        df.addRow("", self.f_infojson)
        self.f_block = QCheckBox("When YouTube blocks or rate-limits, stop and wait instead of skipping ahead")
        self.f_block.setToolTip("On 'Sign in to confirm you're not a bot' or 'rate-limited' errors, ytdl-sub would\n"
                                "carry on with older videos. Instead, stop, wait, and resume in order.")
        self.f_block_min = QSpinBox()
        self.f_block_min.setRange(5, 720)
        self.f_block_min.setSuffix(" min")
        self.f_block_tries = QSpinBox()
        self.f_block_tries.setRange(0, 20)
        self.f_block_tries.setSuffix(" waits per run")
        brow = QWidget()
        bl = QHBoxLayout(brow)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(QLabel("Wait"))
        bl.addWidget(self.f_block_min)
        bl.addWidget(QLabel("before retrying, up to"))
        bl.addWidget(self.f_block_tries)
        bl.addStretch(1)
        df.addRow("", self.f_block)
        df.addRow("", brow)
        self.f_block.toggled.connect(brow.setEnabled)
        self.f_chapters = QCheckBox("Embed chapter markers (an extra rewrite of each video that has chapters)")
        df.addRow("", self.f_chapters)

        jf = QGroupBox("Jellyfin (optional) — refresh library after each run")
        self.f_jf_enabled = QCheckBox("Trigger a Jellyfin library scan after downloads")
        self.f_jf_url = QLineEdit()
        self.f_jf_key = QLineEdit()
        self.f_jf_key.setEchoMode(QLineEdit.Password)
        self.f_jf_key.setPlaceholderText("Dashboard → API Keys → +")
        test_btn = QPushButton("Test connection")
        test_btn.clicked.connect(self._test_jellyfin)
        jff = QFormLayout(jf)
        jff.addRow("", self.f_jf_enabled)
        jff.addRow("Server URL:", self.f_jf_url)
        jff.addRow("API key:", self.f_jf_key)
        jff.addRow("", test_btn)

        save_btn = QPushButton("Save settings")
        save_btn.clicked.connect(self._on_save_settings)
        preview_btn = QPushButton("Preview generated ytdl-sub YAML")
        preview_btn.clicked.connect(self._preview_yaml)
        folder_btn = QPushButton("Open app data folder")
        folder_btn.clicked.connect(lambda: open_path(app_dir()))
        bl = QHBoxLayout()
        bl.addWidget(save_btn)
        bl.addStretch(1)
        bl.addWidget(preview_btn)
        bl.addWidget(folder_btn)

        lay = QVBoxLayout(w)
        lay.addWidget(paths)
        lay.addWidget(dl)
        lay.addWidget(jf)
        lay.addStretch(1)
        credits = QLabel(
            f"Red-Rip {__version__} · "
            '<a href="https://github.com/murderbymodem/red-rip">github.com/murderbymodem/red-rip</a><br>'
            'Built on <a href="https://github.com/jmbannon/ytdl-sub">ytdl-sub</a> and '
            '<a href="https://github.com/yt-dlp/yt-dlp">yt-dlp</a>, with '
            '<a href="https://ffmpeg.org">FFmpeg</a> and <a href="https://deno.com">Deno</a>. '
            "Not affiliated with those projects.")
        credits.setTextFormat(Qt.RichText)
        credits.setOpenExternalLinks(True)
        credits.setWordWrap(True)
        credits.setStyleSheet("color: gray;")
        lay.addWidget(credits)
        lay.addLayout(bl)
        return w

    def _load_settings_into_form(self):
        s = self.state.settings
        self.f_library.setText(s.library_dir)
        self.f_working.setText(s.working_dir)
        self.f_ytdlsub.setText(s.ytdlsub_path)
        self.f_ffmpeg.setText(s.ffmpeg_path)
        self.f_ffprobe.setText(s.ffprobe_path)
        self.f_deno.setText(s.deno_path)
        self.f_ytdlp.setText(s.ytdlp_path)
        self.f_quality.setCurrentText(s.quality)
        self.f_cookies.setText(s.cookies_file)
        self.f_cookie_browser.setCurrentIndex(max(0, self.f_cookie_browser.findData(s.cookies_browser)))
        self.f_throttle.setChecked(s.throttle_protection)
        self.f_autoupdate.setChecked(s.auto_update_ytdlsub)
        self.f_chapters.setChecked(s.embed_chapters)
        self.f_infojson.setChecked(s.keep_info_json)
        self.f_block.setChecked(s.pause_on_block)
        self.f_block_min.setValue(s.block_cooldown_min)
        self.f_block_tries.setValue(s.block_max_retries)
        self.f_maxdl.setValue(s.max_downloads_per_run)
        self.f_jf_enabled.setChecked(s.jellyfin_refresh)
        self.f_jf_url.setText(s.jellyfin_url)
        self.f_jf_key.setText(s.jellyfin_api_key)
        self.sched_enabled.setChecked(s.schedule_enabled)
        self.sched_time.setTime(QTime.fromString(s.schedule_time, "HH:mm"))
        self._refresh_schedule_status()

    def _save_settings_from_form(self):
        s = self.state.settings
        s.library_dir = self.f_library.text().strip()
        s.working_dir = self.f_working.text().strip()
        s.ytdlsub_path = self.f_ytdlsub.text().strip()
        s.ffmpeg_path = self.f_ffmpeg.text().strip()
        s.ffprobe_path = self.f_ffprobe.text().strip()
        s.deno_path = self.f_deno.text().strip()
        s.ytdlp_path = self.f_ytdlp.text().strip()
        s.quality = self.f_quality.currentText()
        s.cookies_file = self.f_cookies.text().strip()
        s.cookies_browser = self.f_cookie_browser.currentData() or ""
        s.throttle_protection = self.f_throttle.isChecked()
        s.auto_update_ytdlsub = self.f_autoupdate.isChecked()
        s.embed_chapters = self.f_chapters.isChecked()
        s.keep_info_json = self.f_infojson.isChecked()
        s.pause_on_block = self.f_block.isChecked()
        s.block_cooldown_min = self.f_block_min.value()
        s.block_max_retries = self.f_block_tries.value()
        s.max_downloads_per_run = self.f_maxdl.value()
        s.jellyfin_refresh = self.f_jf_enabled.isChecked()
        s.jellyfin_url = self.f_jf_url.text().strip()
        s.jellyfin_api_key = self.f_jf_key.text().strip()
        self.state.save()
        self._refresh_table()

    def _on_save_settings(self):
        self._save_settings_from_form()
        self.statusBar().showMessage("Settings saved.", 3000)

    def _preview_yaml(self):
        self._save_settings_from_form()
        text = ("# ---- config.yaml\n" + configgen.dump(configgen.build_config(self.state))
                + "\n# ---- subscriptions.yaml\n" + configgen.dump(configgen.build_subscriptions(self.state)))
        TextViewer(self, "Generated ytdl-sub configuration", text).exec()

    def _test_jellyfin(self):
        try:
            msg = runner.test_jellyfin(self.f_jf_url.text().strip(), self.f_jf_key.text().strip())
            QMessageBox.information(self, "Jellyfin", msg)
        except Exception as exc:
            QMessageBox.warning(self, "Jellyfin", f"Connection failed:\n{exc}")

    def _download_tools(self):
        if sys.platform != "win32":
            QMessageBox.information(self, "Windows only", "Automatic download fetches Windows builds.")
            return
        if getattr(self, "_tools_thread", None) is not None:
            return  # already downloading
        self._save_settings_from_form()
        dlg = QProgressDialog(self)
        dlg.setWindowTitle("Downloading tools")
        dlg.setLabelText("Starting download…")
        dlg.setCancelButton(None)
        dlg.setRange(0, 0)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        self._tools_dlg = dlg

        thread = QThread(self)
        worker = ToolsWorker(self.state)
        worker.moveToThread(thread)
        # Relay through this window's own signals. A signal-to-signal connection is
        # delivered in the receiver's (GUI) thread. Connecting the worker straight to a
        # closure/method would run it in the worker thread, and touching widgets from
        # there crashes the app on Windows without any error.
        worker.progress.connect(self.tools_progress)  # signal -> signal: queued to GUI thread
        worker.finished.connect(self.tools_finished)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._tools_thread = (thread, worker)  # keep references alive
        thread.start()
        dlg.show()

    @Slot(str, object, object)
    def _on_tools_progress(self, label, done, total):
        dlg = self._tools_dlg
        if dlg is None:
            return
        text = f"Downloading {label}… {done / 1e6:.1f} MB"
        if total:
            text += f" / {total / 1e6:.1f} MB"
            dlg.setRange(0, 1000)
            dlg.setValue(int(done * 1000 / total))
        else:
            dlg.setRange(0, 0)
        dlg.setLabelText(text)

    @Slot(str)
    def _on_tools_finished(self, err):
        if self._tools_dlg is not None:
            self._tools_dlg.close()
            self._tools_dlg.deleteLater()
            self._tools_dlg = None
        thread, _worker = self._tools_thread
        thread.quit()
        thread.wait(5000)
        self._tools_thread = None
        if err:
            QMessageBox.critical(self, "Download failed", err)
        else:
            self.state.save()
            self._load_settings_into_form()
            QMessageBox.information(self, "Done", "ytdl-sub, yt-dlp, deno and ffmpeg are installed.")

    # ---- startup
    def _first_run_check(self):
        s = self.state.settings
        if scheduler.is_supported():
            def migrate():
                try:
                    msg = scheduler.migrate_old_task(s.schedule_enabled, s.schedule_time)
                except Exception as exc:
                    msg = f"Could not update the scheduled task from the old app name: {exc}"
                if msg:
                    self.log_line.emit(msg + "\n")
                    self._refresh_schedule_status()
            threading.Thread(target=migrate, daemon=True).start()
        if sys.platform == "win32" and not (s.ytdlsub_path and s.deno_path):
            if QMessageBox.question(
                self, "Welcome",
                "ytdl-sub, yt-dlp, deno and ffmpeg aren't set up yet.\n\nDownload them now (about 200 MB)?"
            ) == QMessageBox.Yes:
                self._download_tools()

    def closeEvent(self, event):
        busy = self.proc is not None or self.q_proc is not None
        if busy and QMessageBox.question(
            self, "Download running", "A download is still running. Stop it and quit?"
        ) != QMessageBox.Yes:
            event.ignore()
            return
        if self.proc is not None:
            self._stopped = True
            runner.kill_tree(self.proc.processId())
            self.proc.kill()
            self.proc.waitForFinished(3000)
        if self.q_proc is not None:
            self.q_current["status"] = "cancelled"
            runner.kill_tree(self.q_proc.processId())
            self.q_proc.kill()
            self.q_proc.waitForFinished(3000)
        self._save_settings_from_form()
        event.accept()


def _install_crash_logging() -> None:
    """The packaged .exe has no console, so record crashes to logs\\crash.log."""
    import faulthandler
    import traceback

    crash_path = logs_dir() / "crash.log"
    try:
        # Hard crashes (access violations inside Qt etc.) - Python-level tracebacks of all threads.
        global _crash_file
        _crash_file = open(crash_path, "a", encoding="utf-8")
        faulthandler.enable(_crash_file, all_threads=True)
    except OSError:
        pass

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            with open(crash_path, "a", encoding="utf-8") as f:
                f.write(f"\n--- unhandled exception ---\n{text}")
        except OSError:
            pass
        if QApplication.instance():
            QMessageBox.critical(None, "Unexpected error",
                                 f"{exc}\n\nDetails were saved to:\n{crash_path}")

    sys.excepthook = hook


_crash_file = None


def icon_path() -> Path:
    """assets/icon.ico from the source tree, or from inside the PyInstaller .exe."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / "icon.ico"


def _set_windows_app_id() -> None:
    """Own taskbar identity, so Windows shows our icon instead of grouping us under
    a generic host (e.g. python.exe when running from source)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("murderbymodem.Red-Rip")
        except Exception:
            pass


def run_gui() -> int:
    _install_crash_logging()
    _set_windows_app_id()  # must happen before any window exists
    app = QApplication(sys.argv)
    app.setApplicationName("Red-Rip")
    if icon_path().exists():
        app.setWindowIcon(QIcon(str(icon_path())))  # title bar, taskbar, and every dialog
    win = MainWindow()
    win.show()
    return app.exec()
