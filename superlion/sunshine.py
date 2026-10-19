"""Adding games to Sunshine, the game streaming host that Moonlight connects to."""

import json
import os
import shlex
import shutil
import signal
import subprocess
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib  # noqa: E402

from . import config as config_mod  # noqa: E402
from . import steam_control  # noqa: E402

CONFIG_DIR = Path(GLib.get_user_config_dir()) / "sunshine"
APPS_PATH = CONFIG_DIR / "apps.json"
CONF_PATH = CONFIG_DIR / "sunshine.conf"
LOG_PATH = CONFIG_DIR / "sunshine.log"
SERVICE = "app-dev.lizardbyte.app.Sunshine.service"
FLATPAK_ID = "dev.lizardbyte.app.Sunshine"
COVERS_DIR = config_mod.data_dir() / "sunshine"
# Moonlight shows box art at 2:3.
COVER_SIZE = (600, 900)


def kind():
    """"native", "flatpak" or None, for how Sunshine is installed."""
    if shutil.which("sunshine"):
        return "native"
    try:
        subprocess.run(["flatpak", "info", FLATPAK_ID], capture_output=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return "flatpak"


def is_running():
    try:
        result = subprocess.run(["systemctl", "--user", "is-active", SERVICE], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def can_capture_hdr():
    """Whether Sunshine can capture the screen through KMS, which HDR needs.

    The Flatpak and AppImage cannot. A native install needs cap_sys_admin,
    which its package sets as a file capability.
    """
    path = shutil.which("sunshine")
    if not path:
        return False
    try:
        return bool(os.getxattr(os.path.realpath(path), "security.capability"))
    except OSError:
        return False


def is_streaming():
    """Whether a Moonlight client is connected, from the log of Sunshine's current run."""
    try:
        lines = LOG_PATH.read_text(errors="replace").splitlines()
    except OSError:
        return False
    for line in reversed(lines):
        if line.endswith("CLIENT DISCONNECTED"):
            return False
        if line.endswith("CLIENT CONNECTED"):
            return True
    return False


def problems():
    """Why games added to Sunshine would not stream properly, worst first:
    "missing", "stopped" or "no-hdr"."""
    if kind() is None:
        return ["missing"]
    issues = []
    if not is_running():
        issues.append("stopped")
    if not can_capture_hdr():
        issues.append("no-hdr")
    return issues


def _load():
    try:
        return json.loads(APPS_PATH.read_text())
    except (OSError, ValueError):
        return {"env": {}, "apps": []}


def _save(data):
    APPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = APPS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=4))
    os.replace(tmp, APPS_PATH)


def _index(apps, game):
    """The position of the game's entry, found by the Steam link it starts."""
    uri = game.run_uri
    for i, app in enumerate(apps):
        if any(cmd.endswith(" " + uri) for cmd in app.get("detached", [])):
            return i
    return None


def has(game):
    return _index(_load().get("apps", []), game) is not None


def _superlion_command():
    if config_mod.DEVEL:
        return shlex.quote(str(Path(__file__).resolve().parent.parent / "run-dev.sh"))
    return "superlion"


def _cover(game):
    """A PNG of the game's cover for Moonlight, or "" without one. Sunshine only reads PNG."""
    if not game.props.cover:
        return ""
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    path = COVERS_DIR / f"{game.props.appid}.png"
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(game.props.cover, *COVER_SIZE, False)
        pixbuf.savev(str(path), "png", [], [])
    except GLib.Error:
        return ""
    return str(path)


def _entry(config, game):
    superlion = _superlion_command()
    steam = shlex.split(config.steam_command) + steam_control.start_options(config) + [game.run_uri]
    return {
        "name": game.props.name,
        "image-path": _cover(game),
        # In its own scope, so a Steam started here survives Sunshine restarting.
        "detached": [shlex.join(["systemd-run", "--user", "--scope", "--collect", "--quiet", "--", *steam])],
        # Undone in reverse: the game is closed before the display is put back.
        "prep-cmd": [
            {"do": f"{superlion} --sunshine-prepare", "undo": f"{superlion} --sunshine-restore"},
            {"do": "", "undo": f"{superlion} --sunshine-close {game.props.appid}"},
        ],
        "auto-detach": True,
        "wait-all": True,
        "exit-timeout": 5,
    }


def add(config, game):
    """Add or update the game's entry. True if Sunshine was restarted to list it."""
    data = _load()
    apps = data.setdefault("apps", [])
    entry = _entry(config, game)
    index = _index(apps, game)
    if index is None:
        apps.append(entry)
    else:
        apps[index] = {**apps[index], **entry}
    _save(data)
    return _reload()


def remove(game):
    """Remove the game's entry. True if Sunshine was restarted."""
    data = _load()
    apps = data.get("apps", [])
    index = _index(apps, game)
    if index is None:
        return False
    del apps[index]
    _save(data)
    (COVERS_DIR / f"{game.props.appid}.png").unlink(missing_ok=True)
    return _reload()


def _reload():
    """Restart Sunshine so it reads apps.json again, unless that would end a stream."""
    if not is_running() or is_streaming():
        return False
    subprocess.run(["systemctl", "--user", "restart", "--no-block", SERVICE], timeout=10)
    return True


def set_output(connector):
    """Have Sunshine capture connector, or its first monitor for "". True if sunshine.conf changed.

    sunshine.conf holds one "name = value" setting per line.
    """
    try:
        lines = CONF_PATH.read_text().splitlines()
    except OSError:
        lines = []
    kept = [line for line in lines if line.split("=", 1)[0].strip() != "output_name"]
    if connector:
        kept.append(f"output_name = {connector}")
    if kept == lines:
        return False
    CONF_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONF_PATH.write_text("".join(line + "\n" for line in kept))
    _reload()
    return True


def start():
    subprocess.run(["systemctl", "--user", "start", "--no-block", SERVICE], timeout=10)


def _children(pid):
    try:
        tasks = os.listdir(f"/proc/{pid}/task")
    except OSError:
        return []
    found = []
    for task in tasks:
        try:
            found += [int(c) for c in Path(f"/proc/{pid}/task/{task}/children").read_text().split()]
        except OSError:
            pass
    return found


def close_game(appid):
    """End a game Steam started, as Steam's own Stop does.

    Steam runs every game under a "reaper SteamLaunch AppId=<id>" process, so
    that process and everything below it make up the game.
    """
    marker = f"AppId={appid}".encode()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            args = Path(f"/proc/{entry}/cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if len(args) > 2 and os.path.basename(args[0]) == b"reaper" and marker in args:
            pids, queue = [], [int(entry)]
            while queue:
                pid = queue.pop()
                pids.append(pid)
                queue += _children(pid)
            for pid in reversed(pids):
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
