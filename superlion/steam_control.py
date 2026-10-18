"""Starting, stopping and sending links to the Steam client."""

import os
import shlex
import subprocess
import time
from pathlib import Path

from gi.repository import Gio, GLib

from . import config as config_mod
from . import steam_paths

SHUTDOWN_TIMEOUT = 60  # seconds
POLL_INTERVAL = 500  # milliseconds


def _is_steam_process(pid):
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return False
    return os.path.basename(exe) == "steam"


def _flatpak_running():
    try:
        result = subprocess.run(
            ["flatpak", "ps", "--columns=application"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return steam_paths.FLATPAK_ID in result.stdout.split()


def is_running(config):
    """Whether the Steam client is running.

    Native Steam is detected from its pid file. Flatpak Steam records a PID from
    inside its sandbox, which does not match the host, so flatpak is asked instead.
    """
    if config.steam_kind == "flatpak":
        return _flatpak_running()
    for pid_file in (Path.home() / ".steam" / "steam.pid", config.root / "steam.pid"):
        try:
            pid = int(pid_file.read_text().strip())
        except (OSError, ValueError):
            continue
        if _is_steam_process(pid):
            return True
    return False


def _spawn(config, *args):
    Gio.Subprocess.new(shlex.split(config.steam_command) + list(args), Gio.SubprocessFlags.NONE)


def open_uri(config, uri):
    """Open a steam:// link in the Steam client the user selected.

    With a single Steam installed the desktop's default handler is used. When both
    native and Flatpak Steam are present, the default handler may belong to the
    other one, so the link is passed to the configured command instead.
    """
    if len(steam_paths.command_candidates()) > 1:
        _spawn(config, uri)
    else:
        Gio.AppInfo.launch_default_for_uri(uri, None)


def start(config):
    _spawn(config)


def shutdown(config, callback):
    """Ask Steam to exit; callback(True) once it has, or callback(False) on timeout."""
    if not is_running(config):
        callback(True)
        return
    _spawn(config, "-shutdown")
    deadline = time.monotonic() + SHUTDOWN_TIMEOUT

    def poll():
        if not is_running(config):
            callback(True)
            return GLib.SOURCE_REMOVE
        if time.monotonic() > deadline:
            callback(False)
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    GLib.timeout_add(POLL_INTERVAL, poll)


def relaunch(config, while_closed, callback):
    """Close Steam, run while_closed(), then start Steam again.

    callback(error) receives None on success or a message describing the failure.
    Steam is restarted even if while_closed() fails, so the user is not left
    without it.
    """
    if config_mod.SCREENSHOTS:
        callback(None)
        return

    def closed(ok):
        if not ok:
            callback("Steam did not close within a minute. Your changes are still waiting.")
            return
        error = None
        try:
            while_closed()
        except Exception as exc:  # Reported to the user; Steam must still restart.
            error = f"The changes could not be written: {exc}"
        # Give Steam a moment to release its files before it starts again.
        GLib.timeout_add(1000, lambda: (start(config), callback(error), GLib.SOURCE_REMOVE)[-1])

    shutdown(config, closed)
