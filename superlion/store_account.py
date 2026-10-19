"""The wishlist and cart of the account signed in to the store inside Superlion.

WebKit keeps the store's cookies in cookies.sqlite, in Firefox's format.
steamLoginSecure holds "<SteamID64>||<access token>", URL-encoded. The store
accepts a form when its sessionid matches the sessionid cookie, so a random
value sent as both is enough.
"""

import secrets
import sqlite3
from contextlib import closing
from urllib.parse import unquote

import requests

from . import config as config_mod
from .store_api import STORE, TIMEOUT

WISHLIST_URL = "https://api.steampowered.com/IWishlistService/GetWishlist/v1/"
CART_URL = "https://api.steampowered.com/IAccountCartService/GetCart/v1/"


def _login_cookie():
    path = config_mod.data_dir() / "webkit" / "cookies.sqlite"
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
            row = db.execute(
                "SELECT value FROM moz_cookies WHERE name = 'steamLoginSecure' AND host LIKE '%store.steampowered.com'"
            ).fetchone()
    except sqlite3.Error:
        return ""
    return row[0] if row else ""


def signed_in():
    return bool(_login_cookie())


def _access_token():
    return unquote(_login_cookie()).partition("||")[2]


def set_wishlisted(appid, add):
    """Add an app to the wishlist, or remove it. True if the store accepted it."""
    login = _login_cookie()
    if not login:
        return False
    session = secrets.token_hex(12)
    response = requests.post(
        f"{STORE}/api/{'addtowishlist' if add else 'removefromwishlist'}",
        data={"sessionid": session, "appid": appid},
        cookies={"sessionid": session, "steamLoginSecure": login},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return bool(response.json().get("success"))


def wishlist(steamid):
    """App IDs on an account's wishlist, in the order its owner set.

    Public wishlists need no sign-in; a private one needs the store sign-in.
    """
    params = {"steamid": steamid}
    token = _access_token()
    if token:
        params["access_token"] = token
    response = requests.get(WISHLIST_URL, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    items = (response.json().get("response") or {}).get("items", [])
    # Unranked items have priority 0 and come after ranked ones.
    items.sort(key=lambda i: (i.get("priority", 0) or 1 << 31, i.get("date_added", 0)))
    return [i["appid"] for i in items]


def cart_count(region):
    """How many items are in the cart, or None when unknown."""
    token = _access_token()
    if not token:
        return None
    try:
        response = requests.get(CART_URL, params={"access_token": token, "user_country": region}, timeout=TIMEOUT)
        response.raise_for_status()
        return len(((response.json().get("response") or {}).get("cart") or {}).get("line_items", []))
    except (requests.RequestException, ValueError):
        return None
