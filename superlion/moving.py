"""Moving and deleting games' files."""

import os
import shutil
from pathlib import Path

from . import library as library_mod
from . import vdf

CHUNK = 1024 * 1024


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
        return os.lstat(path).st_dev

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


def _remove(path):
    path = Path(path)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
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
    done, created = [], []
    try:
        for src, dst in zip(parts, destinations):
            _make_parents(dst, created)
            os.rename(src, dst)
            done.append((src, dst))
    except OSError as err:
        for src, dst in reversed(done):
            try:
                os.rename(dst, src)
            except OSError:
                pass
        _prune(created)
        raise MoveError(f"Could not move {src.name}: {err.strerror or err}") from err


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
    progress.done = progress.total


def move_steam_game(source, target, appid, installdir, progress):
    parts = steam_parts(source, appid, installdir)
    destinations = _destinations(source, target, parts)
    _check_free(destinations)
    if same_drive(Path(source) / "steamapps", Path(target) / "steamapps"):
        _rename_all(parts, destinations)
        return
    _copy_all(parts, destinations, progress)
    # The copy is complete; remove the manifest first so Steam never lists the game twice.
    try:
        for part in reversed(parts):
            _remove(part)
    except OSError as err:
        raise MoveError(f"Copied, but could not remove the original {part.name}: {err.strerror or err}") from err


def delete_steam_game(library, appid, installdir, progress):
    parts = steam_parts(library, appid, installdir)
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
