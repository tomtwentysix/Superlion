"""Detection of Steam installations, accounts and library folders.

Everything here only proposes candidates; the setup wizard and config module
decide which ones are used.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import vdf

STEAMID64_BASE = 76561197960265728
FLATPAK_ID = "com.valvesoftware.Steam"

NATIVE_COMMAND = "steam"
FLATPAK_COMMAND = f"flatpak run {FLATPAK_ID}"


@dataclass
class SteamInstall:
    root: Path
    kind: str  # "native" or "flatpak"

    @property
    def command(self):
        return FLATPAK_COMMAND if self.kind == "flatpak" else NATIVE_COMMAND


@dataclass
class SteamAccount:
    steamid64: int
    account_name: str
    persona_name: str
    timestamp: int

    @property
    def account_id(self):
        return self.steamid64 - STEAMID64_BASE

    @property
    def label(self):
        if self.persona_name and self.account_name:
            return f"{self.persona_name} ({self.account_name})"
        return self.persona_name or self.account_name or str(self.steamid64)


def is_steam_root(path):
    path = Path(path)
    return (path / "steamapps" / "libraryfolders.vdf").is_file() and (
        path / "config" / "config.vdf"
    ).is_file()


def find_installs():
    """Return detected Steam installations, native first, without duplicates."""
    home = Path.home()
    candidates = [
        (home / ".local/share/Steam", "native"),
        (home / ".steam/steam", "native"),
        (home / ".steam/root", "native"),
        (home / f".var/app/{FLATPAK_ID}/.local/share/Steam", "flatpak"),
        (home / f".var/app/{FLATPAK_ID}/data/Steam", "flatpak"),
    ]
    seen, found = set(), []
    for path, kind in candidates:
        if not is_steam_root(path):
            continue
        real = path.resolve()
        if real in seen:
            continue
        seen.add(real)
        found.append(SteamInstall(real, kind))
    return found


def kind_for_root(root):
    return "flatpak" if f"/.var/app/{FLATPAK_ID}/" in str(root) else "native"


def command_candidates():
    found = []
    if shutil.which("steam"):
        found.append(NATIVE_COMMAND)
    if shutil.which("flatpak") and (
        Path(f"/var/lib/flatpak/app/{FLATPAK_ID}").exists()
        or (Path.home() / f".local/share/flatpak/app/{FLATPAK_ID}").exists()
    ):
        found.append(FLATPAK_COMMAND)
    return found


def is_valid_command(command):
    first = command.split()[0] if command.split() else ""
    if not first:
        return False
    if os.sep in first:
        return os.access(first, os.X_OK)
    return shutil.which(first) is not None


def find_accounts(root):
    """Accounts from loginusers.vdf that have a userdata folder, newest first."""
    path = Path(root) / "config" / "loginusers.vdf"
    if not path.is_file():
        return []
    users = vdf.get_path(vdf.load(path), "users") or {}
    accounts = []
    for sid, info in users.items():
        if not sid.isdigit() or not isinstance(info, dict):
            continue
        account = SteamAccount(
            steamid64=int(sid),
            account_name=info.get("AccountName", ""),
            persona_name=info.get("PersonaName", ""),
            timestamp=int(info.get("timestamp", "0") or 0),
        )
        if userdata_dir(root, account.account_id).is_dir():
            accounts.append(account)
    accounts.sort(
        key=lambda a: (users[str(a.steamid64)].get("MostRecent") == "1", a.timestamp),
        reverse=True,
    )
    return accounts


def parse_account_id(text):
    """Accept either a SteamID64 or a 32-bit account ID; return the account ID."""
    text = text.strip()
    if not text.isdigit():
        return None
    value = int(text)
    return value - STEAMID64_BASE if value >= STEAMID64_BASE else value


def userdata_dir(root, account_id):
    return Path(root) / "userdata" / str(account_id)


def find_libraries(root):
    """Library folder paths listed in libraryfolders.vdf, with their app counts."""
    path = Path(root) / "steamapps" / "libraryfolders.vdf"
    if not path.is_file():
        return []
    data = vdf.get_path(vdf.load(path), "libraryfolders") or {}
    libraries = []
    for entry in data.values():
        if isinstance(entry, dict) and "path" in entry:
            folder = Path(entry["path"])
            libraries.append((folder, count_manifests(folder)))
    return libraries


def count_manifests(folder):
    try:
        return sum(1 for _ in (Path(folder) / "steamapps").glob("appmanifest_*.acf"))
    except OSError:
        return 0


def is_library_folder(path):
    return (Path(path) / "steamapps").is_dir()
