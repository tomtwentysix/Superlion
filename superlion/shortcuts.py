"""Adding programs to Steam as non-Steam games, and the Files script that does it."""

import configparser
import os
import shlex
import shutil
import subprocess
import zlib
from pathlib import Path

from gi.repository import GLib

from . import config as config_mod
from . import steam_paths

SCRIPT_NAME = "Add to Steam (Development)" if config_mod.DEVEL else "Add to Steam"


def default_name(path):
    return Path(path).stem.replace("_", " ").strip() or Path(path).name


def new_appid(exe, name):
    # The ID Steam itself gives a shortcut, so artwork named after it matches.
    return zlib.crc32((exe + name).encode("utf-8")) | 0x80000000


def entry(path, name):
    """A shortcuts.vdf entry, with the keys and quoting Steam writes."""
    path = os.path.abspath(path)
    exe = f'"{path}"'
    return {
        "appid": new_appid(exe, name),
        "AppName": name,
        "Exe": exe,
        "StartDir": os.path.dirname(path) + os.sep,
        "icon": "",
        "ShortcutPath": "",
        "LaunchOptions": "",
        "IsHidden": 0,
        "AllowDesktopConfig": 1,
        "AllowOverlay": 1,
        "OpenVR": 0,
        "Devkit": 0,
        "DevkitGameID": "",
        "DevkitOverrideAppID": 0,
        "LastPlayTime": 0,
        "FlatpakAppID": "",
        "tags": {},
    }


def _flatpak_filesystems():
    """Folders Flatpak Steam may read, with the user's overrides; None when unknown."""
    try:
        result = subprocess.run(
            ["flatpak", "info", "--show-permissions", steam_paths.FLATPAK_ID],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(result.stdout)
    entries = parser.get("Context", "filesystems", fallback="").split(";")
    home = Path.home()
    folders = [home / ".var" / "app" / steam_paths.FLATPAK_ID]
    for item in filter(None, entries):
        if item.startswith("!"):
            continue
        name = item.split(":")[0]
        if name in ("host", "host-os", "home"):
            folders.append(Path("/") if name.startswith("host") else home)
        elif name.startswith("~/"):
            folders.append(home / name[2:])
        elif name.startswith("/"):
            folders.append(Path(name))
        elif name.startswith("xdg-"):
            base, _, rest = name.partition("/")
            folder = _xdg_folder(base)
            if folder:
                folders.append(folder / rest if rest else folder)
    return folders


def _xdg_folder(name):
    special = {
        "xdg-desktop": GLib.UserDirectory.DIRECTORY_DESKTOP,
        "xdg-documents": GLib.UserDirectory.DIRECTORY_DOCUMENTS,
        "xdg-download": GLib.UserDirectory.DIRECTORY_DOWNLOAD,
        "xdg-music": GLib.UserDirectory.DIRECTORY_MUSIC,
        "xdg-pictures": GLib.UserDirectory.DIRECTORY_PICTURES,
        "xdg-public-share": GLib.UserDirectory.DIRECTORY_PUBLIC_SHARE,
        "xdg-templates": GLib.UserDirectory.DIRECTORY_TEMPLATES,
        "xdg-videos": GLib.UserDirectory.DIRECTORY_VIDEOS,
    }
    folders = {
        "xdg-config": GLib.get_user_config_dir(),
        "xdg-data": GLib.get_user_data_dir(),
        "xdg-cache": GLib.get_user_cache_dir(),
    }
    if name in special:
        folder = GLib.get_user_special_dir(special[name])
        return Path(folder) if folder else None
    return Path(folders[name]) if name in folders else None


def steam_can_read(config, path):
    """False when Steam is a Flatpak that cannot see this file; True when it can or is not sandboxed."""
    if config.steam_kind != "flatpak":
        return True
    folders = _flatpak_filesystems()
    if folders is None:
        return True  # Cannot tell; Steam will say if it cannot start the game.
    path = Path(path).resolve()
    return any(path.is_relative_to(folder) for folder in folders)


def grant_flatpak_access(folder):
    """Let Flatpak Steam read a folder, as "flatpak override --user" does. Returns an error or None."""
    try:
        result = subprocess.run(
            ["flatpak", "override", "--user", f"--filesystem={folder}:ro", steam_paths.FLATPAK_ID],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return str(error)
    if result.returncode:
        return result.stderr.strip() or "Flatpak could not change Steam's permissions"
    return None


def script_path():
    return Path(GLib.get_user_data_dir()) / "nautilus" / "scripts" / SCRIPT_NAME


def files_available():
    return shutil.which("nautilus") is not None


def _launch_command():
    if config_mod.DEVEL:
        return shlex.quote(str(Path(__file__).resolve().parent.parent / "run-dev.sh"))
    return "superlion"


def script_installed():
    try:
        return f"# {config_mod.APP_ID}" in script_path().read_text()
    except OSError:
        return False


def install_script():
    path = script_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Files passes the selected local files as arguments.
    path.write_text(f'#!/bin/sh\n# {config_mod.APP_ID}\nexec {_launch_command()} "$@"\n')
    path.chmod(0o755)


def remove_script():
    if script_installed():
        script_path().unlink(missing_ok=True)
