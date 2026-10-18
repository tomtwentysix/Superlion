"""Asynchronous, cached loading of artwork into textures."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from gi.repository import GdkPixbuf, Gdk, GLib

from .. import config as config_mod

_executor = ThreadPoolExecutor(max_workers=4)
_cache = {}
_waiting = {}


def _local_copy(url):
    suffix = Path(url.split("?", 1)[0]).suffix or ".img"
    target = config_mod.cache_dir() / "images" / (hashlib.sha1(url.encode()).hexdigest() + suffix)
    if not target.is_file():
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
    return str(target)


def _decode(path, width, height):
    if path.startswith(("https://", "http://")):
        path = _local_copy(path)
    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, width, height, True)
    fmt = Gdk.MemoryFormat.R8G8B8A8 if pixbuf.get_has_alpha() else Gdk.MemoryFormat.R8G8B8
    return (
        pixbuf.get_width(),
        pixbuf.get_height(),
        fmt,
        pixbuf.read_pixel_bytes(),
        pixbuf.get_rowstride(),
    )


def load(path, width, height, callback):
    """Call callback(texture or None) on the main thread once the image is ready.

    path may be a local file or an https:// address, which is downloaded once.
    """
    if not path:
        callback(None)
        return
    key = (path, width, height)
    if key in _cache:
        callback(_cache[key])
        return
    if key in _waiting:
        _waiting[key].append(callback)
        return
    _waiting[key] = [callback]

    def finish(future):
        try:
            texture = Gdk.MemoryTexture.new(*future.result())
        except Exception:  # Unreadable or corrupt image files fall back to placeholders.
            texture = None
        _cache[key] = texture
        for cb in _waiting.pop(key, []):
            cb(texture)
        return GLib.SOURCE_REMOVE

    future = _executor.submit(_decode, path, width, height)
    future.add_done_callback(lambda f: GLib.idle_add(finish, f))


def forget(path):
    for key in [k for k in _cache if k[0] == path]:
        del _cache[key]


def corners_are_light(path, threshold=0.6):
    """Whether the top-left and top-right corners of an image are bright. Blocking.

    Returns (left, right), the areas behind a header bar's start and end
    buttons, so each side can use dark or light buttons; None if unreadable.
    """
    if path.startswith(("https://", "http://")):
        path = _local_copy(path)
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 120, 120, True)
    except GLib.Error:
        return None
    width, height = pixbuf.get_width(), pixbuf.get_height()
    channels, stride, pixels = pixbuf.get_n_channels(), pixbuf.get_rowstride(), pixbuf.get_pixels()
    strip, corner = max(1, height // 5), max(1, width // 6)

    def light(columns):
        total = count = 0
        for y in range(strip):
            for x in columns:
                offset = y * stride + x * channels
                r, g, b = pixels[offset], pixels[offset + 1], pixels[offset + 2]
                total += 0.2126 * r + 0.7152 * g + 0.0722 * b  # Relative luminance weights
                count += 1
        return total / count / 255 > threshold

    return light(range(corner)), light(range(width - corner, width))
