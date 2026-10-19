"""Games the signed-in user owns, including those that are not installed."""

import json
import os
import threading

import requests
from gi.repository import GLib

from . import auth
from . import config as config_mod
from .library import Game, find_art, is_tool

ART_URL = "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/{name}"
REMOTE_ART = {
    "cover": "library_600x900.jpg",
    "hero": "library_hero.jpg",
    "logo": "logo.png",
    "header": "header.jpg",
}

# Owned games shown in screenshot mode when no Steam account is connected.
SAMPLE_GAMES = [
    {"appid": 620, "name": "Portal 2"},
    {"appid": 1145360, "name": "Hades"},
    {"appid": 367520, "name": "Hollow Knight"},
    {"appid": 413150, "name": "Stardew Valley"},
    {"appid": 1086940, "name": "Baldur's Gate 3"},
]


def _cache_path(name="owned"):
    return config_mod.cache_dir() / f"{name}.json"


def _art_dir():
    return config_mod.cache_dir() / "art"


def fetch(key, steamid):
    """Download the owned games list with the user's Web API key. Blocking.

    Raises auth.AuthError when Valve does not accept the key.
    """
    games = auth.owned_games(key, steamid)
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(games))
    os.replace(tmp, path)
    return games


def load_cached(name="owned"):
    try:
        return json.loads(_cache_path(name).read_text())
    except (OSError, ValueError):
        return []


def clear_cache():
    for name in ("owned", "family"):
        _cache_path(name).unlink(missing_ok=True)


def to_games(config, owned, installed_ids):
    """Game objects for owned games that are not installed."""
    games = []
    for entry in owned:
        appid = int(entry.get("appid", 0))
        name = entry.get("name", "")
        if not appid or not name or appid in installed_ids or is_tool(name):
            continue
        art = find_art(config.root, config.userdata, appid)
        for kind, filename in REMOTE_ART.items():
            cached = _art_dir() / f"{appid}_{filename}"
            if not art[kind] and cached.is_file():
                art[kind] = str(cached)
        games.append(
            Game(
                appid=appid,
                name=name,
                installed=False,
                last_played=int(entry.get("rtime_last_played", 0)),
                **art,
            )
        )
    return games


_fetching = set()
_lock = threading.Lock()


def ensure_art(game, kind, source_appid=None):
    """Download missing artwork for a game in the background.

    Steam only caches artwork locally for games it has shown recently, so games
    that are not installed often need their images from Steam's public servers.
    source_appid fetches another app's artwork instead, used for non-Steam games
    that match a game sold on Steam. The game's property is updated when ready.
    """
    if game.get_property(kind):
        return
    appid = source_appid or game.props.appid
    if not source_appid and game.props.non_steam:
        return  # Non-Steam IDs have no artwork on Steam's servers.
    key = (game.props.appid, kind)  # Per game, as two games may share a source.
    with _lock:
        if key in _fetching:
            return
        _fetching.add(key)
    cached = _art_dir() / f"{appid}_{REMOTE_ART[kind]}"
    if cached.is_file():
        game.set_property(kind, str(cached))
        return

    def worker():
        path = download_steam_art(appid, kind)
        GLib.idle_add(finish, path)

    def finish(path):
        if path:
            game.set_property(kind, path)
        return GLib.SOURCE_REMOVE

    threading.Thread(target=worker, daemon=True).start()


def download_steam_art(appid, kind):
    """A Steam game's original artwork of one kind, cached locally; "" if Steam has none. Blocking."""
    filename = REMOTE_ART[kind]
    target = _art_dir() / f"{appid}_{filename}"
    if target.is_file():
        return str(target)
    try:
        response = requests.get(ART_URL.format(appid=appid, name=filename), timeout=auth.TIMEOUT)
        if response.status_code == 200 and response.content:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(response.content)
            return str(target)
    except (requests.RequestException, OSError):
        pass
    return ""


def save_cache(entries, name="owned"):
    """Remember an owned-games list, such as one read from the store, for offline use."""
    path = _cache_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries))
    os.replace(tmp, path)
