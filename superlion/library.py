"""Installed and owned games, read from Steam's local files."""

import os
import re
import shlex
import shutil
import time
from urllib.parse import quote
from pathlib import Path

from gi.repository import GObject

from . import vdf

# Runtime and compatibility tools that Steam installs like games.
TOOL_PREFIXES = ("Proton", "Steam Linux Runtime", "Steamworks Common", "SteamVR Performance Test")

ART_NAMES = {
    "cover": ("library_600x900.jpg", "library_capsule.jpg"),
    "hero": ("library_hero.jpg",),
    "logo": ("logo.png",),
    "header": ("header.jpg", "library_header.jpg"),
}
# Custom artwork set in Steam's "Manage > Set custom artwork", per kind.
GRID_SUFFIXES = {"cover": "p", "hero": "_hero", "logo": "_logo", "header": ""}


class Game(GObject.Object):
    __gtype_name__ = "SuperlionGame"

    # Non-Steam games use unsigned 32-bit IDs, which do not fit a plain int property.
    appid = GObject.Property(type=GObject.TYPE_INT64)
    name = GObject.Property(type=str)
    non_steam = GObject.Property(type=bool, default=False)
    installed = GObject.Property(type=bool, default=False)
    size = GObject.Property(type=GObject.TYPE_INT64)
    install_dir = GObject.Property(type=str)
    library = GObject.Property(type=str)
    last_played = GObject.Property(type=GObject.TYPE_INT64)
    release_date = GObject.Property(type=GObject.TYPE_INT64)
    genres = GObject.Property(type=GObject.TYPE_STRV)
    vr = GObject.Property(type=int, default=0)  # 0 none, 1 supported, 2 required
    # The Steam store entry used for store pages, news and metadata. For Steam games
    # this is the game itself; for non-Steam games it is a matched store game, or 0.
    store_appid = GObject.Property(type=GObject.TYPE_INT64)
    # Steam download state shown on the cover, e.g. "Updating 42%"; "" when none.
    download_label = GObject.Property(type=str, default="")
    download_progress = GObject.Property(type=float, default=-1.0)  # -1 when not downloading
    cover = GObject.Property(type=str)
    hero = GObject.Property(type=str)
    logo = GObject.Property(type=str)
    header = GObject.Property(type=str)

    def __init__(self, **props):
        super().__init__(**props)

    @property
    def run_uri(self):
        if self.props.non_steam:
            # Steam's game ID for a shortcut: the app ID in the high 32 bits,
            # with the "shortcut" type flag set in the low bits.
            return f"steam://rungameid/{(self.props.appid << 32) | 0x02000000}"
        return f"steam://rungameid/{self.props.appid}"


def is_tool(name):
    return name.startswith(TOOL_PREFIXES)


def find_art(steam_root, userdata, appid):
    """Local artwork paths for an app, keyed by kind; missing kinds are ''."""
    cache = Path(steam_root) / "appcache" / "librarycache"
    app_dir = cache / str(appid)
    grid = Path(userdata) / "config" / "grid" if userdata else None
    art = {}
    for kind, names in ART_NAMES.items():
        art[kind] = ""
        if grid is not None:
            for ext in ("png", "jpg"):
                custom = grid / f"{appid}{GRID_SUFFIXES[kind]}.{ext}"
                if custom.is_file():
                    art[kind] = str(custom)
                    break
        if art[kind]:
            continue
        for name in names:
            # Older clients store files directly in the app folder (or flat in
            # the cache); newer ones put each image in a hashed subfolder.
            direct = [app_dir / name, cache / f"{appid}_{name}"]
            hashed = sorted(app_dir.glob(f"*/{name}")) if app_dir.is_dir() else []
            match = next((p for p in direct + hashed if p.is_file()), None)
            if match:
                art[kind] = str(match)
                break
    return art


def read_last_played(localconfig_path):
    """LastPlayed timestamps from localconfig.vdf, as a fallback for manifests."""
    try:
        data = vdf.load(localconfig_path)
    except OSError:
        return {}
    apps = vdf.get_path(data, "UserLocalConfigStore", "Software", "Valve", "Steam", "apps") or {}
    result = {}
    for appid, info in apps.items():
        if appid.isdigit() and isinstance(info, dict):
            value = info.get("LastPlayed", "0")
            if value.isdigit():
                result[int(appid)] = int(value)
    return result


def load_installed(config):
    """Games installed in the enabled library folders, excluding Steam's tools."""
    last_played = read_last_played(config.localconfig_path)
    games = {}
    for folder in config.library_folders():
        steamapps = Path(folder) / "steamapps"
        for manifest in sorted(steamapps.glob("appmanifest_*.acf")):
            try:
                state = vdf.get_path(vdf.load(manifest), "AppState") or {}
            except OSError:
                continue
            appid = int(state.get("appid", "0") or 0)
            name = state.get("name", "")
            if not appid or not name or is_tool(name) or appid in games:
                continue
            played = int(state.get("LastPlayed", "0") or 0) or last_played.get(appid, 0)
            games[appid] = Game(
                appid=appid,
                name=name,
                installed=True,
                size=int(state.get("SizeOnDisk", "0") or 0),
                install_dir=str(steamapps / "common" / state.get("installdir", "")),
                library=str(folder),
                last_played=played,
                **find_art(config.root, config.userdata, appid),
            )
    return list(games.values())


def shortcuts_path(config):
    return config.userdata / "config" / "shortcuts.vdf"


def read_shortcuts(config):
    """Entries from shortcuts.vdf keyed by app ID; {} when there are none."""
    try:
        data = vdf.load_binary(shortcuts_path(config))
    except (OSError, ValueError):
        return {}
    entries = vdf.get_path(data, "shortcuts") or {}
    result = {}
    for entry in entries.values():
        if isinstance(entry, dict) and isinstance(field(entry, "appid"), int):
            result[field(entry, "appid")] = entry
    return result


def field(entry, name):
    """Shortcut keys vary in case between Steam versions (AppName, appname)."""
    return next((v for k, v in entry.items() if k.lower() == name.lower()), None)


def _shortcut_folder(entry):
    """The game's folder: StartDir, or the executable's folder when StartDir is relative."""
    start = field(entry, "StartDir") or ""
    start = start.strip('"')
    if os.path.isabs(start):
        return start
    try:
        exe = shlex.split(field(entry, "Exe") or "")[0]
    except (ValueError, IndexError):
        return start
    return os.path.dirname(exe) if os.path.isabs(exe) else start


def load_shortcuts(config):
    """Non-Steam games added to the Steam library, excluding hidden ones."""
    games = []
    for appid, entry in read_shortcuts(config).items():
        name = field(entry, "AppName") or ""
        if not name or field(entry, "IsHidden"):
            continue
        games.append(
            Game(
                appid=appid,
                name=name,
                installed=True,
                non_steam=True,
                install_dir=_shortcut_folder(entry),
                last_played=field(entry, "LastPlayTime") or 0,
                **find_art(config.root, config.userdata, appid),
            )
        )
    return games


ART_LABELS = {
    "cover": "Cover",
    "hero": "Background",
    "logo": "Logo",
    "header": "Wide Cover",
}


def _grid_files(config, appid, kind):
    grid = config.userdata / "config" / "grid"
    return [grid / f"{appid}{GRID_SUFFIXES[kind]}.{ext}" for ext in ("png", "jpg")]


def custom_art(config, appid, kind):
    return next((p for p in _grid_files(config, appid, kind) if p.is_file()), None)


def set_custom_art(config, appid, kind, source):
    """Use an image as the game's custom artwork, as Steam's "Set Custom Artwork" does.

    Steam reads PNG and JPEG files from userdata/<account>/config/grid, named by
    app ID and kind; any earlier custom image for the same kind is replaced.
    """
    source = Path(source)
    ext = "png" if source.suffix.lower() == ".png" else "jpg"
    clear_custom_art(config, appid, kind)
    target = config.userdata / "config" / "grid" / f"{appid}{GRID_SUFFIXES[kind]}.{ext}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def clear_custom_art(config, appid, kind):
    for path in _grid_files(config, appid, kind):
        path.unlink(missing_ok=True)


STEAMGRIDDB_SEARCH = "https://www.steamgriddb.com/search/grids?term={term}"


def artwork_search_term(name):
    """A search term from a shortcut name: "RSF_Launcher.exe" becomes "RSF Launcher"."""
    term = re.sub(r"\.(exe|sh|bat|lnk|appimage)$", "", name.strip(), flags=re.IGNORECASE)
    return re.sub(r"[_]+", " ", term).strip() or name


def steamgriddb_url(name):
    return STEAMGRIDDB_SEARCH.format(term=quote(artwork_search_term(name)))


def prefix_path(config, game):
    """The game's Proton prefix (Wine "C: drive" folder), or None if it has none.

    Steam keeps a prefix in the compatdata folder of the library the game is
    installed in; non-Steam games use the main Steam folder's library.
    """
    appid = str(game.props.appid)
    first = Path(game.props.library) if game.props.library else config.root
    candidates = [first] + [Path(f) for f in config.library_folders() if Path(f) != first]
    for folder in candidates:
        pfx = folder / "steamapps" / "compatdata" / appid / "pfx"
        if pfx.is_dir():
            return pfx
    return None


def game_matches(game, query):
    """Whether a game should be shown for the search text in the library.

    A game matches when the query appears anywhere in its name, when every query
    word starts a word of the name (so "wars squad" finds "STAR WARS™:
    Squadrons"), when the query is its initials (so "re3" finds "Resident Evil
    3"), or when the query is its App ID. Case, ™ and ® signs, and punctuation
    are ignored.
    """
    words = _words(query)
    if not words:
        return True  # Only punctuation was typed.
    name_words = _words(game.props.name)
    if " ".join(words) in " ".join(name_words):
        return True
    if all(any(n.startswith(w) for n in name_words) for w in words):
        return True
    compact = "".join(words)
    if len(compact) >= 2:
        initials = "".join(w if w.isdigit() else w[0] for w in name_words)
        if initials.startswith(compact):
            return True
    return compact.isdigit() and compact == str(game.props.appid)


_MARKS = re.compile(r"[™®©]")
_SEPARATORS = re.compile(r"[\W_]+")


def _words(text):
    """Lower-case words of text, with trademark signs and punctuation removed."""
    return _SEPARATORS.sub(" ", _MARKS.sub("", text.casefold())).split()


def sort_key(game, mode):
    """Key for ascending sorts; size, last played and release date put the largest first."""
    name = game.props.name.casefold()
    if mode == "size":
        return (-game.props.size, name)
    if mode == "last_played":
        return (-game.props.last_played, name)
    if mode == "release_date":
        return (-game.props.release_date, name)
    return (name,)


def apply_metadata(games, metadata):
    for game in games:
        info = metadata.get(game.props.appid)
        if info:
            game.props.release_date = info.get("release", 0)
            game.props.genres = info.get("genres", [])
            game.props.vr = info.get("vr", 0)


def group_keys(game, mode):
    """The groups a game belongs to, as (order, heading) pairs.

    A game can appear under several genres. Groups without data, such as games
    with no known release date, are gathered at the end.
    """
    if mode == "genre":
        genres = list(game.props.genres or [])
        return [(0, g) for g in genres] or [(1, "Other")]
    if mode == "year":
        if game.props.release_date:
            year = time.localtime(game.props.release_date).tm_year
            return [(-year, str(year))]
        return [(1, "Unknown Release Date")]
    if mode == "installed":
        return [(0, "Installed")] if game.props.installed else [(1, "Not Installed")]
    return [(0, "")]
