"""The wishlist of the account signed in to the store inside Superlion.

Steam's sign-in token comes from a store page (ui.webview.run_in_store), which
renews it as it loads.
"""

import requests

from .store_api import TIMEOUT

WISHLIST_URL = "https://api.steampowered.com/IWishlistService/GetWishlist/v1/"


def wishlist(steamid, token=""):
    """App IDs on an account's wishlist, in the order its owner set.

    Public wishlists need no token; a private one needs the store sign-in's.
    """
    params = {"steamid": steamid}
    if token:
        params["access_token"] = token
    response = requests.get(WISHLIST_URL, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    items = (response.json().get("response") or {}).get("items", [])
    # Unranked items have priority 0 and come after ranked ones.
    items.sort(key=lambda i: (i.get("priority", 0) or 1 << 31, i.get("date_added", 0)))
    return [i["appid"] for i in items]
