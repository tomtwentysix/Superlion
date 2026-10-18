"""Settings changes waiting for Steam to close."""

import json
import os

from . import config as config_mod
from . import game_collections, steam_control, steam_settings

# Queue key for "sync Superlion's collections to Steam"; app ID 0 is never a game.
COLLECTIONS_KEY = 0

PENDING_PATH = config_mod.data_dir() / "pending.json"


def load():
    """Queued changes as {appid: {"launch_options"?, "compat_tool"?}}."""
    try:
        raw = json.loads(PENDING_PATH.read_text())
    except (OSError, ValueError):
        return {}
    return {int(appid): changes for appid, changes in raw.items()}


def _save(queue):
    if not queue:
        PENDING_PATH.unlink(missing_ok=True)
        return
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PENDING_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps({str(k): v for k, v in queue.items()}, indent=2))
    os.replace(tmp, PENDING_PATH)


def add(appid, changes):
    """Queue changes for a game; later changes to the same setting replace earlier ones."""
    queue = load()
    queue.setdefault(int(appid), {}).update(changes)
    _save(queue)


def get(appid):
    return load().get(int(appid), {})


def add_collections_sync(include_own=True):
    """Queue a collection sync; include_own also sends Superlion's own collections."""
    include_own = include_own or get(COLLECTIONS_KEY).get("include_own", False)
    add(COLLECTIONS_KEY, {"sync_collections": True, "include_own": include_own})


def collections_waiting():
    return bool(load().get(COLLECTIONS_KEY))


def count():
    """Waiting changes: each game setting counts once, and a collection sync counts once."""
    queue = load()
    collections = 1 if queue.pop(COLLECTIONS_KEY, None) else 0
    return collections + sum(len(changes) for changes in queue.values())


def apply_now(config):
    """Write every queued change and clear the queue. Steam must not be running."""
    queue = load()
    applied = len(queue)
    sync = queue.pop(COLLECTIONS_KEY, None)
    if sync:
        # Queues saved before include_own existed meant a full sync.
        game_collections.sync_to_steam(config, include_own=sync.get("include_own", True))
        _save(queue)
    if queue:
        steam_settings.write_changes(config, queue)
        _save({})
    return applied


def apply_if_closed(config):
    """Apply the queue when Steam is closed. Returns the number of queued items applied."""
    if not load() or steam_control.is_running(config):
        return 0
    return apply_now(config)
