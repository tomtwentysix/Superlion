"""Public Steam store data, which needs no sign-in.

These endpoints are used widely by third-party tools but are not documented by
Valve. Responses are cached on disk; the app details endpoint is limited to
roughly 200 requests every five minutes, so its requests are made one at a time.
"""

import hashlib
import json
import os
import threading
import time

import requests

from . import config as config_mod

STORE = "https://store.steampowered.com"
TIMEOUT = 20
LIST_TTL = 6 * 3600
DETAILS_TTL = 24 * 3600
DETAILS_MIN_GAP = 1.5  # seconds between uncached app details requests

CURRENCY_SYMBOLS = {
    "AUD": "A$",
    "CAD": "CA$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "NZD": "NZ$",
    "USD": "$",
}
NO_DECIMALS = {"JPY", "KRW", "IDR", "VND"}

_details_lock = threading.Lock()
_last_details = 0.0


def _cache_file(url, params):
    key = hashlib.sha1((url + json.dumps(params, sort_keys=True)).encode()).hexdigest()
    return config_mod.cache_dir() / "store" / f"{key}.json"


def _get_json(url, params, ttl):
    path = _cache_file(url, params)
    try:
        if time.time() - path.stat().st_mtime < ttl:
            return json.loads(path.read_text())
    except (OSError, ValueError):
        pass
    response = requests.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)
    return data


def featured(region):
    """Store home categories: {"specials": [...], "top_sellers": [...], ...}."""
    data = _get_json(f"{STORE}/api/featuredcategories", {"cc": region, "l": "english"}, LIST_TTL)
    return {
        key: [item for item in data.get(key, {}).get("items", []) if item.get("type") == 0]
        for key in ("specials", "top_sellers", "new_releases", "coming_soon")
    }


def genre(name, region):
    """A genre's lists, such as {"Top Sellers": [app IDs], "New Releases": [...]}."""
    data = _get_json(f"{STORE}/api/getappsingenre/", {"genre": name, "cc": region, "l": "english"}, LIST_TTL)
    return {
        tab.get("name", key): list(dict.fromkeys(i["id"] for i in tab.get("items", []) if i.get("type") == 0))
        for key, tab in (data.get("tabs") or {}).items()
    }


ITEMS_URL = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1"
ASSETS = "https://shared.akamai.steamstatic.com/store_item_assets/"


def items(appids, region):
    """Names, prices and art for many apps at once, as {app ID: item}.

    Items have featured()'s "id", "name", "large_capsule_image", "tiny_image",
    "discounted" and "discount_percent", plus "price_text" and "original_text"
    formatted by the store, "final_cents" and "release" (Unix time, or 0).
    """
    found = {}
    appids = list(appids)
    for start in range(0, len(appids), 50):
        request = {
            "ids": [{"appid": a} for a in appids[start:start + 50]],
            "context": {"language": "english", "country_code": region},
            "data_request": {"include_assets": True, "include_release": True},
        }
        data = _get_json(ITEMS_URL, {"input_json": json.dumps(request)}, LIST_TTL)
        for item in (data.get("response") or {}).get("store_items", []):
            if item.get("success") != 1:
                continue
            option = item.get("best_purchase_option") or {}
            assets = item.get("assets") or {}

            def art(name, assets=assets):
                return ASSETS + assets["asset_url_format"].replace("${FILENAME}", assets[name]) if name in assets else ""

            discount = int(option.get("discount_pct", 0) or 0)
            found[item["appid"]] = {
                "id": item["appid"],
                "name": item.get("name", ""),
                "large_capsule_image": art("main_capsule"),
                "tiny_image": art("small_capsule"),
                "price_text": "Free" if item.get("is_free") else option.get("formatted_final_price", ""),
                "original_text": option.get("formatted_original_price", ""),
                "final_cents": int(option.get("final_price_in_cents", 0) or 0),
                "discount_percent": discount,
                "discounted": bool(discount),
                "release": int((item.get("release") or {}).get("steam_release_date", 0) or 0),
            }
    return found


def search(term, region):
    data = _get_json(
        f"{STORE}/api/storesearch/", {"term": term, "cc": region, "l": "english"}, LIST_TTL
    )
    return [item for item in data.get("items", []) if item.get("type") == "app"]


def details(appid, region):
    """Store details for one app, or None when Steam has no store page for it."""
    global _last_details
    url = f"{STORE}/api/appdetails"
    params = {"appids": str(appid), "cc": region, "l": "english"}
    with _details_lock:
        cached = _cache_file(url, params)
        if not cached.is_file() or time.time() - cached.stat().st_mtime >= DETAILS_TTL:
            wait = DETAILS_MIN_GAP - (time.monotonic() - _last_details)
            if wait > 0:
                time.sleep(wait)
            _last_details = time.monotonic()
        data = _get_json(url, params, DETAILS_TTL)
    entry = data.get(str(appid), {})
    return entry.get("data") if entry.get("success") else None


def reviews(appid):
    """Review summary such as ("Very Positive", 987364), or None."""
    data = _get_json(
        f"{STORE}/appreviews/{appid}",
        {"json": 1, "num_per_page": 0, "purchase_type": "all", "language": "all"},
        DETAILS_TTL,
    )
    summary = data.get("query_summary") or {}
    if not summary.get("total_reviews"):
        return None
    return summary.get("review_score_desc", ""), int(summary["total_reviews"])


NEWS_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
NEWS_TTL = 3600


def news(appid, count=5):
    data = _get_json(
        NEWS_URL,
        {"appid": appid, "count": count, "maxlength": 0, "feeds": "steam_community_announcements"},
        NEWS_TTL,
    )
    return (data.get("appnews") or {}).get("newsitems", [])


def format_price(cents, currency):
    if cents is None:
        return ""
    if cents == 0:
        return "Free"
    symbol = CURRENCY_SYMBOLS.get(currency, f"{currency} ")
    if currency in NO_DECIMALS:
        return f"{symbol}{cents:,}"
    return f"{symbol}{cents / 100:,.2f}"
