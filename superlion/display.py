"""Switching the streamed monitor's mode and HDR for Sunshine, and putting it back."""

import json
import os
from pathlib import Path

from gi.repository import Gio, GLib

BUS_NAME = "org.gnome.Mutter.DisplayConfig"
OBJECT_PATH = "/org/gnome/Mutter/DisplayConfig"
# ApplyMonitorsConfig methods. A temporary layout is not saved to monitors.xml and
# needs no confirmation; GNOME asks the user to keep a persistent one.
TEMPORARY = 1
PERSISTENT = 2
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

    monitors maps every connected monitor, on or off, to {"name", "modes",
    "scales", "color_modes"}, each mode being {"id", "width", "height",
    "refresh", "vrr", "current", "preferred"}.
    layout is the list of logical monitors in ApplyMonitorsConfig's own shape:
    [x, y, scale, transform, primary, [[connector, mode_id, {"color-mode": n}], ...]].
    """
    serial, raw_monitors, raw_logical, props = _call("GetCurrentState")
    logical_sizes = props.get("layout-mode", 1) == 1
    monitors = {}
    current = {}
    for (connector, *_), modes, monitor_props in raw_monitors:
        entries = [
            {
                "id": mode_id, "width": width, "height": height, "refresh": refresh,
                "vrr": mode_props.get("refresh-rate-mode") == "variable",
                "current": mode_props.get("is-current", False),
                "preferred": mode_props.get("is-preferred", False),
            }
            for mode_id, width, height, refresh, _scale, _scales, mode_props in modes
        ]
        monitors[connector] = {
            "name": monitor_props.get("display-name", connector),
            "modes": entries,
            "scales": {mode_id: scales for mode_id, *_, scales, _p in modes},
            "color_modes": monitor_props.get("supported-color-modes", [SDR]),
        }
        live = next((m["id"] for m in entries if m["current"]), None)
        if live:
            current[connector] = (live, monitor_props.get("color-mode", SDR))
    layout = [
        [x, y, scale, transform, primary,
         [[c, current[c][0], {"color-mode": current[c][1]}] for (c, *_) in specs if c in current]]
        for x, y, scale, transform, primary, specs, _props in raw_logical
    ]
    return serial, monitors, layout, logical_sizes


def monitors():
    """Every connected monitor except the primary one, as {connector: name}, including ones turned off."""
    _serial, found, layout, _sizes = _state()
    primary = {spec[0] for lm in layout if lm[4] for spec in lm[5]}
    return {connector: info["name"] for connector, info in found.items() if connector not in primary}


SIZES = {(3840, 2160): "4K", (2560, 1440): "1440p", (1920, 1080): "1080p"}


def capabilities(connector):
    """What the monitor can show, such as "4K at 30 Hz · 1080p at 120 Hz · No HDR"."""
    info = _state()[1].get(connector)
    if info is None:
        return "Not connected"
    best = {}
    for mode in info["modes"]:
        size = (mode["width"], mode["height"])
        if size in SIZES:
            best[size] = max(best.get(size, 0), round(mode["refresh"]))
    parts = [f"{SIZES[size]} at {hz} Hz" for size, hz in sorted(best.items(), reverse=True)]
    parts.append("HDR" if HDR in info["color_modes"] else "No HDR")
    return " · ".join(parts)


def _right_edge(monitors, layout, logical_sizes):
    """Where a monitor placed to the right of the whole layout starts."""
    edge = 0
    for x, _y, scale, transform, _primary, specs in layout:
        connector, mode_id, _props = specs[0]
        mode = next(m for m in monitors[connector]["modes"] if m["id"] == mode_id)
        width = mode["height"] if transform % 2 else mode["width"]
        edge = max(edge, x + round(width / scale if logical_sizes else width))
    return edge


def _apply(serial, layout, method=TEMPORARY):
    logical = [
        (x, y, scale, transform, primary,
         [(c, mode_id, {"color-mode": GLib.Variant("u", props["color-mode"])}) for c, mode_id, props in specs])
        for x, y, scale, transform, primary, specs in layout
    ]
    _call("ApplyMonitorsConfig", GLib.Variant(
        "(uua(iiduba(ssa{sv}))a{sv})", (serial, method, logical, {}),
    ))


def choose_mode(modes, width, height, fps):
    """The id of the mode to stream width x height at fps, or None to keep the current one.

    Sizes that reach fps come first, so a display that only manages 4K at
    30 Hz streams 1080p at 60 Hz rather than 4K at 30. Without the exact size,
    the smallest mode that covers it is used, so the picture is scaled down
    rather than up; failing that, the largest mode.
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
    # 59.94 Hz is near enough to 60.
    fast = {(m["width"], m["height"]) for m in fixed if m["refresh"] >= fps - 1} & sizes
    sizes = fast or sizes
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


def prepare(width, height, fps, hdr, target=""):
    """Save the layout, then show the stream at the client's mode and dynamic range.

    With a target connector, such as a dummy plug, the stream gets that monitor
    to itself: it is turned on to the right of the others and made primary, so
    games open there, and the user's monitors are left as they are. Otherwise
    the primary monitor is used and the others are turned off.

    The layout is saved once, so a stream that starts before the last one was
    restored does not overwrite the user's own layout.
    """
    serial, monitors, layout, logical_sizes = _state()
    if not SAVED_PATH.exists():
        SAVED_PATH.parent.mkdir(parents=True, exist_ok=True)
        SAVED_PATH.write_text(json.dumps(layout))
    others = [lm for lm in layout if not any(spec[0] == target for spec in lm[5])]
    if target in monitors:
        connector = target
        modes = monitors[target]["modes"]
        fallback = next((m["id"] for m in modes if m["preferred"]), modes[0]["id"])
        x, scale, transform = _right_edge(monitors, others, logical_sizes), 1.0, 0
        for lm in others:
            lm[4] = False
    else:
        primary = next(lm for lm in layout if lm[4])
        connector, fallback, _props = primary[5][0]
        x, scale, transform = 0, primary[2], primary[3]
        others = []
    monitor = monitors[connector]
    mode_id = choose_mode(monitor["modes"], width, height, fps) or fallback
    want = HDR if hdr and HDR in monitor["color_modes"] else SDR
    if scale not in monitor["scales"][mode_id]:
        scale = 1.0
    _apply(serial, others + [[x, 0, scale, transform, True, [[connector, mode_id, {"color-mode": want}]]]])


def _without(layout, connector):
    """The layout with connector's monitor turned off, keeping a primary monitor."""
    kept = [lm for lm in layout if not any(spec[0] == connector for spec in lm[5])]
    if kept and not any(lm[4] for lm in kept):
        kept[0][4] = True
    return kept


def turn_off(connector):
    """Turn a monitor off for good, such as a dummy plug between streams. True if it was on.

    Not while a stream has the layout saved, which restore() puts back without it.
    """
    serial, _monitors, layout, _sizes = _state()
    kept = _without(layout, connector)
    if SAVED_PATH.exists() or len(kept) == len(layout) or not kept:
        return False
    _apply(serial, kept, PERSISTENT)
    return True


def restore(stream_display=""):
    """Put back the layout saved by prepare(), if there is one, leaving stream_display off."""
    try:
        layout = json.loads(SAVED_PATH.read_text())
    except (OSError, ValueError):
        return
    _apply(_state()[0], _without(layout, stream_display) if stream_display else layout)
    os.remove(SAVED_PATH)
