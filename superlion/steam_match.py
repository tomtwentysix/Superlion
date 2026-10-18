"""Matching non-Steam games to the same game on the Steam store, for its artwork."""

import json
import os
import re

from . import config as config_mod
from . import library, store_api

_MARKS = re.compile(r"[™®©]")
_NOT_WORD = re.compile(r"[\W_]+")


def _normal(name):
    return " ".join(_NOT_WORD.sub(" ", _MARKS.sub("", name.casefold())).split())


def _cache_path():
    return config_mod.cache_dir() / "steam_matches.json"


def _load_cache():
    try:
        return json.loads(_cache_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_cache(cache):
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=1))
    os.replace(tmp, path)


def find_steam_appids(names, region):
    """{name: Steam app ID or 0} for non-Steam game names. Blocking.

    Only exact name matches count (ignoring case, punctuation and ™), so a tool
    such as a mod manager is never given an unrelated game's artwork. Results,
    including misses, are remembered so each name is looked up once.
    """
    cache = _load_cache()
    changed = False
    result = {}
    for name in names:
        term = library.artwork_search_term(name)
        key = _normal(term)
        if key not in cache:
            try:
                items = store_api.search(term, region)
            except Exception:  # Offline: try again next time rather than remembering a miss.
                result[name] = 0
                continue
            cache[key] = next((item["id"] for item in items if _normal(item.get("name", "")) == key), 0)
            changed = True
        result[name] = cache[key]
    if changed:
        _save_cache(cache)
    return result


# Matches chosen by the user ---------------------------------------------------


def _overrides_path():
    return config_mod.config_dir() / "steam_matches.json"


def load_overrides():
    """{shortcut app ID: Steam app ID}, where 0 means "not on Steam"."""
    try:
        return {int(k): int(v) for k, v in json.loads(_overrides_path().read_text()).items()}
    except (OSError, ValueError):
        return {}


def set_override(shortcut_appid, steam_appid):
    """Remember the user's choice; steam_appid 0 marks the game as not on Steam."""
    overrides = load_overrides()
    overrides[int(shortcut_appid)] = int(steam_appid)
    path = _overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({str(k): v for k, v in overrides.items()}, indent=1))
    os.replace(tmp, path)


def clear_override(shortcut_appid):
    overrides = load_overrides()
    if overrides.pop(int(shortcut_appid), None) is not None:
        path = _overrides_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({str(k): v for k, v in overrides.items()}, indent=1))
        os.replace(tmp, path)


def match_games(games, region):
    """{shortcut app ID: Steam app ID or 0}: the user's choice, else an exact name match. Blocking."""
    overrides = load_overrides()
    automatic = find_steam_appids(
        [g.props.name for g in games if g.props.appid not in overrides], region
    )
    return {
        g.props.appid: overrides.get(g.props.appid, automatic.get(g.props.name, 0)) for g in games
    }


_DATE_FORMATS = ("%d %b, %Y", "%b %d, %Y", "%d %B, %Y", "%B %d, %Y", "%b %Y", "%B %Y", "%Y")
_VR_CATEGORIES = {31: 1, 53: 1, 54: 2}  # Store category IDs: VR Support, VR Supported, VR Only


def store_metadata(steam_appid, region):
    """Release date, genres and VR support from a game's store page. Blocking.

    Used for matched games that Steam's local app database does not know about.
    """
    import calendar
    import time as time_mod

    data = store_api.details(steam_appid, region) or {}
    release = 0
    date_text = (data.get("release_date") or {}).get("date", "")
    for fmt in _DATE_FORMATS:
        try:
            release = calendar.timegm(time_mod.strptime(date_text, fmt))
            break
        except ValueError:
            continue
    vr = max((_VR_CATEGORIES.get(c.get("id"), 0) for c in data.get("categories", [])), default=0)
    return {
        "release": release,
        "genres": [g.get("description", "") for g in data.get("genres", []) if g.get("description")],
        "vr": vr,
    }
