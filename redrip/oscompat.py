"""Platform differences (Windows / Linux) in one place."""
from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
EXE = ".exe" if IS_WINDOWS else ""
DESKTOP_ID = "red-rip"  # .desktop file name (and Wayland app id) on Linux


def exe(name: str) -> str:
    return name + EXE


def is_arm64() -> bool:
    return platform.machine().lower() in ("aarch64", "arm64")


def appimage_path() -> Path | None:
    """The .AppImage file when running from one (its mount point is temporary)."""
    p = os.environ.get("APPIMAGE")
    return Path(p) if p else None


def is_kde() -> bool:
    return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()


def which(name: str) -> str | None:
    return shutil.which(name)


def xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def exe_filter() -> str:
    return "Executables (*.exe);;All files (*)" if IS_WINDOWS else "All files (*)"


# ---------------------------------------------------------------- Linux desktop entry
def desktop_entry_path() -> Path:
    return xdg_data_home() / "applications" / f"{DESKTOP_ID}.desktop"


def install_desktop_entry(icon_png: Path) -> Path:
    """Adds Red-Rip to the application menu (KDE's launcher, etc.) pointing at this AppImage."""
    app = appimage_path()
    if app is None:
        raise RuntimeError("Only available when running the AppImage.")
    icon_dir = xdg_data_home() / "icons" / "hicolor" / "256x256" / "apps"
    icon_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(icon_png, icon_dir / f"{DESKTOP_ID}.png")
    entry = desktop_entry_path()
    entry.parent.mkdir(parents=True, exist_ok=True)
    exec_path = str(app).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    entry.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Red-Rip\n"
        "Comment=Download YouTube channels into a Jellyfin library\n"
        f'Exec="{exec_path}"\n'
        f"Icon={DESKTOP_ID}\n"
        "Terminal=false\n"
        "Categories=AudioVideo;Video;\n"
        f"StartupWMClass={DESKTOP_ID}\n",
        encoding="utf-8",
    )
    entry.chmod(0o755)
    return entry


def remove_desktop_entry() -> None:
    for p in (desktop_entry_path(),
              xdg_data_home() / "icons" / "hicolor" / "256x256" / "apps" / f"{DESKTOP_ID}.png"):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
