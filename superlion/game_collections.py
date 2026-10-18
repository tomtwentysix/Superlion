"""Steam's collections (read-only) and Superlion's own collections.

Steam keeps collections in userdata/<account>/config/cloudstorage/
cloud-storage-namespace-1.json as "user-collections.<id>" entries, and lists
locally changed entries for upload to Steam Cloud in the matching
".modified.json" file. This layout is not documented by Valve; it is read as
found, and written only by sync_to_steam() while Steam is closed.
"""

import json
import os
import secrets
import shutil
import string
import time
from dataclasses import asdict, dataclass, field

from . import config as config_mod

STEAM_PREFIX = "user-collections."
SPECIAL_NAMES = {"favorite": "Favorites", "hidden": "Hidden"}
ID_ALPHABET = string.ascii_letters + string.digits + "+*"


@dataclass
class Collection:
    id: str
    name: str
    appids: list = field(default_factory=list)
    steam_id: str = ""  # Set once a Superlion collection has been synced to Steam.
    source: str = "superlion"  # "superlion" or "steam"


def _cloud_dir(config):
    return config.userdata / "config" / "cloudstorage"


def _namespace_path(config):
    return _cloud_dir(config) / "cloud-storage-namespace-1.json"


def _modified_path(config):
    return _cloud_dir(config) / "cloud-storage-namespace-1.modified.json"


def load_steam(config):
    """Steam's static collections, with Favorites first and Hidden last.

    Dynamic collections are defined by filters that only Steam evaluates, so
    they are left out.
    """
    try:
        entries = json.loads(_namespace_path(config).read_text())
    except (OSError, ValueError):
        return []
    found = []
    for key, entry in entries:
        if not key.startswith(STEAM_PREFIX) or entry.get("is_deleted"):
            continue
        try:
            value = json.loads(entry.get("value") or "{}")
        except ValueError:
            continue
        cid = value.get("id", "")
        if "filterSpec" in value or not cid or cid.startswith("partner-"):
            continue
        found.append(
            Collection(
                id=f"steam:{cid}",
                name=SPECIAL_NAMES.get(cid, value.get("name", cid)),
                appids=[int(a) for a in value.get("added", []) if str(a).isdigit()],
                steam_id=cid,
                source="steam",
            )
        )
    # Renames and deletions made in Superlion show at once, before they are synced.
    store = _load_store()
    edits = store["steam_edits"]
    # Collections Superlion created are listed under My Collections, not here as well.
    own_ids = {c.steam_id for c in store["collections"] if c.steam_id} | set(store["deleted_steam_ids"])
    present = {c.steam_id for c in found}
    for special, name in SPECIAL_NAMES.items():
        if special not in present and edits.get(special, {}).get("added"):
            found.append(Collection(id=f"steam:{special}", name=name, steam_id=special, source="steam"))
    shown = []
    for c in found:
        edit = edits.get(c.steam_id, {})
        if edit.get("deleted") or c.steam_id in own_ids:
            continue
        if edit.get("name"):
            c.name = edit["name"]
        c.appids = _apply_membership(c.appids, edit)
        shown.append(c)
    order = {"favorite": 0, "hidden": 2}
    shown.sort(key=lambda c: (order.get(c.steam_id, 1), c.name.casefold()))
    return shown


def _apply_membership(appids, edit):
    removed = set(edit.get("removed", []))
    result = [a for a in appids if a not in removed]
    result += [a for a in edit.get("added", []) if a not in result]
    return result


def is_fixed(collection):
    """Favorites and Hidden are built into Steam and cannot be renamed or deleted."""
    return collection.steam_id in SPECIAL_NAMES and collection.source == "steam"


def _store_path():
    return config_mod.config_dir() / "collections.json"


def _load_store():
    try:
        data = json.loads(_store_path().read_text())
    except (OSError, ValueError):
        data = {}
    return {
        "collections": [Collection(**c) for c in data.get("collections", [])],
        # Steam IDs of synced collections deleted in Superlion, removed from Steam on the next sync.
        "deleted_steam_ids": data.get("deleted_steam_ids", []),
        "needs_sync": data.get("needs_sync", False),
        # Renames and deletions of Steam's collections, written on the next sync.
        "steam_edits": data.get("steam_edits", {}),
    }


def _save_store(store):
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "collections": [asdict(c) for c in store["collections"]],
        "deleted_steam_ids": store["deleted_steam_ids"],
        "needs_sync": store["needs_sync"],
        "steam_edits": store["steam_edits"],
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def load_own():
    return _load_store()["collections"]


def needs_sync():
    return _load_store()["needs_sync"]


def _change(func):
    store = _load_store()
    result = func(store)
    store["needs_sync"] = True
    _save_store(store)
    return result


def create(name):
    def apply(store):
        collection = Collection(id=f"sl-{secrets.token_hex(6)}", name=name.strip())
        store["collections"].append(collection)
        return collection

    return _change(apply)


def rename(collection_id, name):
    def apply(store):
        for c in store["collections"]:
            if c.id == collection_id:
                c.name = name.strip()

    _change(apply)


def delete(collection_id):
    def apply(store):
        for c in list(store["collections"]):
            if c.id == collection_id:
                store["collections"].remove(c)
                if c.steam_id:
                    store["deleted_steam_ids"].append(c.steam_id)

    _change(apply)


def rename_steam(steam_id, name):
    store = _load_store()
    store["steam_edits"].setdefault(steam_id, {})["name"] = name.strip()
    _save_store(store)


def set_steam_member(steam_id, appid, member):
    """Add a game to, or remove it from, one of Steam's collections (including Hidden)."""
    store = _load_store()
    edit = store["steam_edits"].setdefault(steam_id, {})
    added, removed = edit.setdefault("added", []), edit.setdefault("removed", [])
    if member:
        if appid in removed:
            removed.remove(appid)
        if appid not in added:
            added.append(appid)
    else:
        if appid in added:
            added.remove(appid)
        if appid not in removed:
            removed.append(appid)
    _save_store(store)  # Steam-side edits do not mark Superlion's own collections as changed.


def has_steam_edits():
    return bool(_load_store()["steam_edits"])


def delete_steam(steam_id):
    store = _load_store()
    store["steam_edits"][steam_id] = {"deleted": True}
    _save_store(store)


def set_member(collection_id, appid, member):
    def apply(store):
        for c in store["collections"]:
            if c.id == collection_id:
                if member and appid not in c.appids:
                    c.appids.append(appid)
                elif not member and appid in c.appids:
                    c.appids.remove(appid)

    _change(apply)


def _new_steam_id():
    return "uc-" + "".join(secrets.choice(ID_ALPHABET) for _ in range(12))


def sync_to_steam(config, include_own=True):
    """Write Superlion's collections into Steam's collection data. Steam must be closed.

    Each collection becomes (or updates) a Steam collection with the same name
    and games, and is listed as changed so Steam uploads it to Steam Cloud when
    it next starts. Collections deleted in Superlion are marked deleted in Steam.
    Both files are backed up first.
    """
    store = _load_store()
    path, modified_path = _namespace_path(config), _modified_path(config)
    entries = json.loads(path.read_text())
    modified = json.loads(modified_path.read_text()) if modified_path.is_file() else []
    index = {key: i for i, (key, _entry) in enumerate(entries)}
    now = int(time.time())

    def upsert(key, entry):
        if key in index:
            entry.setdefault("version", entries[index[key]][1].get("version", "0"))
            entries[index[key]] = [key, entry]
        else:
            entry.setdefault("version", "0")
            index[key] = len(entries)
            entries.append([key, entry])
        if key not in modified:
            modified.append(key)

    for collection in store["collections"] if include_own else []:
        if not collection.steam_id:
            collection.steam_id = _new_steam_id()
        key = STEAM_PREFIX + collection.steam_id
        value = {"id": collection.steam_id, "name": collection.name, "added": collection.appids, "removed": []}
        # Steam's own recent collection entries carry the same merge settings.
        upsert(key, {
            "key": key,
            "timestamp": now,
            "value": json.dumps(value, separators=(",", ":")),
            "conflictResolutionMethod": "custom",
            "strMethodId": "union-collections",
        })

    for steam_id, edit in store["steam_edits"].items():
        key = STEAM_PREFIX + steam_id
        if edit.get("deleted"):
            upsert(key, {"key": key, "timestamp": now, "is_deleted": True})
        else:
            # Keep Steam's own fields, such as its merge settings; change only what was edited.
            if key in index:
                entry = dict(entries[index[key]][1])
                value = json.loads(entry.get("value") or "{}")
            else:  # Favorites or Hidden before Steam has ever created them.
                entry = {"key": key, "conflictResolutionMethod": "custom", "strMethodId": "union-collections"}
                value = {"id": steam_id, "name": SPECIAL_NAMES.get(steam_id, steam_id), "added": [], "removed": []}
            if edit.get("name"):
                value["name"] = edit["name"]
            if edit.get("added") or edit.get("removed"):
                value["added"] = _apply_membership(value.get("added", []), edit)
                # Steam merges collections across devices; recording removals stops them returning.
                removed = [a for a in value.get("removed", []) if a not in edit.get("added", [])]
                value["removed"] = removed + [a for a in edit.get("removed", []) if a not in removed]
            entry.update(timestamp=now, value=json.dumps(value, separators=(",", ":"), ensure_ascii=False))
            upsert(key, entry)

    for steam_id in store["deleted_steam_ids"] if include_own else []:
        key = STEAM_PREFIX + steam_id
        upsert(key, {"key": key, "timestamp": now, "is_deleted": True})

    stamp = time.strftime("%Y%m%d-%H%M%S")
    for source in (path, modified_path):
        if source.is_file():
            shutil.copy2(source, source.with_name(f"{source.name}.superlion-bak-{stamp}"))
    for target, data in ((path, entries), (modified_path, modified)):
        tmp = target.with_name(f".{target.name}.tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
        if target.is_file():
            os.chmod(tmp, target.stat().st_mode & 0o7777)
        os.replace(tmp, target)

    store["steam_edits"] = {}
    if include_own:
        store["deleted_steam_ids"] = []
        store["needs_sync"] = False
    _save_store(store)
    return len(store["collections"])
