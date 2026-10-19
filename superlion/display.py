"""Switching the streamed monitor's mode and HDR for Sunshine, and putting it back."""

import json
import os
from pathlib import Path

from gi.repository import Gio, GLib

BUS_NAME = "org.gnome.Mutter.DisplayConfig"
OBJECT_PATH = "/org/gnome/Mutter/DisplayConfig"
TEMPORARY = 1  # ApplyMonitorsConfig method: not saved to monitors.xml, no confirmation prompt.
# Mutter's color-mode values.
SDR = 0
HDR = 1

SAVED_PATH = Path(GLib.get_user_runtime_dir()) / "superlion" / "display.json"


def _call(method, args=None):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    return bus.call_sync(
        BUS_NAME, OBJECT_PATH, BUS_NAME, method, args, None, Gio.DBusCallFlags.NONE, -1, None,
    ).unpack()


def _state():
    """The current layout as (serial, monitors, layout).

    monitors maps a connector to {"modes": [mode, ...], "color_modes": [...]},
    each mode being {"id", "width", "height", "refresh", "vrr", "current"}.
    layout is the list of logical monitors in ApplyMonitorsConfig's own shape:
    [x, y, scale, transform, primary, [[connector, mode_id, {"color-mode": n}], ...]].
    """
    serial, raw_monitors, raw_logical, _props = _call("GetCurrentState")
    monitors = {}
    current = {}
    for (connector, *_), modes, props in raw_monitors:
        entries = [
            {
                "id": mode_id, "width": width, "height": height, "refresh": refresh,
                "vrr": mode_props.get("refresh-rate-mode") == "variable",
                "current": mode_props.get("is-current", False),
            }
            for mode_id, width, height, refresh, _scale, _scales, mode_props in modes
        ]
        monitors[connector] = {
            "modes": entries,
            "scales": {mode_id: scales for mode_id, *_, scales, _p in modes},
            "color_modes": props.get("supported-color-modes", [SDR]),
        }
        live = next((m["id"] for m in entries if m["current"]), None)
        if live:
            current[connector] = (live, props.get("color-mode", SDR))
    layout = [
        [x, y, scale, transform, primary,
         [[c, current[c][0], {"color-mode": current[c][1]}] for (c, *_) in specs if c in current]]
        for x, y, scale, transform, primary, specs, _props in raw_logical
    ]
    return serial, monitors, layout


def _apply(serial, layout):
    logical = [
        (x, y, scale, transform, primary,
         [(c, mode_id, {"color-mode": GLib.Variant("u", props["color-mode"])}) for c, mode_id, props in specs])
        for x, y, scale, transform, primary, specs in layout
    ]
    _call("ApplyMonitorsConfig", GLib.Variant(
        "(uua(iiduba(ssa{sv}))a{sv})", (serial, TEMPORARY, logical, {}),
    ))


def choose_mode(modes, width, height, fps):
    """The id of the mode to stream width x height at fps, or None to keep the current one.

    Without the exact size, the smallest mode that covers it is used, so the
    picture is scaled down rather than up; failing that, the largest mode.
    """
    if not (width and height and fps):
        return None
    fixed = [m for m in modes if not m["vrr"]]
    if not fixed:
        return None
    # Modes in another shape than the largest, such as 1920x2160, would stretch the picture.
    native = max(fixed, key=lambda m: m["width"] * m["height"])
    shape = native["width"] / native["height"]
    sizes = {(m["width"], m["height"]) for m in fixed if abs(m["width"] / m["height"] - shape) < 0.01}
    covering = [s for s in sizes if s[0] >= width and s[1] >= height]
    if (width, height) in sizes:
        size = (width, height)
    elif covering:
        size = min(covering, key=lambda s: s[0] * s[1])
    else:
        size = max(sizes, key=lambda s: s[0] * s[1])
    # 59.94 Hz counts as 60, so the closest refresh rate wins.
    return min(
        (m for m in fixed if (m["width"], m["height"]) == size),
        key=lambda m: abs(m["refresh"] - fps),
    )["id"]


def prepare(width, height, fps, hdr):
    """Save the layout, then show only the primary monitor at the client's mode and dynamic range.

    The layout is saved once, so a stream that starts before the last one was
    restored does not overwrite the user's own layout.
    """
    serial, monitors, layout = _state()
    if not SAVED_PATH.exists():
        SAVED_PATH.parent.mkdir(parents=True, exist_ok=True)
        SAVED_PATH.write_text(json.dumps(layout))
    primary = next(lm for lm in layout if lm[4])
    connector, mode_id, props = primary[5][0]
    monitor = monitors[connector]
    mode_id = choose_mode(monitor["modes"], width, height, fps) or mode_id
    want = HDR if hdr and HDR in monitor["color_modes"] else SDR
    scale = primary[2] if primary[2] in monitor["scales"][mode_id] else 1.0
    # Other monitors are turned off: Sunshine captures one, and games should open on it.
    _apply(serial, [[0, 0, scale, primary[3], True, [[connector, mode_id, {"color-mode": want}]]]])


def restore():
    """Put back the layout saved by prepare(), if there is one."""
    try:
        layout = json.loads(SAVED_PATH.read_text())
    except (OSError, ValueError):
        return
    serial, _monitors, _layout = _state()
    _apply(serial, layout)
    os.remove(SAVED_PATH)
