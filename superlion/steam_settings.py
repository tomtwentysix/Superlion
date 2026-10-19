"""Reading and writing per-game launch options and compatibility tools.

Steam keeps these files in memory and rewrites them on exit, so writes must only
happen while Steam is closed; callers check steam_control.is_running() first.
"""

import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from . import config as config_mod
from . import library, vdf

LAUNCH_PATH = ("UserLocalConfigStore", "Software", "Valve", "Steam", "apps")
COMPAT_PATH = ("InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping")
BACKUPS_KEPT = 5

# Steam's internal names for Valve's Proton builds, keyed by tool app ID. These
# names are only recorded in Steam's binary app info, so they are listed here.
VALVE_TOOLS = {
    1493710: "proton_experimental",
    2180100: "proton_hotfix",
    3658110: "proton_10",
    2805730: "proton_9",
    2348590: "proton_8",
    1887720: "proton_7",
    1580130: "proton_63",
    1420170: "proton_5013",
}


@dataclass
class CompatTool:
    name: str  # Internal name written to CompatToolMapping; "" means Steam's default.
    label: str


def config_vdf_path(steam_root):
    return Path(steam_root) / "config" / "config.vdf"


def read_launch_options(config, appid):
    shortcut = library.read_shortcuts(config).get(int(appid))
    if shortcut is not None:
        # Non-Steam games keep their launch options in shortcuts.vdf.
        return library.field(shortcut, "LaunchOptions") or ""
    data = vdf.load(config.localconfig_path)
    app = vdf.get_path(data, *LAUNCH_PATH, str(appid)) or {}
    return app.get("LaunchOptions", "")


def read_compat_tool(config, appid):
    data = vdf.load(config_vdf_path(config.steam_root))
    entry = vdf.get_path(data, *COMPAT_PATH, str(appid))
    return entry.get("name", "") if isinstance(entry, dict) else ""


def list_compat_tools(config):
    """Compatibility tools the user can choose, starting with Steam's default."""
    tools = [CompatTool("", "Default (Steam Setting)")]
    seen = {""}

    custom_dirs = [config.root / "compatibilitytools.d"]
    for base in custom_dirs:
        for manifest in sorted(base.glob("*/compatibilitytool.vdf")) + sorted(base.glob("*.vdf")):
            try:
                entries = vdf.get_path(vdf.load(manifest), "compatibilitytools", "compat_tools") or {}
            except OSError:
                continue
            for name, info in entries.items():
                if name not in seen and isinstance(info, dict):
                    seen.add(name)
                    tools.append(CompatTool(name, info.get("display_name", name)))

    for folder in config.library_folders():
        steamapps = Path(folder) / "steamapps"
        for appid, name in VALVE_TOOLS.items():
            manifest = steamapps / f"appmanifest_{appid}.acf"
            if name in seen or not manifest.is_file():
                continue
            label = (vdf.get_path(vdf.load(manifest), "AppState") or {}).get("name", name)
            seen.add(name)
            tools.append(CompatTool(name, label))
    return tools


def _backup(path):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, path.with_name(f"{path.name}.superlion-bak-{stamp}"))
    backups = sorted(path.parent.glob(f"{path.name}.superlion-bak-*"))
    for old in backups[:-BACKUPS_KEPT]:
        old.unlink(missing_ok=True)


def _write_atomic(path, data, binary=False):
    """Back up the file, then replace it in one step, keeping its permissions."""
    path = Path(path)
    _backup(path)
    mode = path.stat().st_mode
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as fh:
            if binary:
                fh.write(vdf.dumps_binary(data))
            else:
                fh.write(vdf.dumps(data).encode("utf-8", "surrogateescape"))
        os.chmod(tmp, mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_changes(config, changes):
    """Apply {appid: {"launch_options"?, "compat_tool"?, "name"?}} to Steam's files.

    "name" applies to non-Steam games only, whose names Steam keeps in shortcuts.vdf.
    """
    if config_mod.SCREENSHOTS:
        return
    launch = {a: c["launch_options"] for a, c in changes.items() if "launch_options" in c}
    compat = {a: c["compat_tool"] for a, c in changes.items() if "compat_tool" in c}
    names = {int(a): c["name"] for a, c in changes.items() if c.get("name")}
    added = [c["shortcut"] for c in changes.values() if "shortcut" in c]

    if added:
        path = library.shortcuts_path(config)
        data = vdf.load_binary(path) if path.is_file() else {"shortcuts": {}}
        entries = vdf.ensure_path(data, "shortcuts")
        existing = {library.field(e, "appid") for e in entries.values() if isinstance(e, dict)}
        # Entries are keyed "0", "1", ... in order.
        index = max((int(k) for k in entries if k.isdigit()), default=-1) + 1
        for entry in added:
            if entry["appid"] not in existing:
                entries[str(index)] = entry
                index += 1
        if path.is_file():
            _write_atomic(path, data, binary=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(vdf.dumps_binary(data))

    shortcut_ids = set(library.read_shortcuts(config)) if (launch or names) else set()
    shortcut_launch = {int(a): o for a, o in launch.items() if int(a) in shortcut_ids}
    launch = {a: o for a, o in launch.items() if int(a) not in shortcut_ids}
    names = {a: n for a, n in names.items() if a in shortcut_ids}

    if shortcut_launch or names:
        path = library.shortcuts_path(config)
        data = vdf.load_binary(path)
        for entry in (vdf.get_path(data, "shortcuts") or {}).values():
            appid = library.field(entry, "appid") if isinstance(entry, dict) else None
            for wanted, field_name, value_map in (
                ("launchoptions", "LaunchOptions", shortcut_launch),
                ("appname", "AppName", names),
            ):
                if appid in value_map:
                    # Keep the key's existing spelling; Steam versions differ (AppName, appname).
                    key = next((k for k in entry if k.lower() == wanted), field_name)
                    entry[key] = value_map[appid]
        _write_atomic(path, data, binary=True)

    if launch:
        path = config.localconfig_path
        data = vdf.load(path)
        apps = vdf.ensure_path(data, *LAUNCH_PATH)
        for appid, options in launch.items():
            app = vdf.ensure_path(apps, str(appid))
            if options:
                app["LaunchOptions"] = options
            else:
                app.pop("LaunchOptions", None)
        _write_atomic(path, data)

    if compat:
        path = config_vdf_path(config.steam_root)
        data = vdf.load(path)
        mapping = vdf.ensure_path(data, *COMPAT_PATH)
        for appid, name in compat.items():
            if name:
                mapping[str(appid)] = {"name": name, "config": "", "priority": "250"}
            else:
                mapping.pop(str(appid), None)
        _write_atomic(path, data)
