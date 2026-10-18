"""Owned games from the Steam store's own list, for profiles with private game details.

When the Web API returns no games, Superlion reads the list the Steam store
keeps for the signed-in browser (the one it uses to mark games "In Library").
It is loaded in Superlion's own browser view, which shares the sign-in made on
Steam's own pages, and only the page text is read. This is not documented by
Valve, so it is used only as a fallback.
"""

import json

import gi

gi.require_version("WebKit", "6.0")
from gi.repository import GLib, WebKit  # noqa: E402

from .. import appinfo  # noqa: E402
from .webview import network_session  # noqa: E402

USERDATA_URL = "https://store.steampowered.com/dynamicstore/userdata/"
TIMEOUT = 30  # seconds

_active = set()  # Keeps hidden views alive until they finish.


def fetch_owned_appids(callback):
    """Call callback(list of app IDs, or None if unavailable) on the main thread."""
    view = WebKit.WebView(network_session=network_session())
    _active.add(view)
    state = {"done": False, "timer": 0}

    def finish(appids):
        if state["done"]:
            return
        state["done"] = True
        if state["timer"]:
            GLib.source_remove(state["timer"])
        _active.discard(view)
        callback(appids)

    def on_text(webview, result):
        try:
            text = webview.evaluate_javascript_finish(result).to_string()
            data = json.loads(text)
        except (GLib.Error, ValueError):
            finish(None)
            return
        appids = [int(a) for a in data.get("rgOwnedApps", []) if str(a).isdigit()]
        finish(appids or None)  # Empty means the browser is not signed in to the store.

    def on_load(webview, event):
        if event == WebKit.LoadEvent.FINISHED:
            webview.evaluate_javascript(
                "document.body ? document.body.innerText : ''", -1, None, None, None, on_text
            )

    view.connect("load-changed", on_load)
    view.connect("load-failed", lambda *_: (finish(None), True)[1])
    state["timer"] = GLib.timeout_add_seconds(TIMEOUT, lambda: (finish(None), GLib.SOURCE_REMOVE)[1])
    view.load_uri(USERDATA_URL)


def owned_entries(appids, steam_root):
    """Owned-games entries, like the Web API's, for the games among the app IDs."""
    known = appinfo.load(steam_root)
    entries = []
    for appid in appids:
        info = known.get(appid)
        if info and info.get("type") == "game" and info.get("name"):
            entries.append({"appid": appid, "name": info["name"]})
    return entries
