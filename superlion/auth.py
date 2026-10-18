"""Connecting to Steam with the user's own Steam Web API key.

Valve offers every Steam account a free personal Web API key for exactly this
kind of use (steamcommunity.com/dev). Superlion uses only the documented calls
GetOwnedGames and GetPlayerSummaries, for the account already signed in to Steam
on this computer. The key is kept in GNOME Keyring and never leaves this
computer except in requests to api.steampowered.com.
"""

import json
import threading

import gi
import requests

gi.require_version("Secret", "1")
from gi.repository import GLib, Secret  # noqa: E402

from . import config as config_mod  # noqa: E402

API = "https://api.steampowered.com"
KEY_PAGE = "https://steamcommunity.com/dev/apikey"
PRIVACY_PAGE = "https://steamcommunity.com/my/edit/settings"
TIMEOUT = 20
STEAMID64_BASE = 76561197960265728

KEY_SCHEMA = Secret.Schema.new(
    "uk.co.solarflareit.Superlion.SteamWebApiKey",
    Secret.SchemaFlags.NONE,
    {"kind": Secret.SchemaAttributeType.STRING},
)
KEY_ATTRIBUTES = {"kind": "steam-web-api-key"}

# The QR sign-in of earlier test builds stored a token under this schema.
LEGACY_SCHEMA = Secret.Schema.new(
    "uk.co.solarflareit.Superlion.Token",
    Secret.SchemaFlags.NONE,
    {"kind": Secret.SchemaAttributeType.STRING},
)
LEGACY_ATTRIBUTES = {"kind": "steam-session"}


class AuthError(Exception):
    """Valve did not accept the Web API key."""


def run_async(func, callback):
    """Run func() in a thread and call callback(result, error) on the main thread."""

    def worker():
        try:
            result, error = func(), None
        except Exception as exc:  # Reported to the caller on the main thread.
            result, error = None, exc
        GLib.idle_add(lambda: (callback(result, error), GLib.SOURCE_REMOVE)[-1])

    threading.Thread(target=worker, daemon=True).start()


def steamid64(config):
    return str(config.account_id + STEAMID64_BASE)


def load_key():
    try:
        return Secret.password_lookup_sync(KEY_SCHEMA, KEY_ATTRIBUTES, None) or ""
    except GLib.Error:
        return ""


def save_key(key):
    Secret.password_store_sync(
        KEY_SCHEMA, KEY_ATTRIBUTES, Secret.COLLECTION_DEFAULT,
        "Superlion Steam Web API key", key.strip(), None,
    )


def clear_key():
    try:
        Secret.password_clear_sync(KEY_SCHEMA, KEY_ATTRIBUTES, None)
    except GLib.Error:
        pass


def remove_legacy_sign_in():
    """Delete the token kept by the old QR sign-in; True if one was removed."""
    try:
        return bool(Secret.password_clear_sync(LEGACY_SCHEMA, LEGACY_ATTRIBUTES, None))
    except GLib.Error:
        return False


def _get(interface, method, version, key, params):
    response = requests.get(
        f"{API}/{interface}/{method}/v{version}/", params={"key": key, **params}, timeout=TIMEOUT
    )
    if response.status_code in (401, 403):
        raise AuthError("Valve did not accept this Steam Web API key.")
    response.raise_for_status()
    return response.json().get("response") or {}


def owned_games(key, steamid):
    """The account's owned games, including free ones it has played. Blocking."""
    data = _get(
        "IPlayerService", "GetOwnedGames", 1, key,
        {"steamid": steamid, "include_appinfo": 1, "include_played_free_games": 1},
    )
    return data.get("games", [])


def player_summary(key, steamid):
    data = _get("ISteamUser", "GetPlayerSummaries", 2, key, {"steamids": steamid})
    players = data.get("players", [])
    return players[0] if players else {}


def check_key(key, steamid):
    """Test a key before it is saved. Blocking.

    Returns {"name", "games", "country"}; "games" is 0 when the profile's game
    details are not visible, which the setup explains how to fix.
    """
    summary = player_summary(key, steamid)
    games = owned_games(key, steamid)
    return {
        "name": summary.get("personaname", ""),
        "games": len(games),
        "country": (summary.get("loccountrycode") or "").upper(),
    }


def account_country(key, steamid):
    """The account's country from its Steam profile, if it shows one. Blocking.

    Remembered per account, as it rarely changes; "" when the profile has none.
    """
    cache = config_mod.cache_dir() / "account_country.json"
    try:
        known = json.loads(cache.read_text())
    except (OSError, ValueError):
        known = {}
    if steamid in known:
        return known[steamid]
    country = (player_summary(key, steamid).get("loccountrycode") or "").upper()
    if len(country) == 2 and country.isalpha():
        known[steamid] = country
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(known))
        return country
    return ""
