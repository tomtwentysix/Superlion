"""Keeping GNOME's dock and notification banners out of a Sunshine stream."""

import json
import subprocess
from pathlib import Path

from gi.repository import GLib

DOCKS = ("dash-to-dock@micxgx.gmail.com", "ubuntu-dock@ubuntu.com", "dash2dock-lite@icedman.github.com")
# What quiet() changed, as {"banners": bool, "docks": [uuid, ...]}, so restore() undoes only that.
SAVED_PATH = Path(GLib.get_user_runtime_dir()) / "superlion" / "desktop.json"


def _run(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=10)


def quiet():
    if SAVED_PATH.exists():
        return
    try:
        enabled = _run("gnome-extensions", "list", "--enabled").stdout.split()
    except (OSError, subprocess.SubprocessError):
        enabled = []
    docks = [uuid for uuid in DOCKS if uuid in enabled]
    banners = _run("gsettings", "get", "org.gnome.desktop.notifications", "show-banners").stdout.strip() == "true"
    SAVED_PATH.parent.mkdir(parents=True, exist_ok=True)
    SAVED_PATH.write_text(json.dumps({"banners": banners, "docks": docks}))
    for uuid in docks:
        _run("gnome-extensions", "disable", uuid)
    if banners:
        _run("gsettings", "set", "org.gnome.desktop.notifications", "show-banners", "false")


def restore():
    try:
        saved = json.loads(SAVED_PATH.read_text())
    except (OSError, ValueError):
        return
    for uuid in saved["docks"]:
        _run("gnome-extensions", "enable", uuid)
    if saved["banners"]:
        _run("gsettings", "set", "org.gnome.desktop.notifications", "show-banners", "true")
    SAVED_PATH.unlink()
