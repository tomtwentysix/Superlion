"""Installing games into a chosen library folder without Steam's install dialog.

Superlion writes an app manifest that marks the game as needing its download,
as Steam does when an install starts. Steam reads manifests when it starts, so
the manifest is written while Steam is closed and Steam then downloads the game.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import appinfo, auth, vdf

# UpdateRequired (2) and UpdateStarted (1024): Steam resumes the download on start.
INSTALL_STATE = "1026"


@dataclass
class Library:
    path: Path
    free: int  # Bytes free on its drive, or 0 if unknown


def libraries(config):
    """The enabled library folders, with the free space on each."""
    result = []
    for folder in config.library_folders():
        try:
            free = shutil.disk_usage(Path(folder) / "steamapps").free
        except OSError:
            free = 0
        result.append(Library(Path(folder), free))
    return result


def install_info(config, appid):
    """{"name", "installdir", "download_size"} from Steam's app data, or None if unknown."""
    info = appinfo.load(config.root).get(int(appid))
    if not info or not info.get("installdir"):
        return None
    return {"name": info.get("name", ""), "installdir": info["installdir"], "download_size": info.get("download_size", 0)}


def manifest_path(library, appid):
    return Path(library) / "steamapps" / f"appmanifest_{int(appid)}.acf"


def is_installed_anywhere(config, appid):
    return any(manifest_path(folder, appid).exists() for folder in config.library_folders())


def write_manifest(config, appid, library, name, installdir):
    """Write the manifest that makes Steam download the game. Steam must not be running."""
    if is_installed_anywhere(config, appid):
        return  # Steam already knows this game, so its own manifest is left alone.
    path = manifest_path(library, appid)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "AppState": {
            "appid": str(int(appid)),
            "universe": "1",
            "name": name,
            "StateFlags": INSTALL_STATE,
            "installdir": installdir,
            "LastUpdated": "0",
            "SizeOnDisk": "0",
            "buildid": "0",
            "LastOwner": auth.steamid64(config),
            "BytesToDownload": "0",
            "BytesDownloaded": "0",
            "AutoUpdateBehavior": "0",
            "AllowOtherDownloadsWhileRunning": "0",
            "ScheduledAutoUpdate": "0",
        }
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(vdf.dumps(state), encoding="utf-8")
    os.replace(tmp, path)
