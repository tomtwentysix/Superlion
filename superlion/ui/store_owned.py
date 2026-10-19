"""Owned and family-shared games from the Steam store's own session.

When the Web API returns no games, Superlion reads the list the Steam store
keeps for the signed-in browser (the one it uses to mark games "In Library").
It is loaded in Superlion's own browser view, which shares the sign-in made on
Steam's own pages, and only the page text is read. This is not documented by
Valve, so it is used only as a fallback.

Family library games are never in either owned list. IFamilyGroupsService does
not accept a Web API key, so the store session's own access token is read from
the same browser view and used only for that request; it is never stored.
"""

import json

import gi
import requests

gi.require_version("WebKit", "6.0")
from gi.repository import GLib, WebKit  # noqa: E402

from .. import appinfo, auth  # noqa: E402
from .webview import network_session  # noqa: E402

USERDATA_URL = "https://store.steampowered.com/dynamicstore/userdata/"
TOKEN_URL = "https://store.steampowered.com/pointssummary/ajaxgetasyncconfig"
FAMILY_API = f"{auth.API}/IFamilyGroupsService"
TIMEOUT = 30  # seconds

_active = set()  # Keeps hidden views alive until they finish.


def _fetch_json(url, callback):
    """Call callback(the page parsed as JSON, or None) on the main thread."""
    view = WebKit.WebView(network_session=network_session())
    _active.add(view)
    state = {"done": False, "timer": 0}

    def finish(data):
        if state["done"]:
            return
        state["done"] = True
        if state["timer"]:
            GLib.source_remove(state["timer"])
        _active.discard(view)
        callback(data)

    def on_text(webview, result):
        try:
            text = webview.evaluate_javascript_finish(result).to_string()
            finish(json.loads(text))
        except (GLib.Error, ValueError):
            finish(None)

    def on_load(webview, event):
        if event == WebKit.LoadEvent.FINISHED:
            webview.evaluate_javascript(
                "document.body ? document.body.innerText : ''", -1, None, None, None, on_text
            )

    view.connect("load-changed", on_load)
    view.connect("load-failed", lambda *_: (finish(None), True)[1])
    state["timer"] = GLib.timeout_add_seconds(TIMEOUT, lambda: (finish(None), GLib.SOURCE_REMOVE)[1])
    view.load_uri(url)


def fetch_owned_appids(callback):
    """Call callback(list of app IDs, or None if unavailable) on the main thread."""

    def done(data):
        if not isinstance(data, dict):
            callback(None)
            return
        appids = [int(a) for a in data.get("rgOwnedApps", []) if str(a).isdigit()]
        callback(appids or None)  # Empty means the browser is not signed in to the store.

    _fetch_json(USERDATA_URL, done)


def owned_entries(appids, steam_root):
    """Owned-games entries, like the Web API's, for the games among the app IDs."""
    known = appinfo.load(steam_root)
    entries = []
    for appid in appids:
        info = known.get(appid)
        if info and info.get("type") == "game" and info.get("name"):
            entries.append({"appid": appid, "name": info["name"]})
    return entries


def _family_call(method, token, params):
    response = requests.get(
        f"{FAMILY_API}/{method}/v1/", params={"access_token": token, **params}, timeout=auth.TIMEOUT
    )
    response.raise_for_status()
    return response.json().get("response") or {}


def shared_entries(apps, steamid):
    """Owned-games entries for the family library apps this account can play.

    apps is GetSharedLibraryApps' list: dicts with "appid", "name",
    "owner_steamids" (strings), "exclude_reason" (0 when shareable),
    "app_type" (1 for games) and "rt_last_played".
    """
    entries = []
    for app in apps:
        if app.get("exclude_reason") or app.get("app_type", 1) != 1 or not app.get("name"):
            continue
        if steamid in app.get("owner_steamids", []):
            continue
        entries.append({
            "appid": int(app["appid"]),
            "name": app["name"],
            "rtime_last_played": int(app.get("rt_last_played") or 0),
        })
    return entries


def fetch_family_entries(steamid, callback):
    """Call callback(family library entries, or None if unavailable) on the main thread."""

    def lookup(token):
        group = _family_call("GetFamilyGroupForUser", token, {"steamid": steamid})
        groupid = group.get("family_groupid")
        if not groupid or group.get("is_not_member_of_any_group"):
            return []
        library = _family_call(
            "GetSharedLibraryApps", token,
            {"family_groupid": groupid, "steamid": steamid, "include_own": "false"},
        )
        return shared_entries(library.get("apps", []), steamid)

    def on_token(data):
        token = (data or {}).get("data", {}).get("webapi_token") if isinstance(data, dict) else None
        if not token:
            callback(None)  # Not signed in to the Steam store here.
            return
        auth.run_async(lambda: lookup(token), lambda entries, error: callback(None if error else entries))

    _fetch_json(TOKEN_URL, on_token)
