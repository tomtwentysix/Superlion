"""Display information (EDID) for dummy plugs, so a stream can have the modes and HDR it needs.

An override is made permanent by edid-helper.sh, run as root through pkexec,
using the kernel's drm.edid_firmware option, which amdgpu, i915 and NVIDIA's
driver all honour.
"""

import glob
import subprocess
import threading
from pathlib import Path

from gi.repository import GLib

FIRMWARE_DIR = Path("/usr/lib/firmware/edid")
HELPER = Path(__file__).with_name("edid-helper.sh")

# (width, height, refresh, pixel clock kHz, h front porch, h sync, h blank, v front porch, v sync, v blank).
# CTA-861 timings where one exists, otherwise CVT reduced blanking.
TIMINGS = {
    "2160p60": (3840, 2160, 60, 594000, 176, 88, 560, 8, 10, 90),
    "2160p30": (3840, 2160, 30, 297000, 176, 88, 560, 8, 10, 90),
    "1440p120": (2560, 1440, 120, 497760, 48, 32, 160, 3, 5, 85),
    "1440p60": (2560, 1440, 60, 241500, 48, 32, 160, 3, 5, 41),
    "1080p120": (1920, 1080, 120, 297000, 88, 44, 280, 4, 5, 45),
    "1080p60": (1920, 1080, 60, 148500, 88, 44, 280, 4, 5, 45),
    "720p60": (1280, 720, 60, 74250, 110, 40, 370, 5, 5, 30),
}
# CTA-861 video codes for the timings that have one.
VICS = {"2160p60": 97, "2160p30": 95, "1080p120": 63, "1080p60": 16, "720p60": 4}

# What a dummy plug can be made to act as: (label, preferred mode, modes it also offers).
PROFILES = {
    "4k": ("4K HDR, 60 Hz", "2160p60", ["2160p30", "1440p120", "1440p60", "1080p120", "1080p60", "720p60"]),
    "1440p": ("1440p HDR, 120 Hz", "1440p120", ["1440p60", "1080p120", "1080p60", "720p60"]),
    "1080p": ("1080p HDR, 120 Hz", "1080p120", ["1080p60", "720p60"]),
}


def _dtd(name):
    width, height, _hz, clock, hfp, hsync, hblank, vfp, vsync, vblank = TIMINGS[name]
    size_w, size_h = 1210, 680  # millimetres, a 55" screen
    return bytes([
        (clock // 10) & 0xFF, (clock // 10) >> 8,
        width & 0xFF, hblank & 0xFF, (width >> 8) << 4 | hblank >> 8,
        height & 0xFF, vblank & 0xFF, (height >> 8) << 4 | vblank >> 8,
        hfp & 0xFF, hsync & 0xFF, (vfp & 0xF) << 4 | (vsync & 0xF),
        (hfp >> 8) << 6 | (hsync >> 8) << 4 | (vfp >> 4) << 2 | vsync >> 4,
        size_w & 0xFF, size_h & 0xFF, (size_w >> 8) << 4 | size_h >> 8,
        0, 0, 0x1E,  # no border; digital separate sync, both positive
    ])


def _text(tag, text):
    return bytes([0, 0, 0, tag, 0]) + (text.encode()[:13] + b"\n").ljust(13, b" ")[:13]


def _checksum(block):
    return block + bytes([-sum(block) % 256])


def generate(profile, displayport=False):
    """A 256-byte EDID for one of PROFILES."""
    _label, preferred, others = PROFILES[profile]
    modes = [preferred, *others]
    manufacturer = sum((ord(c) - 64) << shift for c, shift in zip("SFD", (10, 5, 0)))
    base = bytearray(b"\x00\xff\xff\xff\xff\xff\xff\x00")
    base += manufacturer.to_bytes(2, "big") + b"\x01\x00" + bytes(4)
    base += bytes([0, 2026 - 1990, 1, 4])
    # Digital, 8 bits per colour, on HDMI or DisplayPort; 121 x 68 cm; gamma 2.2;
    # RGB and YCbCr, preferred timing is native.
    base += bytes([0xA5 if displayport else 0xA2, 121, 68, 120, 0x1A])
    base += bytes.fromhex("ee91a3544c99260f5054")  # sRGB primaries
    base += bytes(3) + b"\x01\x01" * 8  # no established or standard timings
    base += _dtd(preferred)
    max_clock = max(TIMINGS[m][3] for m in modes)
    base += bytes([0, 0, 0, 0xFD, 0, 24, 120, 15, 255, -(-max_clock // 10000), 0, 0x0A]) + b" " * 6
    base += _text(0xFC, "Superlion")
    base += _text(0xFE, f"{profile.upper()} HDR")
    base += b"\x01"  # one extension
    base = _checksum(bytes(base))

    blocks = [
        bytes([2 << 5 | len([m for m in modes if m in VICS])] + [VICS[m] for m in modes if m in VICS]),
        bytes([3 << 5 | 7]) + bytes.fromhex("030c00") + bytes([0x10, 0x00, 0x18, 340 // 5]),
        # HDMI Forum: 600 MHz, SCDC and scrambling below 340 MHz.
        bytes([3 << 5 | 7]) + bytes.fromhex("d85dc4") + bytes([1, 600 // 5, 0x88, 0]),
        bytes([7 << 5 | 3, 0x05, 0xC0, 0x00]),  # BT.2020 YCC and RGB
        # HDR: SDR, PQ and HLG; 1000 nits peak, 400 average, 0.05 minimum.
        bytes([7 << 5 | 6, 0x06, 0x0D, 0x01, 138, 96, 18]),
    ]
    data = b"".join(blocks)
    dtds = b"".join(_dtd(m) for m in others if m not in VICS)
    cta = bytearray([0x02, 0x03, 4 + len(data), 0x30 | 1]) + data + dtds
    cta = _checksum(bytes(cta.ljust(127, b"\x00")))
    return base + cta


def kernel_connector(name):
    """The kernel's name for a connector GNOME calls name, such as HDMI-A-1 for HDMI-1."""
    for candidate in (name, name.replace("HDMI-", "HDMI-A-", 1)):
        if glob.glob(f"/sys/class/drm/card*-{candidate}"):
            return candidate
    return name


def current(name):
    """The connector's EDID as the kernel has it, override included, or b""."""
    for path in glob.glob(f"/sys/class/drm/card*-{kernel_connector(name)}/edid"):
        try:
            return Path(path).read_bytes()
        except OSError:
            pass
    return b""


def override(name):
    """The profile the connector's permanent override was made from, "other", or None without one."""
    try:
        saved = (FIRMWARE_DIR / f"superlion-{kernel_connector(name)}.bin").read_bytes()
    except OSError:
        return None
    displayport = name.startswith("DP")
    return next((p for p in PROFILES if generate(p, displayport) == saved), "other")


def apply(name, profile, callback):
    """Give the connector a profile's EDID now and after reboots, or its own again for None.

    Asks for the administrator password through pkexec. callback(error) gets
    None on success or a message.
    """
    connector = kernel_connector(name)
    args = ["pkexec", "/bin/bash", str(HELPER)]
    if profile:
        path = Path(GLib.get_user_runtime_dir()) / "superlion" / f"{connector}.edid"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(generate(profile, name.startswith("DP")))
        args += ["enable", connector, str(path)]
    else:
        args += ["disable", connector]

    def run():
        result = subprocess.run(args, capture_output=True, text=True)
        # pkexec exits 126 when the password dialog is dismissed.
        error = None if result.returncode == 0 else (
            "Cancelled" if result.returncode == 126 else result.stderr.strip() or "The change could not be made")
        GLib.idle_add(callback, error)

    threading.Thread(target=run, daemon=True).start()
