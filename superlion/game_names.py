"""Names for games outside the library: Steam's app database, then the store.

Store lookups are remembered in names.json, including apps the store does not
know (as ""), so each app is looked up once.
"""

import json
import os

import requests

from . import config as config_mod
from . import store_api


def _path():
    return config_mod.cache_dir() / "names.json"


def _saved():
    try:
        return json.loads(_path().read_text())
    except (OSError, ValueError):
        return {}


def known(apps, appid):
    """The name from appinfo.load()'s apps or an earlier store lookup; "" if unknown, None if never looked up."""
    name = (apps.get(appid) or {}).get("name")
    return name if name else _saved().get(str(appid))


def look_up(appids):
    """Ask the store for these apps' names and remember them. Makes one slow request per app."""
    saved = _saved()
    for appid in appids:
        try:
            data = store_api.details(appid, "GB")
        except requests.RequestException:
            continue
        saved[str(appid)] = (data or {}).get("name", "")
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(saved))
    os.replace(tmp, path)


def display_name(name, appid):
    return name or f"Unknown Game ({appid})"
