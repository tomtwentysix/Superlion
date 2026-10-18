"""Launch option presets: named sets of launch options to reuse across games.

Stored by Superlion only, in ~/.config/superlion/launch_presets.json. Applying a
preset fills in a game's launch options, which are then saved to Steam like any
other change.
"""

import json
import os
import uuid
from dataclasses import asdict, dataclass

from . import config as config_mod
from . import library, pending, steam_settings, vdf


@dataclass
class Preset:
    id: str
    name: str
    options: str


def _path():
    return config_mod.config_dir() / "launch_presets.json"


def all_presets():
    """Presets in the order the user created them."""
    try:
        data = json.loads(_path().read_text())
    except (OSError, ValueError):
        return []
    return [Preset(**p) for p in data.get("presets", []) if p.get("id") and p.get("name")]


def _save(presets):
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"presets": [asdict(p) for p in presets]}, indent=2))
    os.replace(tmp, path)


def get(preset_id):
    return next((p for p in all_presets() if p.id == preset_id), None)


def add(name, options):
    preset = Preset(uuid.uuid4().hex, name.strip(), options.strip())
    _save(all_presets() + [preset])
    return preset


def update(preset_id, name, options):
    presets = all_presets()
    for preset in presets:
        if preset.id == preset_id:
            preset.name, preset.options = name.strip(), options.strip()
    _save(presets)


def remove(preset_id):
    _save([p for p in all_presets() if p.id != preset_id])


def find_by_options(options):
    """The preset with exactly these launch options, or None."""
    options = options.strip()
    return next((p for p in all_presets() if p.options == options), None)


def unique_name(name):
    """The name, followed by a number if a preset already uses it."""
    taken = {p.name.casefold() for p in all_presets()}
    candidate, number = name, 2
    while candidate.casefold() in taken:
        candidate, number = f"{name} {number}", number + 1
    return candidate


def suggest_name(options, game_name):
    """A default name for a preset made from a game's launch options."""
    # TODO(human): name the preset after what the options do, falling back to the game.
    return f"{game_name} Options"


def configured_games(config):
    """{app ID: launch options} for every game with launch options set.

    Includes Steam games (localconfig.vdf), non-Steam games (shortcuts.vdf) and
    changes still waiting for Steam to close, which take precedence.
    """
    found = {}
    try:
        data = vdf.load(config.localconfig_path)
        apps = vdf.get_path(data, *steam_settings.LAUNCH_PATH) or {}
    except (OSError, ValueError):
        apps = {}
    for appid, app in apps.items():
        if appid.isdigit() and isinstance(app, dict) and app.get("LaunchOptions", "").strip():
            found[int(appid)] = app["LaunchOptions"].strip()
    for appid, entry in library.read_shortcuts(config).items():
        options = (library.field(entry, "LaunchOptions") or "").strip()
        if options:
            found[appid] = options
    for appid, changes in pending.load().items():
        if "launch_options" in changes:
            if changes["launch_options"].strip():
                found[appid] = changes["launch_options"].strip()
            else:
                found.pop(appid, None)
    # "%command%" on its own runs the game unchanged, so it is not worth a preset.
    return {appid: options for appid, options in found.items() if options.replace("%command%", "").strip()}
