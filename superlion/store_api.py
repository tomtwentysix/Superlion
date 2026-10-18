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
    """Recent announcements posted by the game's developers on Steam."""
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
