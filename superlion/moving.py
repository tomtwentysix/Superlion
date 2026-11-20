"""Moving and deleting games' files."""

import errno
import os
import re
import shlex
import shutil
from pathlib import Path

from . import library as library_mod
from . import vdf

CHUNK = 1024 * 1024
# Folders that hold games rather than being one, so a suggestion stops below them.
CONTAINERS = {
    "games", "heroic", "gog games", "lutris", "bottles", "wine", "program files",
    "program files (x86)", "drive_c", "steamlibrary", "steamapps", "common",
}


class MoveError(Exception):
    pass


class Progress:
    # Written by the worker thread, polled by the UI.
    def __init__(self):
        self.done = 0
        self.total = 0
        self.label = ""
        self.cancelled = False


def steam_parts(library, appid, installdir):
    if not installdir or installdir in (".", "..") or Path(installdir).name != installdir:
        raise MoveError(f"Invalid install folder name: {installdir!r}")
    steamapps = Path(library) / "steamapps"
    candidates = [
        steamapps / "common" / installdir,
        steamapps / "compatdata" / str(appid),
        steamapps / "shadercache" / str(appid),
        steamapps / "workshop" / "content" / str(appid),
        steamapps / "workshop" / f"appworkshop_{appid}.acf",
        steamapps / f"appmanifest_{appid}.acf",
    ]
    return [p for p in candidates if os.path.lexists(p)]


def folder_sharers(library, appid, installdir):
    # Steam lets several apps share one folder in common/, such as Half-Life 2 and its episodes.
    if not installdir:
        return []
    return sorted(
        game["name"] for game in library_contents(library)
        if game["appid"] != appid and game["installdir"] == installdir
    )


def _walk_size(path):
    if path.is_symlink():
        return 0
    if not path.is_dir():
        return path.lstat().st_size
    total = 0
    with os.scandir(path) as entries:
        for entry in entries:
            total += _walk_size(Path(entry.path))
    return total


def parts_size(paths):
    return sum(_walk_size(Path(p)) for p in paths)


def same_drive(a, b):
    def device(path):
        path = Path(path)
        while not os.path.lexists(path):
            path = path.parent
        return os.stat(path).st_dev

    return device(a) == device(b)


def _copy_file(src, dst, progress):
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        while chunk := fin.read(CHUNK):
            if progress.cancelled:
                raise MoveError("Cancelled")
            fout.write(chunk)
            progress.done += len(chunk)
    shutil.copystat(src, dst)


def _copy_tree(src, dst, progress):
    src, dst = Path(src), Path(dst)
    if src.is_symlink():
        os.symlink(os.readlink(src), dst)
    elif src.is_dir():
        dst.mkdir()
        with os.scandir(src) as entries:
            for entry in entries:
                _copy_tree(entry.path, dst / entry.name, progress)
        shutil.copystat(src, dst)
    elif src.is_file():
        _copy_file(src, dst, progress)
    else:
        raise MoveError(f"Cannot copy {src}: unsupported file type")


def _make_writable(func, path, _err):
    # copystat can leave read-only directories behind, which rmtree cannot empty.
    parent = Path(path).parent
    os.chmod(parent, os.stat(parent).st_mode | 0o700)
    func(path)


def _remove(path):
    path = Path(path)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, onexc=_make_writable)
    else:
        path.unlink()


def _remove_quietly(path):
    try:
        _remove(path)
    except OSError:
        pass


def _make_parents(path, created):
    missing = []
    for parent in path.parents:
        if parent.exists():
            break
        missing.append(parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    created.extend(missing)


def _prune(created):
    for folder in created:
        try:
            folder.rmdir()
        except OSError:
            pass


def _destinations(source, target, parts):
    source_steamapps = Path(source) / "steamapps"
    return [Path(target) / "steamapps" / p.relative_to(source_steamapps) for p in parts]


def _check_free(destinations):
    for dst in destinations:
        if os.path.lexists(dst):
            raise MoveError(f"{dst} already exists")


def _rename_all(parts, destinations):
    # Returns False if the paths are on different mounts (EXDEV) after undoing any renames.
    done, created = [], []
    try:
        for src, dst in zip(parts, destinations):
            _make_parents(dst, created)
            os.rename(src, dst)
            done.append((src, dst))
    except OSError as err:
        for done_src, done_dst in reversed(done):
            try:
                os.rename(done_dst, done_src)
            except OSError:
                pass
        _prune(created)
        if err.errno == errno.EXDEV:
            return False
        raise MoveError(f"Could not move {src.name}: {err.strerror or err}") from err
    return True


def _copy_all(parts, destinations, progress):
    progress.total = parts_size(parts)
    progress.done = 0
    started, created = [], []
    try:
        for src, dst in zip(parts, destinations):
            _make_parents(dst, created)
            started.append(dst)
            _copy_tree(src, dst, progress)
    except (OSError, MoveError) as err:
        for dst in reversed(started):
            _remove_quietly(dst)
        _prune(created)
        if isinstance(err, MoveError):
            raise
        raise MoveError(f"Could not copy {src.name}: {err.strerror or err}") from err
    # The originals are removed next, so the copy must be on the disk first.
    os.sync()
    progress.done = progress.total


def _installed_parts(library, appid, installdir):
    if not os.path.lexists(Path(library) / "steamapps" / f"appmanifest_{appid}.acf"):
        raise MoveError(f"It is no longer installed in {library}")
    return steam_parts(library, appid, installdir)


def move_steam_game(source, target, appid, installdir, progress):
    parts = _installed_parts(source, appid, installdir)
    others = folder_sharers(source, appid, installdir)
    if others:
        raise MoveError(f"Its folder is shared with {', '.join(others)}, so it cannot be moved on its own")
    destinations = _destinations(source, target, parts)
    _check_free(destinations)
    if same_drive(Path(source) / "steamapps", Path(target) / "steamapps"):
        if _rename_all(parts, destinations):
            return
    _copy_all(parts, destinations, progress)
    # The copy is complete; remove the manifest first so Steam never lists the game twice.
    try:
        for part in reversed(parts):
            _remove(part)
    except OSError as err:
        raise MoveError(f"Copied, but could not remove the original {part.name}: {err.strerror or err}") from err


def delete_steam_game(library, appid, installdir, progress):
    parts = _installed_parts(library, appid, installdir)
    if folder_sharers(library, appid, installdir):
        shared = Path(library) / "steamapps" / "common" / installdir
        parts = [p for p in parts if p != shared]
    progress.total = len(parts)
    progress.done = 0
    for part in reversed(parts):
        try:
            _remove(part)
        except OSError as err:
            raise MoveError(f"Could not delete {part.name}: {err.strerror or err}") from err
        progress.done += 1


def library_contents(folder):
    games = []
    for manifest in sorted((Path(folder) / "steamapps").glob("appmanifest_*.acf")):
        try:
            state = vdf.get_path(vdf.load(manifest), "AppState") or {}
        except OSError:
            continue
        appid = int(state.get("appid", "0") or 0)
        name = state.get("name", "")
        if not appid or not name:
            continue
        games.append({
            "appid": appid,
            "name": name,
            "installdir": state.get("installdir", ""),
            "size": int(state.get("SizeOnDisk", "0") or 0),
            "tool": library_mod.is_tool(name),
        })
    return games


def shortcut_exe(entry):
    try:
        words = shlex.split(library_mod.field(entry, "Exe") or "")
    except ValueError:
        return None
    if words and os.path.isabs(words[0]) and os.path.exists(words[0]):
        return Path(words[0])
    return None


def sharing(entries, appid, folder):
    folder = Path(folder)
    ids = []
    for other, entry in entries.items():
        exe = shortcut_exe(entry)
        if other != appid and exe and exe.is_relative_to(folder):
            ids.append(other)
    return sorted(ids)


def suggest_folder(entries, appid, blocked, home=None, is_mount=os.path.ismount, keep=()):
    # keep: folders never to suggest, such as Downloads.
    exe = shortcut_exe(entries[appid])
    if exe is None:
        return None
    home = Path.home() if home is None else Path(home)
    group = {appid, *sharing(entries, appid, exe.parent)}
    outside = [e for a, entry in entries.items() if a not in group and (e := shortcut_exe(entry))]

    def allowed(folder):
        return (
            folder != home
            and folder not in keep
            and folder != folder.parent
            and not is_mount(folder)
            and not any(folder.is_relative_to(b) or b.is_relative_to(folder) for b in blocked)
            and not any(e.is_relative_to(folder) for e in outside)
        )

    folder = exe.parent
    if not allowed(folder):
        return None
    def container(candidate):
        return (
            candidate == home
            or is_mount(candidate)
            or candidate in keep
            or candidate.name.startswith(".")
            or candidate.name.lower() in CONTAINERS
        )

    while allowed(folder.parent) and not container(folder.parent):
        folder = folder.parent
    return folder, sorted(group - {appid})


def _replace_prefix(text, old, new):
    # Only whole path components, so /g/X leaves /g/X2 and /h/g/X alone.
    pattern = r"(?<![^\s\"'=:,])" + re.escape(str(old)) + r"(?=$|[/\s\"'\\:,;])"
    return re.sub(pattern, lambda _m: str(new), text)


def rewrite_entry(entry, old, new):
    result = {}
    for key, value in entry.items():
        if key.lower() in ("exe", "startdir", "icon", "launchoptions") and isinstance(value, str):
            value = _replace_prefix(value, old, new)
        result[key] = value
    return result


def move_folder(old, new_parent, progress):
    old, new_parent = Path(old), Path(new_parent)
    if new_parent.resolve().is_relative_to(old.resolve()):
        raise MoveError(f"Cannot move {old.name} into itself")
    dest = new_parent / old.name
    _check_free([dest])
    if same_drive(old, dest) and _rename_all([old], [dest]):
        return dest
    _copy_all([old], [dest], progress)
    try:
        _remove(old)
    except OSError as err:
        raise MoveError(f"Copied, but could not remove the original {old.name}: {err.strerror or err}") from err
    return dest
