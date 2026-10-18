"""SteamGridDB: community artwork for Steam and non-Steam games.

Requests use the user's own free API key from steamgriddb.com, which is kept in
GNOME Keyring. Only artwork Steam can use (PNG and JPEG, not animated) is offered.
"""

import hashlib
from urllib.parse import quote

import gi
import requests

gi.require_version("Secret", "1")
from gi.repository import GLib, Secret  # noqa: E402

from . import config as config_mod  # noqa: E402

API = "https://www.steamgriddb.com/api/v2"
KEY_PAGE = "https://www.steamgriddb.com/profile/preferences/api"
TIMEOUT = 20

SCHEMA = Secret.Schema.new(
    "uk.co.solarflareit.Superlion.SteamGridDB",
    Secret.SchemaFlags.NONE,
    {"kind": Secret.SchemaAttributeType.STRING},
)
ATTRIBUTES = {"kind": "steamgriddb-api-key"}

# What each Superlion artwork kind is called on SteamGridDB, and the sizes Steam uses.
KINDS = {
    "cover": ("grids", {"dimensions": "600x900,342x482,660x930"}),
    "header": ("grids", {"dimensions": "460x215,920x430"}),
    "hero": ("heroes", {}),
    "logo": ("logos", {}),
}
STATIC_IMAGES = {"mimes": "image/png,image/jpeg", "types": "static"}


class ApiKeyError(Exception):
    """The API key is missing or was rejected."""


# API key -------------------------------------------------------------------


def load_key():
    try:
        return Secret.password_lookup_sync(SCHEMA, ATTRIBUTES, None) or ""
    except GLib.Error:
        return ""


def save_key(key):
    Secret.password_store_sync(
        SCHEMA, ATTRIBUTES, Secret.COLLECTION_DEFAULT, "Superlion SteamGridDB API key", key.strip(), None
    )


def clear_key():
    try:
        Secret.password_clear_sync(SCHEMA, ATTRIBUTES, None)
    except GLib.Error:
        pass


# Requests ------------------------------------------------------------------


def _get(path, key, params=None):
    response = requests.get(
        API + path, params=params or {}, headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT
    )
    if response.status_code in (401, 403):
        raise ApiKeyError("SteamGridDB did not accept the API key.")
    if response.status_code == 404:
        return []
    response.raise_for_status()
    body = response.json()
    if not body.get("success", True):
        raise RuntimeError("; ".join(body.get("errors", [])) or "SteamGridDB returned an error.")
    return body.get("data") or []


def search(name, key):
    """Games matching a name: [{"id", "name", "release_date"?, "verified"}]."""
    return _get(f"/search/autocomplete/{quote(name, safe='')}", key)


def images(kind, key, game_id=None, steam_appid=None, page=0):
    """Artwork of one kind, by SteamGridDB game ID or by Steam app ID."""
    endpoint, extra = KINDS[kind]
    where = f"steam/{steam_appid}" if steam_appid else f"game/{game_id}"
    params = {**STATIC_IMAGES, **extra, "page": page}
    if kind == "logo":
        params["mimes"] = "image/png"  # Logos need a transparent background.
    return _get(f"/{endpoint}/{where}", key, params)


def download(url):
    """Save a full-size image in the cache and return its path."""
    suffix = ".png" if url.lower().split("?")[0].endswith(".png") else ".jpg"
    target = config_mod.cache_dir() / "steamgriddb" / (hashlib.sha1(url.encode()).hexdigest() + suffix)
    if not target.is_file():
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
    return target
