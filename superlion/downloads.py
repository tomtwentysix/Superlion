"""Steam's downloads and updates, read from its app manifests and content log.

Steam writes each app's state flags and byte counts to its appmanifest, but
rarely rewrites them mid-download, so a running download can still read as
started-but-paused there. Its content log records every state change as it
happens, so while Steam runs the log's latest state wins. Superlion only reads
these; downloads are controlled in Steam itself.
"""

import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import steam_control, vdf

# Steam's app state flags (EAppState).
UPDATE_REQUIRED = 2
FULLY_INSTALLED = 4
UPDATE_RUNNING = 256
UPDATE_PAUSED = 512
UPDATE_STARTED = 1024
DOWNLOADING = 1 << 20
STAGING = 1 << 21
COMMITTING = 1 << 22

RATE_LINE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] Current download rate: ([\d.]+) Mbps")
RATE_FRESH = 30  # seconds a logged rate is treated as current
# e.g. "[2026-10-19 23:49:38] AppID 1088850 state changed : Update Required,Update Running,"
STATE_LINE = re.compile(r"^\[[^]]+\] AppID (\d+) state changed : (.*)$")
CLIENT_LINE = "] Client version: "  # logged once each time Steam starts

_log_lock = threading.Lock()
_log = {"path": None, "offset": 0, "states": {}}


@dataclass
class Download:
    appid: int
    name: str
    status: str  # "downloading", "paused" or "waiting"
    detail: str  # e.g. "Downloading", "Staging", "Verifying"
    downloaded: int
    total: int
    staged: int
    stage_total: int
    scheduled: int  # Unix time of a scheduled automatic update, or 0

    @property
    def fraction(self):
        if self.total and (self.downloaded or not self.staged):
            return min(1.0, self.downloaded / self.total)
        if self.stage_total:
            return min(1.0, self.staged / self.stage_total)
        return 0.0


def _status(flags):
    if flags & (UPDATE_RUNNING | DOWNLOADING | STAGING | COMMITTING):
        if flags & COMMITTING:
            return "downloading", "Installing"
        if flags & STAGING and not flags & DOWNLOADING:
            return "downloading", "Staging"
        return "downloading", "Downloading"
    if flags & UPDATE_PAUSED or (flags & UPDATE_STARTED and flags & UPDATE_REQUIRED):
        return "paused", "Paused"
    if flags & UPDATE_REQUIRED:
        return "waiting", "Update waiting"
    return None, None


def _staged_on_disk(folder):
    """Bytes allocated under a steamapps/downloading/<appid> folder.

    Steam leaves the manifest's byte counts at 0 until a download stops, but
    stages its files here as it goes. Allocated rather than apparent sizes,
    since Steam writes chunks out of order into sparse files.
    """
    total = 0
    for root, _dirs, files in os.walk(folder):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_blocks * 512
            except OSError:
                pass
    return total


def _logged_states(config):
    """{appid: set of state names} from the content log since Steam last started.

    The log is read incrementally; it is rotated to content_log.previous.txt when large.
    """
    log = Path(config.steam_root) / "logs" / "content_log.txt"
    with _log_lock:
        try:
            size = log.stat().st_size
        except OSError:
            return {}
        if _log["path"] != log or size < _log["offset"]:
            _log.update(path=log, offset=0, states={})
        try:
            with open(log, "rb") as fh:
                fh.seek(_log["offset"])
                chunk = fh.read()
        except OSError:
            return dict(_log["states"])
        end = chunk.rfind(b"\n") + 1  # leave a half-written last line for next time
        _log["offset"] += end
        for line in chunk[:end].decode("utf-8", "replace").splitlines():
            if CLIENT_LINE in line:
                _log["states"].clear()
            elif match := STATE_LINE.match(line):
                names = {n.strip() for n in match.group(2).split(",")} - {""}
                _log["states"][int(match.group(1))] = names
        return dict(_log["states"])


def _logged_status(names):
    """The (status, detail) for an app's latest logged state names, as _status() returns."""
    if "Update Running" in names:
        return "downloading", "Downloading"
    if "Update Paused" in names or "(Suspended)" in names:
        return "paused", "Paused"
    if names & {"Update Required", "Update Queued"}:
        return "waiting", "Update waiting"
    return None, None


def scan(config, appids=None):
    """Apps with an active, paused or waiting download, across every enabled library.

    appids limits the scan to those apps, which is quicker for a single game.
    """
    found = {}
    logged = _logged_states(config) if steam_control.is_running(config) else {}
    for folder in config.library_folders():
        steamapps = Path(folder) / "steamapps"
        manifests = (
            [steamapps / f"appmanifest_{a}.acf" for a in appids] if appids is not None
            else sorted(steamapps.glob("appmanifest_*.acf"))
        )
        for manifest in manifests:
            if not manifest.is_file():
                continue
            try:
                state = vdf.get_path(vdf.load(manifest), "AppState") or {}
            except (OSError, ValueError):
                continue
            try:
                flags = int(state.get("StateFlags", "0") or 0)
                appid = int(state.get("appid", "0") or 0)
            except ValueError:
                continue
            status, detail = _logged_status(logged[appid]) if appid in logged else _status(flags)
            if not status or not appid or appid in found:
                continue
            number = lambda key: int(state.get(key, "0") or 0)  # noqa: E731
            if status == "paused" and not flags & UPDATE_REQUIRED and not number("BytesToDownload"):
                continue  # A leftover paused flag with nothing to fetch; Steam does not list these.
            staged = number("BytesStaged")
            if status == "downloading" and not number("BytesDownloaded") and not staged:
                staged = _staged_on_disk(steamapps / "downloading" / str(appid))
            found[appid] = Download(
                appid=appid,
                name=state.get("name", str(appid)),
                status=status,
                detail=detail,
                downloaded=number("BytesDownloaded"),
                total=number("BytesToDownload"),
                staged=staged,
                stage_total=number("BytesToStage"),
                scheduled=number("ScheduledAutoUpdate"),
            )
    order = {"downloading": 0, "paused": 1, "waiting": 2}
    return sorted(found.values(), key=lambda d: (order[d.status], d.scheduled or 0, d.name.casefold()))


def current_rate(config):
    """Steam's latest logged download rate in megabits per second, or None if not recent."""
    log = Path(config.steam_root) / "logs" / "content_log.txt"
    try:
        with open(log, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 65536))  # The latest entries are at the end.
            tail = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for line in reversed(tail):
        match = RATE_LINE.match(line)
        if match:
            logged = time.mktime(time.strptime(match.group(1), "%Y-%m-%d %H:%M:%S"))
            return float(match.group(2)) if time.time() - logged <= RATE_FRESH else None
    return None


def state_for(config, appid):
    """The download state of one game, or None when nothing is downloading or waiting."""
    items = scan(config, [appid])
    return items[0] if items else None


def is_busy(item, installed=True):
    """Whether Steam's download stops the game starting; a waiting update is fetched when it is played."""
    return item is not None and not (item.status == "waiting" and installed)


def cover_label(item, installed=True):
    """What a game's cover says about a download, such as "Updating 42%" or "Update Available"."""
    if item.status == "waiting" and installed:
        return "Update Available"
    return play_label(item, installed)


def play_label(item, installed=True):
    """What a Play button should say while a game downloads, e.g. "Updating 42%"."""
    if item.status == "downloading":
        verb = "Updating" if installed else "Installing"
        return f"{verb} {round(item.fraction * 100)}%" if item.total or item.stage_total else f"{verb}…"
    if item.status == "paused":
        return "Update Paused" if installed else "Install Paused"
    return "Update and Play" if installed else "Install Queued"
