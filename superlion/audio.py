"""Taking EasyEffects out of the way while Sunshine streams, and bringing it back."""

import shutil
import subprocess
from pathlib import Path

from gi.repository import GLib

FLATPAK_ID = "com.github.wwmm.easyeffects"
# Present while a stream has EasyEffects stopped, so it is only started again if it was running.
STOPPED_PATH = Path(GLib.get_user_runtime_dir()) / "superlion" / "easyeffects-stopped"


def detached(command):
    """Start command in its own systemd scope.

    Sunshine runs its commands inside its own service, and systemd stops
    everything in a service when it stops or restarts, so anything that
    should outlive Sunshine is moved out.
    """
    subprocess.Popen(
        ["systemd-run", "--user", "--scope", "--collect", "--quiet", "--", *command],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _easyeffects():
    if shutil.which("easyeffects"):
        return ["easyeffects"]
    if shutil.which("flatpak") and subprocess.run(
        ["flatpak", "info", FLATPAK_ID], capture_output=True, timeout=5,
    ).returncode == 0:
        return ["flatpak", "run", "--command=easyeffects", FLATPAK_ID]
    return None


def _running():
    return subprocess.run(["pgrep", "-x", "easyeffects"], capture_output=True).returncode == 0


def bypass():
    """Quit EasyEffects, which mixes every app down to its own stereo sink."""
    command = _easyeffects()
    if command is None or not _running():
        return
    subprocess.run([*command, "--quit"], capture_output=True, timeout=15)
    STOPPED_PATH.parent.mkdir(parents=True, exist_ok=True)
    STOPPED_PATH.touch()


def restore():
    """Start EasyEffects again, hidden, if bypass() stopped it."""
    if not STOPPED_PATH.exists():
        return
    STOPPED_PATH.unlink()
    command = _easyeffects()
    if command and not _running():
        detached([*command, "--hide-window"])
