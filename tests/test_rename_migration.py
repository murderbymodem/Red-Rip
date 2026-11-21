import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from redrip import models  # noqa: E402


import pytest  # noqa: E402


@pytest.mark.parametrize("old_name", ["ytdl-sub-win-gui", "ytdl-sub-gui"])
def test_settings_migrate_from_old_app_name(tmp_path, monkeypatch, old_name):
    home = tmp_path / "home"
    old = home / ".config" / old_name                # %APPDATA%\<old name> on Windows
    (old / "bin").mkdir(parents=True)
    (old / "bin" / "ytdl-sub").write_text("x")
    (old / "state.json").write_text(json.dumps({
        "settings": {"ytdlsub_path": str(old / "bin" / "ytdl-sub"), "library_dir": "D:/Videos"},
        "subscriptions": [{"name": "Example VOD Archive", "urls": ["u"]}]}))
    monkeypatch.setattr(models.sys, "platform", "win32")  # the portable data folder is the Windows rule
    monkeypatch.setattr(models.Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("APPDATA", raising=False)
    install = tmp_path / "app"
    monkeypatch.setattr(models, "install_dir", lambda: install)
    monkeypatch.setattr(models, "_APP_DIR", None)

    st = models.AppState.load()
    assert models.app_dir() == install / "data"
    assert [s.name for s in st.subscriptions] == ["Example VOD Archive"]
    assert st.settings.ytdlsub_path == str(install / "data" / "bin" / "ytdl-sub")
    assert st.settings.library_dir == "D:/Videos"


def test_linux_data_dir_is_xdg(tmp_path, monkeypatch):
    monkeypatch.setattr(models.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(models, "_APP_DIR", None)
    assert models.app_dir() == tmp_path / "share" / "Red-Rip"  # an AppImage's own folder is read-only
