"""Mod managers: Linux applications or non-Steam games used to mod other games.

Stored by Superlion only. A non-Steam game marked as a mod manager is listed
under Mod Managers instead of the main library views.
"""

import json
import os
from dataclasses import asdict, dataclass

from gi.repository import Gio

from . import config as config_mod


@dataclass
class ModManager:
    id: str  # "app:<desktop file ID>" or "shortcut:<non-Steam app ID>"
    name: str

    @property
    def is_app(self):
        return self.id.startswith("app:")

    @property
    def desktop_id(self):
        return self.id[len("app:"):] if self.is_app else ""

    @property
    def shortcut_appid(self):
        return int(self.id[len("shortcut:"):]) if not self.is_app else 0


def _path():
    return config_mod.config_dir() / "mod_managers.json"


def _load():
    try:
        data = json.loads(_path().read_text())
    except (OSError, ValueError):
        data = {}
    return {
        "managers": [ModManager(**m) for m in data.get("managers", [])],
        "links": {int(k): v for k, v in data.get("links", {}).items()},  # game app ID -> manager ID
    }


def _save(data):
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "managers": [asdict(m) for m in data["managers"]],
        "links": {str(k): v for k, v in data["links"].items()},
    }, indent=2))
    os.replace(tmp, path)


def all_managers():
    return _load()["managers"]


def get(manager_id):
    return next((m for m in all_managers() if m.id == manager_id), None)


def shortcut_ids():
    return {m.shortcut_appid for m in all_managers() if not m.is_app}


def add(manager_id, name):
    data = _load()
    if not any(m.id == manager_id for m in data["managers"]):
        data["managers"].append(ModManager(manager_id, name))
        _save(data)


def remove(manager_id):
    """Stop treating something as a mod manager; games linked to it are unlinked."""
    data = _load()
    data["managers"] = [m for m in data["managers"] if m.id != manager_id]
    data["links"] = {k: v for k, v in data["links"].items() if v != manager_id}
    _save(data)


def set_shortcut(appid, name, is_manager):
    if is_manager:
        add(f"shortcut:{appid}", name)
    else:
        remove(f"shortcut:{appid}")


def linked(game_appid):
    manager_id = _load()["links"].get(int(game_appid))
    return get(manager_id) if manager_id else None


def link(game_appid, manager_id):
    """Link a game to a mod manager; None removes the link."""
    data = _load()
    if manager_id:
        data["links"][int(game_appid)] = manager_id
    else:
        data["links"].pop(int(game_appid), None)
    _save(data)


def installed_apps():
    """Desktop applications that can be chosen as mod managers, by name."""
    apps = [a for a in Gio.AppInfo.get_all() if a.should_show() and a.get_id()]
    return sorted(apps, key=lambda a: a.get_display_name().casefold())


def app_info(manager):
    """The desktop application for an app mod manager, or None if it was uninstalled."""
    if not manager.is_app:
        return None
    return next((a for a in Gio.AppInfo.get_all() if a.get_id() == manager.desktop_id), None)


def link_counts():
    counts = {}
    for manager_id in _load()["links"].values():
        counts[manager_id] = counts.get(manager_id, 0) + 1
    return counts
