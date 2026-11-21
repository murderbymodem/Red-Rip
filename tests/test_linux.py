import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from redrip import oscompat, scheduler  # noqa: E402

# systemd units and .desktop files only exist on Linux (paths here are POSIX paths)
pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux-only")


def test_systemd_units_for_appimage(monkeypatch):
    monkeypatch.setenv("APPIMAGE", "/home/me/Apps/My Apps/Red-Rip-v1.0.0-x86_64.AppImage")
    service, timer = scheduler.unit_files("03:15")
    # the .AppImage file itself (its mount point is temporary), quoted because of the space
    assert 'ExecStart="/home/me/Apps/My Apps/Red-Rip-v1.0.0-x86_64.AppImage" "--headless"' in service
    assert "WorkingDirectory=/home/me/Apps/My Apps\n" in service
    assert "OnCalendar=*-*-* 03:15:00" in timer and "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer


def test_systemd_quote_escapes_specials():
    assert scheduler._systemd_quote('/a b/50% "x"') == '"/a b/50%% \\"x\\""'   # "/a b/50%% \"x\""
    assert scheduler._systemd_quote("a\\b") == '"a\\\\b"'                        # backslash doubled


def test_desktop_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("APPIMAGE", "/opt/Red Rip/Red-Rip.AppImage")
    icon = Path(__file__).resolve().parent.parent / "assets" / "icon.png"
    entry = oscompat.install_desktop_entry(icon)
    text = entry.read_text()
    assert entry == tmp_path / "applications" / "red-rip.desktop"
    assert 'Exec="/opt/Red Rip/Red-Rip.AppImage"' in text and "Icon=red-rip" in text
    assert (tmp_path / "icons" / "hicolor" / "256x256" / "apps" / "red-rip.png").exists()
    oscompat.remove_desktop_entry()
    assert not entry.exists()
