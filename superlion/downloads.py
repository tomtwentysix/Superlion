"""Steam's downloads and updates, read from its app manifests and content log.

Steam writes each app's state flags and byte counts to its appmanifest while it
downloads, and logs the current download rate. Superlion only reads these;
downloads are controlled in Steam itself.
"""

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from . import vdf

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
        if self.total:
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


def scan(config, appids=None):
    """Apps with an active, paused or waiting download, across every enabled library.

    appids limits the scan to those apps, which is quicker for a single game.
    """
    found = {}
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
            status, detail = _status(flags)
            if not status or not appid or appid in found:
                continue
            number = lambda key: int(state.get(key, "0") or 0)  # noqa: E731
            if status == "paused" and not flags & UPDATE_REQUIRED and not number("BytesToDownload"):
                continue  # A leftover paused flag with nothing to fetch; Steam does not list these.
            found[appid] = Download(
                appid=appid,
                name=state.get("name", str(appid)),
                status=status,
                detail=detail,
                downloaded=number("BytesDownloaded"),
                total=number("BytesToDownload"),
                staged=number("BytesStaged"),
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


def play_label(item, installed=True):
    """What a Play button should say while a game downloads, e.g. "Updating 42%"."""
    if item.status == "downloading":
        verb = "Updating" if installed else "Installing"
        return f"{verb} {round(item.fraction * 100)}%" if item.total or item.stage_total else f"{verb}…"
    if item.status == "paused":
        return "Update Paused" if installed else "Install Paused"
    return "Update Queued"
