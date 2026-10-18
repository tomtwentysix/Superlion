"""Persistent application configuration chosen in the setup wizard."""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from gi.repository import GLib

from . import steam_paths

APP_NAME = "superlion"


def config_dir():
    return Path(GLib.get_user_config_dir()) / APP_NAME


def data_dir():
    return Path(GLib.get_user_data_dir()) / APP_NAME


def cache_dir():
    return Path(GLib.get_user_cache_dir()) / APP_NAME


CONFIG_PATH = config_dir() / "config.json"


@dataclass
class Config:
    steam_root: str = ""
    steam_command: str = steam_paths.NATIVE_COMMAND
    account_id: int = 0
    # Store prices: automatic uses the signed-in account's country, otherwise the UK.
    region_auto: bool = True
    region: str = "GB"  # Used only when region_auto is False.
    # Library folders from libraryfolders.vdf that the user turned off.
    disabled_libraries: list = field(default_factory=list)
    # Library folders added by hand in the wizard.
    extra_libraries: list = field(default_factory=list)
    sign_in_skipped: bool = False

    @property
    def root(self):
        return Path(self.steam_root)

    @property
    def userdata(self):
        return steam_paths.userdata_dir(self.steam_root, self.account_id)

    @property
    def localconfig_path(self):
        return self.userdata / "config" / "localconfig.vdf"

    @property
    def steam_kind(self):
        return steam_paths.kind_for_root(self.steam_root)

    def library_folders(self):
        """Enabled library folders, in libraryfolders.vdf order, then extras."""
        folders = [
            path
            for path, _count in steam_paths.find_libraries(self.steam_root)
            if str(path) not in self.disabled_libraries
        ]
        known = {str(p) for p in folders}
        folders += [Path(p) for p in self.extra_libraries if p not in known]
        return folders

    def problems(self):
        """Human-readable reasons the saved configuration no longer works."""
        issues = []
        if not steam_paths.is_steam_root(self.steam_root):
            issues.append(f"The Steam folder {self.steam_root} could not be found.")
        elif not self.userdata.is_dir():
            issues.append("The selected Steam account has no data folder.")
        for folder in self.library_folders():
            if not steam_paths.is_library_folder(folder):
                issues.append(f"The library folder {folder} is not available.")
        return issues


def load():
    """Return the saved configuration, or None when setup has not been run."""
    try:
        data = json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return None
    known = Config.__dataclass_fields__
    return Config(**{k: v for k, v in data.items() if k in known})


def save(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(config), indent=2))
    os.replace(tmp, CONFIG_PATH)


def detect():
    """Best-guess configuration from what is installed, used to prefill the wizard."""
    config = Config()
    installs = steam_paths.find_installs()
    if installs:
        config.steam_root = str(installs[0].root)
        config.steam_command = installs[0].command
        accounts = steam_paths.find_accounts(installs[0].root)
        if accounts:
            config.account_id = accounts[0].account_id
    return config
