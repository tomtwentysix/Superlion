import os
import sys
from pathlib import Path

# Run by Sunshine before and after a stream, which sets SUNSHINE_CLIENT_* for the client's request.
if sys.argv[1:] == ["--sunshine-prepare"]:
    from . import audio, display

    audio.bypass()
    env = os.environ
    display.prepare(
        int(env.get("SUNSHINE_CLIENT_WIDTH", 0)),
        int(env.get("SUNSHINE_CLIENT_HEIGHT", 0)),
        int(env.get("SUNSHINE_CLIENT_FPS", 0)),
        env.get("SUNSHINE_CLIENT_HDR") == "true",
    )
    sys.exit(0)
if sys.argv[1:] == ["--sunshine-restore"]:
    from . import audio, display

    display.restore()
    audio.restore()
    sys.exit(0)
if sys.argv[1:2] == ["--sunshine-close"] and len(sys.argv) == 3:
    from . import sunshine

    sunshine.close_game(int(sys.argv[2]))
    sys.exit(0)

from .app import main  # noqa: E402

# /usr/bin/superlion adds Superlion's folder to PYTHONPATH, and GNOME names the
# desktop file it was opened from. Python has already read them, and Steam, its
# games (Proton is a Python script) and mod managers started from here must not
# inherit them.
own = os.path.realpath(Path(__file__).parent.parent)
paths = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p and os.path.realpath(p) != own]
if paths:
    os.environ["PYTHONPATH"] = os.pathsep.join(paths)
else:
    os.environ.pop("PYTHONPATH", None)
for name in ("GIO_LAUNCHED_DESKTOP_FILE", "GIO_LAUNCHED_DESKTOP_FILE_PID"):
    os.environ.pop(name, None)

sys.exit(main())
