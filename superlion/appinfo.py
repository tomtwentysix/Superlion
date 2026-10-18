"""Release dates and genres from Steam's local app database (appcache/appinfo.vdf).

The Steam client keeps metadata for every app the account has seen, installed
or not, in this binary file. Only the few fields Superlion uses are extracted,
and the result is cached until Steam rewrites the file.
"""

import json
import os
import struct
from pathlib import Path

from . import config as config_mod

CACHE_VERSION = 3  # Raised when the extracted fields change, so old caches are rebuilt.

VR_NONE, VR_SUPPORTED, VR_REQUIRED = 0, 1, 2
# Store categories: 31 "VR Support" (older), 53 "VR Supported", 54 "VR Only".
VR_CATEGORIES = {"category_31", "category_53", "category_54"}

MAGIC_V28 = 0x07564428
MAGIC_V29 = 0x07564429  # Keys are indexes into a string table at the end of the file.

# Steam's genre IDs, as used by the store; names match its English store pages.
GENRES = {
    1: "Action",
    2: "Strategy",
    3: "RPG",
    4: "Casual",
    9: "Racing",
    18: "Sports",
    23: "Indie",
    25: "Adventure",
    28: "Simulation",
    29: "Massively Multiplayer",
    37: "Free to Play",
    51: "Animation & Modeling",
    52: "Audio Production",
    53: "Design & Illustration",
    54: "Education",
    55: "Photo Editing",
    56: "Software Training",
    57: "Utilities",
    58: "Video Production",
    59: "Web Publishing",
    60: "Game Development",
    70: "Early Access",
    71: "Sexual Content",
    72: "Nudity",
    73: "Violent",
    74: "Gore",
    81: "Documentary",
    84: "Tutorial",
}


def _cache_path():
    return config_mod.cache_dir() / "appinfo.json"


def _parse(data):
    """{appid: {"release": unix time or 0, "genres": [names]}} from appinfo.vdf bytes."""
    magic, _universe = struct.unpack_from("<II", data, 0)
    if magic == MAGIC_V29:
        (table_offset,) = struct.unpack_from("<q", data, 8)
        (count,) = struct.unpack_from("<I", data, table_offset)
        strings, pos = [], table_offset + 4
        for _ in range(count):
            end = data.index(b"\0", pos)
            strings.append(data[pos:end].decode("utf-8", "replace"))
            pos = end + 1
        pos = 16
    elif magic == MAGIC_V28:
        strings, pos = None, 8
    else:
        raise ValueError(f"Unsupported appinfo.vdf version {magic:#x}")

    def read_key(pos):
        if strings is not None:
            return strings[struct.unpack_from("<I", data, pos)[0]], pos + 4
        end = data.index(b"\0", pos)
        return data[pos:end].decode("utf-8", "replace"), end + 1

    def read_map(pos):
        node = {}
        while True:
            kind = data[pos]
            pos += 1
            if kind == 8:
                return node, pos
            key, pos = read_key(pos)
            if kind == 0:
                node[key], pos = read_map(pos)
            elif kind == 1:
                end = data.index(b"\0", pos)
                node[key] = data[pos:end].decode("utf-8", "replace")
                pos = end + 1
            elif kind in (2, 3):
                node[key] = struct.unpack_from("<i" if kind == 2 else "<f", data, pos)[0]
                pos += 4
            elif kind == 7:
                node[key] = struct.unpack_from("<Q", data, pos)[0]
                pos += 8
            else:
                raise ValueError(f"Unknown value type {kind} at offset {pos - 1}")

    # Each entry: app ID, size, info state, last updated, PICS token, text SHA-1,
    # change number, binary SHA-1, then the app's binary KeyValues.
    header = 4 + 4 + 8 + 20 + 4 + 20
    apps = {}
    while True:
        (appid,) = struct.unpack_from("<I", data, pos)
        if appid == 0:
            break
        (size,) = struct.unpack_from("<I", data, pos + 4)
        start = pos + 8
        try:
            node, _ = read_map(start + header)
        except (ValueError, IndexError, struct.error):
            node = {}
        common = (node.get("appinfo") or {}).get("common") or {}
        release = common.get("original_release_date") or common.get("steam_release_date") or 0
        genre_ids = (common.get("genres") or {}).values()
        apps[appid] = {
            "name": common.get("name", ""),
            "type": str(common.get("type", "")).lower(),
            "release": int(release) if str(release).isdigit() else 0,
            "vr": _vr_level(common),
            # Retired genre IDs that the store no longer shows are skipped.
            "genres": [GENRES[int(g)] for g in genre_ids if str(g).isdigit() and int(g) in GENRES],
        }
        pos = start + size
    return apps


def _vr_level(common):
    categories = set(common.get("category") or {})
    if common.get("onlyvrsupport") == 1 or "category_54" in categories:
        return VR_REQUIRED
    if (
        common.get("openvrsupport") == 1
        or "controllervr" in common
        or "playareavr" in common
        or categories & VR_CATEGORIES
    ):
        return VR_SUPPORTED
    return VR_NONE


def load(steam_root):
    """App metadata keyed by app ID; {} when Steam's database cannot be read."""
    source = Path(steam_root) / "appcache" / "appinfo.vdf"
    try:
        mtime = source.stat().st_mtime
    except OSError:
        return {}
    cache = _cache_path()
    try:
        cached = json.loads(cache.read_text())
        if (
            cached.get("version") == CACHE_VERSION
            and cached.get("source") == str(source)
            and cached.get("mtime") == mtime
        ):
            return {int(k): v for k, v in cached["apps"].items()}
    except (OSError, ValueError, KeyError):
        pass
    try:
        apps = _parse(source.read_bytes())
    except (OSError, ValueError, struct.error):
        return {}
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"version": CACHE_VERSION, "source": str(source), "mtime": mtime, "apps": apps})
    )
    os.replace(tmp, cache)
    return apps
