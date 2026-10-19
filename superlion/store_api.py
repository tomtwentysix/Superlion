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
QUERY_URL = "https://api.steampowered.com/IStoreQueryService/Query/v1"
ASSETS = "https://shared.akamai.steamstatic.com/store_item_assets/"
# The After Hours section lists games with Steam's content descriptor 3, as Steam's
# own section for them does. Store queries cannot filter on descriptors, so these
# games are found by tags (Sexual Content, Hentai, Nudity) and then checked.
AFTER_HOURS_DESCRIPTOR = 3
AFTER_HOURS_TAGS = [12095, 9130, 6650]
# Store query sort orders.
TOP_SELLERS = 10
TRENDING = 11


def _item(item):
    """A store item in the shape items() returns."""
    option = item.get("best_purchase_option") or {}
    assets = item.get("assets") or {}

    def art(name):
        return ASSETS + assets["asset_url_format"].replace("${FILENAME}", assets[name]) if name in assets else ""

    discount = int(option.get("discount_pct", 0) or 0)
    return {
        "id": item["appid"],
        "name": item.get("name", ""),
        # The header image is the shape of the store's capsules, unlike main_capsule.
        "large_capsule_image": art("header"),
        "tiny_image": art("small_capsule"),
        "price_text": "Free" if item.get("is_free") else option.get("formatted_final_price", ""),
        "original_text": option.get("formatted_original_price", ""),
        "final_cents": int(option.get("final_price_in_cents", 0) or 0),
        "discount_percent": discount,
        "discounted": bool(discount),
        "release": int((item.get("release") or {}).get("steam_release_date", 0) or 0),
        "after_hours": AFTER_HOURS_DESCRIPTOR in (item.get("content_descriptorids") or []),
    }


DATA_REQUEST = {"include_assets": True, "include_release": True, "include_ratings": True}


def items(appids, region):
    """Names, prices and art for many apps at once, as {app ID: item}.

    Items have featured()'s "id", "name", "large_capsule_image", "tiny_image",
    "discounted" and "discount_percent", plus "price_text" and "original_text"
    formatted by the store, "final_cents", "release" (Unix time, or 0) and
    "after_hours" (whether the game belongs in After Hours).
    """
    found = {}
    appids = list(appids)
    for start in range(0, len(appids), 50):
        request = {
            "ids": [{"appid": a} for a in appids[start:start + 50]],
            "context": {"language": "english", "country_code": region},
            "data_request": DATA_REQUEST,
        }
        data = _get_json(ITEMS_URL, {"input_json": json.dumps(request)}, LIST_TTL)
        for item in (data.get("response") or {}).get("store_items", []):
            if item.get("success") == 1:
                found[item["appid"]] = _item(item)
    return found


def purchase_options(appid, region):
    """Every way to buy an app, editions and bundles included.

    Each is {"packageid" or "bundleid": ID, "name", "price_text", "original_text",
    "discount_percent"}, the form the cart API takes items in.
    """
    request = {
        "ids": [{"appid": appid}],
        "context": {"language": "english", "country_code": region},
        "data_request": {"include_all_purchase_options": True},
    }
    data = _get_json(ITEMS_URL, {"input_json": json.dumps(request)}, LIST_TTL)
    found = []
    for item in (data.get("response") or {}).get("store_items", []):
        for option in item.get("purchase_options", []):
            kind = "packageid" if option.get("packageid") else "bundleid"
            found.append({
                kind: option[kind],
                "name": option.get("purchase_option_name", ""),
                "price_text": option.get("formatted_final_price", ""),
                "original_text": option.get("formatted_original_price", ""),
                "discount_percent": int(option.get("discount_pct", 0) or 0),
            })
    return found


def cart_items(line_items, region):
    """The cart API's line items described for display, in order.

    Each is {"line_item_id", "name", "image", "price_text", "original_text",
    "discount_percent", "gift"}. Packages have no art of their own, so they
    use their first game's.
    """
    ids = [{"packageid": i["packageid"]} if i.get("packageid") else {"bundleid": i["bundleid"]} for i in line_items]
    request = {
        "ids": ids,
        "context": {"language": "english", "country_code": region},
        "data_request": {"include_assets": True, "include_basic_info": True},
    }
    data = _get_json(ITEMS_URL, {"input_json": json.dumps(request)}, LIST_TTL)
    described = {(i.get("item_type"), i.get("id")): i for i in (data.get("response") or {}).get("store_items", [])}
    games = items({a for i in described.values() for a in (i.get("included_appids") or [])[:1]}, region)
    found = []
    for line in line_items:
        key = (1, line["packageid"]) if line.get("packageid") else (2, line["bundleid"])
        item = described.get(key, {})
        option = item.get("best_purchase_option") or {}
        assets = item.get("assets") or {}
        if "header" in assets:
            image = ASSETS + assets["asset_url_format"].replace("${FILENAME}", assets["header"])
        else:
            image = games.get(next(iter(item.get("included_appids") or []), 0), {}).get("tiny_image", "")
        found.append({
            "line_item_id": line["line_item_id"],
            "name": item.get("name", ""),
            "image": image,
            "price_text": option.get("formatted_final_price")
            or (line.get("price_when_added") or {}).get("formatted_amount", ""),
            "original_text": option.get("formatted_original_price", ""),
            "discount_percent": int(option.get("discount_pct", 0) or 0),
            "gift": bool((line.get("flags") or {}).get("is_gift")),
        })
    return found


def after_hours(region, sort=TOP_SELLERS, tagid=None, coming_soon=False, discounted=False, free=False):
    """After Hours games as a list of items(), optionally of one tag, such as Visual Novel."""
    filters = {
        "type_filters": {"include_games": True},
        "tagids_must_match": [{"tagids": AFTER_HOURS_TAGS}] + ([{"tagids": [tagid]}] if tagid else []),
        "coming_soon_only" if coming_soon else "released_only": True,
    }
    if discounted:
        filters["price_filters"] = {"min_discount_percent": 1}
    elif free:
        filters["price_filters"] = {"only_free_items": True}
    request = {
        "query": {"count": 200, "sort": sort, "filters": filters},
        "context": {"language": "english", "country_code": region},
        "data_request": {"include_basic_info": True, **DATA_REQUEST},
    }
    data = _get_json(QUERY_URL, {"input_json": json.dumps(request)}, LIST_TTL)
    found = [_item(i) for i in (data.get("response") or {}).get("store_items", []) if i.get("success") == 1]
    return [item for item in found if item["after_hours"]]


def after_hours_search(term, region):
    """After Hours games matching a search, as items()."""
    ids = [item["id"] for item in search(term, region)]
    found = items(ids, region)
    return [found[a] for a in ids if a in found and found[a]["after_hours"]]


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
