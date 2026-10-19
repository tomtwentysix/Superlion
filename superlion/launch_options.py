"""Splitting launch options into separate settings, and joining them back.

Steam launch options take the form

    VARIABLE=value … wrapper programs … %command% game arguments …

Each part becomes a setting that the launch options editor can switch on and
off. Anything not recognised is kept as written, so nothing is lost.
"""

import json
import os
import re
from collections import Counter
from itertools import combinations
from dataclasses import asdict, dataclass, field
from functools import cache
from pathlib import Path

from . import config as config_mod

COMMAND = "%command%"
VARIABLE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
NEEDS_QUOTES = re.compile(r"[\s;&|<>()]")

# Programs that start the game, in the order they are written before %command%.
WRAPPERS = ["prime-run", "gamemoderun", "game-performance", "obs-gamecapture", "mangohud", "strangle", "gamescope"]
# Programs whose options follow their name, up to the next variable or program.
TAKE_OPTIONS = {"strangle"}

ENV, WRAPPER, ARGUMENT = "env", "wrapper", "argument"

# Categories, in the order the editor shows them. Settings that only work on one
# make of graphics card are kept in its own category.
CATEGORIES = [
    "Tools",
    "Display and HDR",
    "Upscaling and Frame Generation",
    "Performance and Latency",
    "NVIDIA",
    "AMD",
    "DirectX and OpenGL",
    "Mods and DLLs",
    "Compatibility Fixes",
    "Videos and Cutscenes",
    "Online and Anti-Cheat",
    "Input",
    "Audio",
    "VR",
    "Logging",
    "Other Variables",
    "Game Arguments",
]

# Categories from earlier versions, for settings the user added then.
OLD_CATEGORIES = {"NVIDIA and DLSS": "NVIDIA", "Proton and Wine": "Compatibility Fixes"}


@dataclass
class Known:
    title: str
    category: str
    description: str = ""
    default: str = "1"


def _env(key, title, category, description, default="1"):
    return (ENV, key), Known(title, category, description, default)


def _program(key, title, category, description, default=""):
    return (WRAPPER, key), Known(title, category, description, default)


def _argument(key, title, description):
    return (ARGUMENT, key), Known(title, "Game Arguments", description, "")


# Settings Superlion can describe. Others found in the user's games are shown by
# name. Proton-CachyOS documents most of these; those from other Proton builds or
# from drivers say so.
CATALOGUE = dict([
    # Tools
    _program("gamemoderun", "GameMode", "Tools", "Applies Feral GameMode's performance tweaks while the game runs."),
    _program("mangohud", "MangoHud", "Tools", "Shows the MangoHud overlay with frame rate and usage."),
    _program(
        "gamescope", "Gamescope", "Tools",
        "Runs the game inside Valve's Gamescope compositor with these options. "
        "-w and -h set the game's resolution, -W and -H the output's, and -F fsr upscales with FSR 1.",
        "-f",
    ),
    _program("obs-gamecapture", "OBS Game Capture", "Tools", "Lets OBS Studio capture the game directly."),
    _program(
        "game-performance", "Performance Power Profile", "Tools",
        "Switches to the performance power profile while the game runs (CachyOS).",
    ),
    _program("strangle", "Frame Rate Limiter (libstrangle)", "Tools", "Limits the frame rate to the number given.", "60"),

    # Display and HDR
    _env(
        "PROTON_ENABLE_WAYLAND", "Wayland", "Display and HDR",
        "Runs the game in a native Wayland window instead of through Xwayland.",
    ),
    _env("DXVK_HDR", "HDR", "Display and HDR", "Turns on HDR output for games that support it."),
    _env(
        "DXVK_NO_HDR", "Turn Off HDR", "Display and HDR",
        "Keeps HDR off even where Proton would turn it on.",
    ),
    _env(
        "ENABLE_HDR_WSI", "HDR Vulkan Layer", "Display and HDR",
        "Turns on the Vulkan layer used for HDR. Only needed with NVIDIA drivers older than 595.",
    ),
    _env("DISABLE_HDR_WSI", "Turn Off HDR Vulkan Layer", "Display and HDR", "Turns off the Vulkan layer used for HDR."),
    _env(
        "WINE_FULLSCREEN_INTEGER_SCALING", "Integer Scaling", "Display and HDR",
        "Scales full-screen games by whole numbers, for sharp pixels.",
    ),
    _env(
        "PROTON_NO_WM_DECORATION", "Wine Window Borders", "Display and HDR",
        "Uses Wine's own window borders instead of the desktop's.",
    ),
    _env(
        "WINE_DISABLE_VULKAN_OPWR", "Turn Off Cross-Process Rendering", "Display and HDR",
        "Can remove a frame of delay in some launchers and games on Wayland.",
    ),
    _env("WINE_USE_KWIN_HACKS", "KDE Window Fixes", "Display and HDR", "Works around window problems on older KDE Plasma."),
    _env("DXVK_HUD", "DXVK Overlay", "Display and HDR", "Shows DXVK's overlay; fps shows the frame rate.", "fps"),
    _env(
        "DXVK_FRAME_RATE", "DXVK Frame Rate Limit", "Display and HDR",
        "Limits the frame rate of DirectX games running through DXVK.", "60",
    ),
    _env(
        "MANGOHUD", "MangoHud in Vulkan Games", "Display and HDR",
        "1 shows MangoHud in Vulkan games without the mangohud command.",
    ),
    _env("MANGOHUD_CONFIG", "MangoHud Settings", "Display and HDR", "MangoHud settings separated by commas.", "fps_limit=60"),
    _env("ENABLE_VKBASALT", "vkBasalt", "Display and HDR", "Applies vkBasalt's post-processing effects, such as sharpening."),
    _env(
        "SDL_VIDEODRIVER", "SDL Video Driver", "Display and HDR",
        "For native Linux games using SDL: wayland or x11.", "wayland",
    ),

    # Upscaling and frame generation that work on any graphics card
    _env(
        "WINE_FULLSCREEN_FSR", "FSR 1 Upscaling", "Upscaling and Frame Generation",
        "Upscales full-screen games with AMD FSR 1 when they run below your screen's resolution. "
        "Works on any graphics card (GE-Proton).",
    ),
    _env(
        "WINE_FULLSCREEN_FSR_STRENGTH", "FSR 1 Sharpness", "Upscaling and Frame Generation",
        "0 is the sharpest and 5 the softest; 2 is the default (GE-Proton).", "2",
    ),
    _env(
        "WINE_FULLSCREEN_FSR_CUSTOM_MODE", "FSR 1 Custom Resolution", "Upscaling and Frame Generation",
        "Offers games this resolution, such as 1920x1080, for FSR 1 to upscale from (GE-Proton).", "1920x1080",
    ),
    _env(
        "PROTON_FFX3_UPGRADE", "Upgrade FSR 3", "Upscaling and Frame Generation",
        "Upgrades the game's AMD FidelityFX 3 files, used for FSR 3 on any graphics card.",
    ),
    _env(
        "PROTON_XESS_UPGRADE", "Upgrade XeSS", "Upscaling and Frame Generation",
        "Upgrades the game's Intel XeSS to a newer version.",
    ),
    _env(
        "PROTON_USE_OPTISCALER", "OptiScaler", "Upscaling and Frame Generation",
        "Adds OptiScaler, which can replace a game's upscaler with FSR, XeSS or DLSS.",
    ),
    _env(
        "PROTON_OPTISCALER_NAME", "OptiScaler File Name", "Upscaling and Frame Generation",
        "The DLL OptiScaler is loaded as: dxgi.dll, d3d12.dll or dbghelp.dll.", "dxgi.dll",
    ),
    _env(
        "PROTON_OPTISCALER_CONFIG", "OptiScaler Settings", "Upscaling and Frame Generation",
        "Settings written to OptiScaler.ini, as Section.Option=value separated by semicolons.", "",
    ),
    _env(
        "DISABLE_LSFGVK", "Turn Off Lossless Scaling", "Upscaling and Frame Generation",
        "Turns off lsfg-vk frame generation for this game.",
    ),

    # Performance and latency
    _env(
        "PROTON_DXVK_LOWLATENCY", "Low-Latency DXVK", "Performance and Latency",
        "Uses a version of DXVK with better frame pacing and lower input lag for DirectX 9 to 11 games.",
    ),
    _env(
        "PROTON_VKD3D_LOWLATENCY", "Low-Latency VKD3D", "Performance and Latency",
        "Uses a version of VKD3D-Proton with better frame pacing and lower latency for DirectX 12 games.",
    ),
    _env(
        "LOW_LATENCY_LAYER", "Low Latency Layer", "Performance and Latency",
        "Turns on the low_latency_layer Vulkan layer.",
    ),
    _env(
        "PROTON_LOCAL_SHADER_CACHE", "Game Shader Cache", "Performance and Latency",
        "Keeps a shader cache for this game in its Steam library, even when Steam's shader pre-caching is off.",
    ),
    _env(
        "PROTON_NO_FSYNC", "Turn Off Fsync", "Performance and Latency",
        "Turns off futex synchronisation, which fixes some games.",
    ),
    _env(
        "PROTON_NO_ESYNC", "Turn Off Esync", "Performance and Latency",
        "Turns off eventfd synchronisation, which fixes some games in older Proton versions.",
    ),

    # NVIDIA only
    _program("prime-run", "NVIDIA PRIME", "NVIDIA", "Runs the game on the NVIDIA graphics card of a laptop."),
    _env(
        "PROTON_ENABLE_NVAPI", "NVAPI", "NVIDIA",
        "Gives the game NVIDIA's NVAPI, which DLSS and Reflex need in some games.",
    ),
    _env("PROTON_DISABLE_NVAPI", "Turn Off NVAPI", "NVIDIA", "Stops the game using NVIDIA's NVAPI."),
    _env("PROTON_DLSS_UPGRADE", "Upgrade DLSS", "NVIDIA", "Replaces the game's DLSS with the latest version, or the version given."),
    _env("PROTON_DLSS_INDICATOR", "DLSS Indicator", "NVIDIA", "Shows DLSS's overlay, to confirm which DLSS is in use."),
    _env("PROTON_ENABLE_NGX_UPDATER", "NGX Updater", "NVIDIA", "Lets NVIDIA's NGX updater download newer DLSS files."),
    _env(
        "DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE", "DLSS Super Resolution Override", "NVIDIA",
        "Overrides the game's DLSS Super Resolution settings.", "on",
    ),
    _env(
        "DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE_RENDER_PRESET_SELECTION", "DLSS Preset", "NVIDIA",
        "Chooses the DLSS Super Resolution preset.", "render_preset_m",
    ),
    _env(
        "DXVK_NVAPI_DRS_SETTINGS", "NVIDIA Driver Settings", "NVIDIA",
        "NVIDIA driver profile settings, applied through DXVK-NVAPI.", "",
    ),
    _env("DXVK_NVAPI_VKREFLEX", "Reflex in Vulkan Games", "NVIDIA", "Turns on NVIDIA Reflex for Vulkan games that support it."),
    _env("NVPRESENT_ENABLE_SMOOTH_MOTION", "Smooth Motion", "NVIDIA", "Turns on NVIDIA Smooth Motion frame generation."),
    _env(
        "VKLayer_DLSS5", "DLSS 5 Vulkan Layer", "NVIDIA",
        "Turns on the experimental DLSS5VKLayer, which sends the game's frames to NVIDIA's neural rendering.",
    ),
    _env(
        "PROTON_NVIDIA_LIBS", "NVIDIA Libraries", "NVIDIA",
        "Uses alternative NVIDIA CUDA, NVENC, NVML and OptiX libraries. Not used in WoW64 mode.",
    ),
    _env(
        "PROTON_NVIDIA_LIBS_NO_32BIT", "NVIDIA Libraries: 64-Bit Only", "NVIDIA",
        "With NVIDIA Libraries, uses only the 64-bit ones; useful on RTX 4000 and 5000 series cards.",
    ),
    _env(
        "PROTON_NVIDIA_NVCUDA", "NVIDIA CUDA", "NVIDIA",
        "Uses an alternative nvcuda.dll so games can use CUDA and GPU PhysX. Not used in WoW64 mode.",
    ),
    _env("PROTON_NVIDIA_NVENC", "NVIDIA Video Encoding", "NVIDIA", "Uses an alternative NVENC library, for games that record video."),
    _env("PROTON_NVIDIA_NVOPTIX", "NVIDIA OptiX", "NVIDIA", "Uses an alternative OptiX library, for ray tracing in some apps."),
    _env(
        "PROTON_HIDE_NVIDIA_GPU", "Hide NVIDIA Graphics Card", "NVIDIA",
        "Reports the graphics card as AMD, for games that misbehave on NVIDIA.",
    ),
    _env(
        "__GL_THREADED_OPTIMIZATIONS", "OpenGL Threaded Optimisations", "NVIDIA",
        "Can speed up OpenGL games on NVIDIA's driver.",
    ),
    _env(
        "__GL_SHADER_DISK_CACHE_SIZE", "OpenGL Shader Cache Size", "NVIDIA",
        "The size of NVIDIA's shader cache in bytes, such as 12000000000.", "12000000000",
    ),

    # AMD only
    _env(
        "PROTON_FSR4_UPGRADE", "Upgrade to FSR 4", "AMD",
        "Upgrades games with FSR 3.1 to FSR 4, or the version given. Needs an AMD Radeon RDNA 3 or newer graphics card.",
    ),
    _env("PROTON_FSR4_INDICATOR", "FSR 4 Indicator", "AMD", "Shows FSR's watermark, to confirm FSR 4 is in use."),
    _env(
        "PROTON_MLFG_UPGRADE", "FSR Machine Learning Frame Generation", "AMD",
        "Turns on FSR's machine learning frame generation, with FSR 4.0.3 or newer.",
    ),
    _env("PROTON_FFX4_UPGRADE", "Upgrade FidelityFX 4", "AMD", "Upgrades the game's AMD FidelityFX 4 files, used by FSR 4."),
    _env(
        "AMD_VULKAN_ICD", "AMD Vulkan Driver", "AMD",
        "RADV uses Mesa's driver, AMDVLK uses AMD's own.", "RADV",
    ),
    _env(
        "RADV_PERFTEST", "RADV Experimental Features", "AMD",
        "Experimental features of Mesa's AMD driver, separated by commas.", "",
    ),

    # DirectX and OpenGL
    _env(
        "PROTON_USE_WINED3D", "WineD3D", "DirectX and OpenGL",
        "1 draws DirectX 9 to 11 through OpenGL with WineD3D instead of DXVK; 0 keeps DXVK.",
    ),
    _env("PROTON_NO_D3D11", "Turn Off DirectX 11", "DirectX and OpenGL", "Makes games that can fall back to DirectX 9 do so."),
    _env("PROTON_NO_D3D10", "Turn Off DirectX 10", "DirectX and OpenGL", "Makes games that can fall back to DirectX 9 do so."),
    _env("PROTON_DXVK_D3D8", "DXVK for DirectX 8", "DirectX and OpenGL", "Runs DirectX 8 games through DXVK."),
    _env("PROTON_D7VK_DDRAW", "D7VK for DirectX 7", "DirectX and OpenGL", "Runs DirectX 7 and older games through D7VK."),
    _env(
        "PROTON_DXVK_SAREK", "DXVK for Older Graphics Cards", "DirectX and OpenGL",
        "Uses dxvk-sarek, for cards limited to Vulkan 1.1 or 1.2. Not for games with anti-cheat or multiplayer.",
    ),
    _env("VKD3D_CONFIG", "VKD3D-Proton Options", "DirectX and OpenGL", "VKD3D-Proton options for DirectX 12 games, such as dxr.", ""),
    _env(
        "VKD3D_FEATURE_LEVEL", "DirectX 12 Feature Level", "DirectX and OpenGL",
        "The DirectX 12 feature level reported to games, such as 12_0.", "12_0",
    ),
    _env(
        "PROTON_OLD_GL_STRING", "Short OpenGL Extension List", "DirectX and OpenGL",
        "Fixes older games that crash on a long list of OpenGL extensions.",
    ),

    # Mods and DLLs
    _env(
        "WINEDLLOVERRIDES", "DLL Overrides", "Mods and DLLs",
        "Loads the game's own copies of these DLLs (n) before Wine's (b), as mods such as ReShade need.", "",
    ),
    _env(
        "LD_PRELOAD", "Clear Preloaded Libraries", "Mods and DLLs",
        'Set to "" to stop libraries such as the Steam overlay being loaded into the game.', '""',
    ),

    # Compatibility fixes
    _env(
        "PROTON_FORCE_LARGE_ADDRESS_AWARE", "Large Address Aware", "Compatibility Fixes",
        "Lets 32-bit games use up to 4 GB of memory. On by default in current Proton.",
    ),
    _env(
        "PROTON_HEAP_DELAY_FREE", "Delay Freeing Memory", "Compatibility Fixes",
        "Works around crashes in games that use memory after freeing it.",
    ),
    _env("PROTON_USE_WOW64", "WoW64 Mode", "Compatibility Fixes", "Runs 32-bit Windows code with Wine's newer WoW64 mode."),
    _env("PROTON_SET_GAME_DRIVE", "Game Drive", "Compatibility Fixes", "Adds an S: drive for the Steam library the game is in."),
    _env(
        "HOST_LC_ALL", "Game Language and Region", "Compatibility Fixes",
        "Runs the game with this locale, such as ja_JP.UTF-8.", "en_GB.UTF-8",
    ),

    # Videos and cutscenes
    _env(
        "WINE_DO_NOT_CREATE_DXGI_DEVICE_MANAGER", "Video Playback Fix", "Videos and Cutscenes",
        "Works around videos that do not play in some games.",
    ),
    _env("PROTON_MEDIA_FORCE_GST", "GStreamer Video", "Videos and Cutscenes", "Fixes video and sound in some cutscenes."),

    # Online and anti-cheat
    _env("PROTON_USE_EAC_LINUX", "Easy Anti-Cheat for Linux", "Online and Anti-Cheat", "Uses the Linux Easy Anti-Cheat runtime."),
    _env(
        "WINE_BLOCK_HOSTS", "Block Internet Hosts", "Online and Anti-Cheat",
        "Stops the game connecting to these hosts, separated by commas.", "",
    ),
    _env(
        "PROTON_DISCORD_BRIDGE", "Discord Rich Presence", "Online and Anti-Cheat",
        "Lets the game show what you are playing in Discord.",
    ),

    # Input
    _env(
        "PROTON_PREFER_SDL", "SDL Controller Input", "Input",
        "Reads controllers through SDL instead of Steam Input. Can fix controllers on Wayland.",
    ),
    _env(
        "WINE_MOUSE_GRAB", "Keep Mouse in Window", "Input",
        "Locks the mouse to the game window, so it cannot drift to another monitor or break mouse-look.",
    ),
    _env(
        "PROTON_USE_XALIA", "Xalia Controller Interface", "Input",
        "1 adds Xalia's controller interface to programs made for keyboard and mouse; 0 turns it off.",
    ),

    # Audio
    _env("PULSE_SINK", "Audio Output", "Audio", "Sends the game's sound to this audio output.", ""),
    _env(
        "WINE_AUDIO_DRIVER", "Wine Audio Driver", "Audio",
        "The audio drivers to try, in order, such as pipewire,pulse,alsa.", "pulse",
    ),
    _env("PROTON_USE_PIPEWIRE", "PipeWire Audio", "Audio", "1 uses Wine's PipeWire driver, the default; 0 turns it off."),
    _env(
        "WINEALSA_CHANNELS", "Audio Channels", "Audio",
        "The number of audio channels: 2, 4, 6 or 8. 2 turns off spatial audio.", "2",
    ),

    # VR
    _env(
        "PRESSURE_VESSEL_IMPORT_OPENXR_1_RUNTIMES", "OpenXR Runtime", "VR",
        "Makes your OpenXR runtime, such as WiVRn, available inside Steam's container.",
    ),
    _env(
        "PRESSURE_VESSEL_FILESYSTEMS_RW", "Container Folders", "VR",
        "Folders Steam's container may write to, such as your VR runtime's.", "",
    ),

    # Logging
    _env("PROTON_LOG", "Proton Log", "Logging", "Writes a log to steam-<app ID>.log in your home folder."),
    _env("PROTON_LOG_DIR", "Proton Log Folder", "Logging", "The folder Proton's logs are written to.", "~/proton-logs"),
    _env("PROTON_CRASH_REPORT_DIR", "Crash Report Folder", "Logging", "Saves crash reports to this folder.", "~/proton-crashes"),

    # Other
    _env(
        "VK_INSTANCE_LAYERS", "Vulkan Layers", "Other Variables",
        "Vulkan layers to load, separated by colons.", "",
    ),
    _env("SteamDeck", "Steam Deck Mode", "Other Variables", "Makes some games use their Steam Deck settings."),

    # Game arguments understood by many games
    _argument("-dx11", "DirectX 11", "Asks the game to use DirectX 11."),
    _argument("-dx12", "DirectX 12", "Asks the game to use DirectX 12."),
    _argument("-vulkan", "Vulkan", "Asks the game to use Vulkan."),
    _argument("-windowed", "Windowed", "Asks the game to start in a window."),
    _argument("-fullscreen", "Full Screen", "Asks the game to start full screen."),
    _argument("-novid", "Skip Intro Videos (Source)", "Skips the intro videos in Source engine games."),
    _argument("-skipintro", "Skip Intro", "Skips the intro in games that support it."),
])


# Settings whose value is a list: the separator, and items to offer.
LISTS = {
    "VKD3D_CONFIG": (",", ["dxr", "nodxr", "force_static_cbv", "single_queue", "no_upload_hvv",
                           "pipeline_library_app_cache", "small_vram_rebar"]),
    "DXVK_HUD": (",", ["fps", "frametimes", "gpuload", "memory", "devinfo", "version", "api", "compiler", "full"]),
    "MANGOHUD_CONFIG": (",", ["fps_limit=60", "fps", "frametime", "gpu_stats", "cpu_stats", "vram", "ram", "no_display"]),
    "RADV_PERFTEST": (",", ["gpl", "rt", "sam", "nggc", "video_decode"]),
    "WINE_AUDIO_DRIVER": (",", ["pipewire", "pulse", "alsa"]),
    "WINE_BLOCK_HOSTS": (",", []),
    "DXVK_NVAPI_DRS_SETTINGS": (",", []),
    "PROTON_OPTISCALER_CONFIG": (";", []),
    "VK_INSTANCE_LAYERS": (":", []),
    "PRESSURE_VESSEL_FILESYSTEMS_RW": (":", []),
}
# Settings with a known set of values, as [(value, label)].
CHOICES = {
    "WINEALSA_CHANNELS": [("2", "2 (Stereo)"), ("4", "4"), ("6", "6 (5.1)"), ("8", "8 (7.1)")],
    "AMD_VULKAN_ICD": [("RADV", "RADV (Mesa)"), ("AMDVLK", "AMDVLK (AMD)")],
    "SDL_VIDEODRIVER": [("wayland", "Wayland"), ("x11", "X11")],
    "PROTON_OPTISCALER_NAME": [("dxgi.dll", "dxgi.dll"), ("d3d12.dll", "d3d12.dll"), ("dbghelp.dll", "dbghelp.dll")],
    "WINE_FULLSCREEN_FSR_STRENGTH": [("0", "0 (Sharpest)"), ("1", "1"), ("2", "2 (Default)"), ("3", "3"),
                                     ("4", "4"), ("5", "5 (Softest)")],
    "VKD3D_FEATURE_LEVEL": [(level, level) for level in ("11_0", "11_1", "12_0", "12_1", "12_2")],
    "DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE": [("on", "On"), ("off", "Off")],
    "DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE_RENDER_PRESET_SELECTION": [
        ("render_preset_default", "Default"),
        *((f"render_preset_{p}", f"Preset {p.upper()}") for p in "jklm"),
    ],
}
# WINEDLLOVERRIDES load orders: which copy of a DLL is used.
DLL_ORDERS = [
    ("n,b", "Game's Copy First"),
    ("b,n", "Wine's Copy First"),
    ("n", "Game's Copy Only"),
    ("b", "Wine's Copy Only"),
    ("", "Disabled"),
]


def split_dll_overrides(value):
    """[(dll, load order)] from a value such as "dxgi,dinput8=n,b;d3d11=b". A DLL without an order gets n,b."""
    items = []
    for part in value.strip("\"'").split(";"):
        names, equals, order = part.partition("=")
        for name in names.split(","):
            if name.strip():
                items.append((name.strip(), order.strip() if equals else "n,b"))
    return items


def join_dll_overrides(items):
    """The value for [(dll, load order)], DLLs with the same order sharing one entry."""
    orders = {}
    for name, order in items:
        orders.setdefault(order, []).append(name)
    return ";".join(f"{','.join(names)}={order}" for order, names in orders.items())


@dataclass
class Custom:
    kind: str
    key: str
    title: str
    category: str
    description: str = ""
    default: str = "1"


def _custom_path():
    return config_mod.config_dir() / "launch_settings.json"


def custom_settings():
    """Settings the user added to the editor, keyed by (kind, key)."""
    try:
        data = json.loads(_custom_path().read_text())
    except (OSError, ValueError):
        return {}
    result = {}
    for item in data.get("settings", []):
        try:
            custom = Custom(**item)
        except TypeError:
            continue
        custom.category = OLD_CATEGORIES.get(custom.category, custom.category)
        if custom.category not in CATEGORIES:
            custom.category = default_category(custom.kind)
        result[(custom.kind, custom.key)] = custom
    return result


def _save_custom(settings):
    path = _custom_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"settings": [asdict(c) for c in settings.values()]}, indent=2))
    os.replace(tmp, path)


def add_custom(custom):
    settings = custom_settings()
    settings[(custom.kind, custom.key)] = custom
    _save_custom(settings)


def remove_custom(kind, key):
    settings = custom_settings()
    settings.pop((kind, key), None)
    _save_custom(settings)


def is_valid_key(kind, key):
    """Whether a name can be used for a setting of this kind."""
    if kind == ENV:
        return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key))
    if kind == WRAPPER:
        return bool(key) and not any(c.isspace() for c in key) and key not in (COMMAND, "--", "env")
    return bool(key.strip()) and COMMAND not in key


def tokenize(options):
    """Split on spaces outside quotes, keeping the quotes in each word."""
    words, current, quote = [], "", ""
    for char in options:
        if quote:
            current += char
            if char == quote:
                quote = ""
        elif char in "\"'":
            current += char
            quote = char
        elif char.isspace():
            if current:
                words.append(current)
            current = ""
        else:
            current += char
    if current:
        words.append(current)
    return words


@dataclass
class Parsed:
    env: list = field(default_factory=list)  # [(name, value)], value as written, quotes included
    wrappers: dict = field(default_factory=dict)  # {program: its options}
    other: list = field(default_factory=list)  # Unrecognised words before %command%
    arguments: list = field(default_factory=list)  # Game arguments, each with its values


def parse(options, programs=()):
    """Split launch options; programs are extra wrapper programs to recognise."""
    words = tokenize(options)
    parsed = Parsed()
    if COMMAND not in words:
        # Without %command%, Steam passes everything to the game as arguments.
        parsed.arguments = _group_arguments(words)
        return parsed
    split = words.index(COMMAND)
    before, after = words[:split], words[split + 1:]
    i = 0
    while i < len(before):
        word = before[i]
        name = word.rsplit("/", 1)[-1]
        match = VARIABLE.match(word)
        if match:
            parsed.env.append((match.group(1), match.group(2)))
        elif name == "gamescope":
            # Its options run up to "--", after which the game's command follows.
            end = before.index("--", i) if "--" in before[i:] else len(before)
            parsed.wrappers["gamescope"] = " ".join(before[i + 1:end])
            i = end
        elif name in WRAPPERS and name not in TAKE_OPTIONS:
            parsed.wrappers[name] = ""
        elif name in programs or name in TAKE_OPTIONS:
            # Its options are the words up to the next variable or program.
            end = i + 1
            while end < len(before) and not (
                VARIABLE.match(before[end]) or before[end] in ("--", "env")
                or before[end].rsplit("/", 1)[-1] in (*WRAPPERS, *programs)
            ):
                end += 1
            parsed.wrappers[name] = " ".join(before[i + 1:end])
            i = end - 1
        elif word != "env":  # "env" only sets the variables that follow it.
            parsed.other.append(word)
        i += 1
    parsed.arguments = _group_arguments(after)
    return parsed


def _group_arguments(words):
    """Group each -option or +option with the values that follow it."""
    groups = []
    for word in words:
        if groups and not word.startswith(("-", "+")):
            groups[-1] += " " + word
        else:
            groups.append(word)
    return groups


NOT_NEEDED, BREAKS = "not-needed", "breaks"

# PCI vendor IDs, as in /sys/class/drm/card*/device/vendor.
GRAPHICS_VENDORS = {"0x10de": "NVIDIA", "0x1002": "AMD", "0x8086": "Intel"}

HDR_VARIABLES = ["DXVK_HDR", "PROTON_ENABLE_HDR", "ENABLE_HDR_WSI"]
# Misspelt and old names: the name to use instead, and why.
RENAMES = {
    "WINE_DLL_OVERRIDES": ("WINEDLLOVERRIDES", "Wine does not read this name. Use DLL Overrides (WINEDLLOVERRIDES)."),
    "PROTON_ENABLE_HDR": (
        "DXVK_HDR", "An old name for HDR (DXVK_HDR). Only GE-Proton still reads it; other Protons ignore it.",
    ),
}
# Settings that only DXVK reads, which do nothing when WineD3D replaces it.
DXVK_SETTINGS = ["DXVK_HDR", "DXVK_NO_HDR", "DXVK_HUD", "DXVK_FRAME_RATE", "PROTON_DXVK_LOWLATENCY", "PROTON_DXVK_D3D8"]
# Each setting, and the setting it undoes when both are on.
OPPOSITES = {
    "PROTON_DISABLE_NVAPI": "PROTON_ENABLE_NVAPI",
    "DXVK_NO_HDR": "DXVK_HDR",
    "DISABLE_HDR_WSI": "ENABLE_HDR_WSI",
}


@dataclass
class LaunchWarning:
    key: tuple  # (kind, key) of the setting it is about
    kind: str  # NOT_NEEDED or BREAKS
    rule: str  # The check that found it, such as "duplicate"
    text: str

    @property
    def id(self):
        """Stays the same while the setting is unchanged, so an ignored warning stays ignored."""
        return f"{self.rule}:{self.key[0]}:{self.key[1]}"


@cache
def graphics_vendors():
    """Makes of graphics card in this computer, such as {"NVIDIA"}; empty when unknown."""
    found = set()
    for path in Path("/sys/class/drm").glob("card*/device/vendor"):
        try:
            found.add(GRAPHICS_VENDORS.get(path.read_text().strip(), ""))
        except OSError:
            pass
    return found - {""}


@cache
def nvidia_driver():
    """The loaded NVIDIA driver's major version, or 0."""
    try:
        return int(Path("/sys/module/nvidia/version").read_text().split(".")[0])
    except (OSError, ValueError):
        return 0


def _is_on(value):
    return value.strip("\"'") not in ("", "0")


def warnings(options, custom=None):
    """Settings in the launch options that do nothing on this computer, or stop something else working."""
    custom = custom if custom is not None else custom_settings()
    parsed = parse(options, custom_programs(custom))
    env = dict(parsed.env)
    on = {name for name, value in env.items() if _is_on(value)}
    found = []

    def warn(name, kind, rule, text, setting_kind=ENV):
        found.append(LaunchWarning((setting_kind, name), kind, rule, text))

    def named(kind, name):
        title = setting_for(kind, name, custom).title
        return f"{title} ({name})" if kind == ENV and title != name else title

    for name, count in Counter(name for name, _value in parsed.env).items():
        if count > 1:
            warn(name, NOT_NEEDED, "duplicate", f"Set {count} times. Only the last value is used.")

    vendors = graphics_vendors()
    for kind, key in [(ENV, name) for name in env] + [(WRAPPER, name) for name in parsed.wrappers]:
        category = setting_for(kind, key, custom).category
        if category in ("NVIDIA", "AMD") and vendors and category not in vendors:
            warn(key, NOT_NEEDED, "vendor", f"No {category} graphics card was found.", kind)

    for name, (_new, text) in RENAMES.items():
        if name in env:
            warn(name, NOT_NEEDED, "rename", text)
    if env.get("PROTON_USE_PIPEWIRE") == "1":
        warn("PROTON_USE_PIPEWIRE", NOT_NEEDED, "default", "PipeWire audio is already the default.")

    hdr_capable = "PROTON_ENABLE_WAYLAND" in on or "gamescope" in parsed.wrappers
    for name in HDR_VARIABLES:
        if name not in on:
            continue
        if not hdr_capable:
            warn(name, NOT_NEEDED, "hdr-display", "HDR only works with Wayland (PROTON_ENABLE_WAYLAND=1) or Gamescope.")
        elif name == "ENABLE_HDR_WSI" and vendors == {"NVIDIA"} and nvidia_driver() >= 595:
            warn(name, NOT_NEEDED, "hdr-driver", "NVIDIA drivers from 595 output HDR without this layer.")

    for name, opposite in OPPOSITES.items():
        if name in on and opposite in on:
            warn(name, BREAKS, "opposite", f"Undoes {named(ENV, opposite)}, which is also set.")

    for first, second, reason in conflicts(parsed, on):
        for (kind, key), (other_kind, other) in ((first, second), (second, first)):
            warn(key, BREAKS, f"conflict-{other}", f"Conflicts with {named(other_kind, other)}. {reason}", kind)

    if "LD_PRELOAD" in env and not env["LD_PRELOAD"].strip("\"'"):
        warn(
            "LD_PRELOAD", BREAKS, "overlay",
            "Stops the Steam overlay and its screenshots.",
        )
    if "PROTON_PREFER_SDL" in on:
        warn("PROTON_PREFER_SDL", BREAKS, "steam-input", "Controller layouts set in Steam Input are not used.")
    return found


def conflicts(parsed, on):
    """Pairs of settings that work against each other, as [((kind, key), (kind, key), reason)]."""
    gamescope = (WRAPPER, "gamescope")
    gamescope_options = tokenize(parsed.wrappers.get("gamescope", "")) if "gamescope" in parsed.wrappers else None
    found = []
    if gamescope_options is not None:
        if "PROTON_ENABLE_WAYLAND" in on and "--expose-wayland" not in gamescope_options:
            found.append((gamescope, (ENV, "PROTON_ENABLE_WAYLAND"),
                          "Games in a Wayland window do not start inside Gamescope without its --expose-wayland option."))
        if "--mangoapp" in gamescope_options:
            for key in [(WRAPPER, "mangohud")] * ("mangohud" in parsed.wrappers) + [(ENV, "MANGOHUD")] * ("MANGOHUD" in on):
                found.append((gamescope, key, "Gamescope's --mangoapp shows MangoHud already."))
        if "--hdr-enabled" in gamescope_options and "ENABLE_HDR_WSI" in on:
            found.append((gamescope, (ENV, "ENABLE_HDR_WSI"),
                          "Gamescope outputs HDR itself, and the HDR Vulkan layer can stop games starting inside it."))
    if "PROTON_USE_WINED3D" in on:
        for name in DXVK_SETTINGS:
            if name in on:
                found.append(((ENV, "PROTON_USE_WINED3D"), (ENV, name), "WineD3D replaces DXVK, so DXVK's settings do nothing."))
    limits = [(ENV, "DXVK_FRAME_RATE")] * ("DXVK_FRAME_RATE" in on)
    if gamescope_options and {"-r", "--framerate-limit"} & set(gamescope_options):
        limits.append(gamescope)
    if "fps_limit=" in dict(parsed.env).get("MANGOHUD_CONFIG", ""):
        limits.append((ENV, "MANGOHUD_CONFIG"))
    if "strangle" in parsed.wrappers:
        limits.append((WRAPPER, "strangle"))
    for first, second in combinations(limits, 2):
        found.append((first, second, "Two frame rate limits work against each other."))
    return found


def quote(value):
    """The value as written in launch options, quoted if it needs to be."""
    if value[:1] in "\"'" or not NEEDS_QUOTES.search(value):
        return value
    return '"' + value.replace('"', '\\"') + '"'


def compose(env, wrappers, other, arguments):
    """Launch options from settings: env [(name, value)], wrappers {program: options}."""
    words = [f"{name}={quote(value)}" for name, value in env]
    # Known programs first, then the user's own, which run closest to the game.
    for program in [p for p in WRAPPERS if p in wrappers] + [p for p in wrappers if p not in WRAPPERS]:
        if program == "gamescope":
            words += ["gamescope", wrappers[program], "--"]
        else:
            words += [program, wrappers[program]]
    words += other
    words.append(COMMAND)
    words += arguments
    options = " ".join(w for w in words if w)
    return "" if options == COMMAND else options


@dataclass
class Setting:
    kind: str  # ENV, WRAPPER or ARGUMENT
    key: str  # Variable name, program name, or the argument as written
    title: str
    category: str
    description: str
    values: Counter  # Values used across the user's games, by number of games
    games: int  # Number of games using it
    default: str = "1"  # Value used when none of the user's games has one
    custom: bool = False  # Added to the editor by the user

    @property
    def takes_value(self):
        if self.kind == ARGUMENT:
            return False
        if self.kind == WRAPPER:
            return self.key == "gamescope" or bool(self.default) or any(self.values)
        return (set(self.values) or {self.common_value}) != {"1"}

    @property
    def common_value(self):
        if self.values:
            return self.values.most_common(1)[0][0]
        return self.default


def default_category(kind):
    return "Game Arguments" if kind == ARGUMENT else "Tools" if kind == WRAPPER else "Other Variables"


def setting_for(kind, key, custom=None):
    custom = custom if custom is not None else custom_settings()
    known = custom.get((kind, key)) or CATALOGUE.get((kind, key))
    default = "" if kind == WRAPPER else "1"
    if known:
        return Setting(
            kind, key, known.title, known.category, known.description, Counter(), 0,
            known.default, (kind, key) in custom,
        )
    return Setting(kind, key, key, default_category(kind), "", Counter(), 0, default)


def suggestions(present):
    """Settings Superlion knows that are not among the present (kind, key) pairs."""
    return [setting_for(kind, key, {}) for kind, key in CATALOGUE if (kind, key) not in present]


def baseline(all_options):
    """Every setting Superlion knows, used in the given launch options, or added by the user.

    Returns {(kind, key): Setting}, counting how many games use each setting and
    which values they use.
    """
    settings = {}
    custom = custom_settings()
    programs = custom_programs(custom)

    def note(kind, key, value=None):
        setting = settings.setdefault((kind, key), setting_for(kind, key, custom))
        setting.games += 1
        if value is not None:
            setting.values[value] += 1

    for options in all_options:
        parsed = parse(options, programs)
        for name, value in dict(parsed.env).items():
            note(ENV, name, value)
        for program, program_options in parsed.wrappers.items():
            note(WRAPPER, program, program_options if program_options or program == "gamescope" else None)
        for argument in dict.fromkeys(parsed.arguments):
            note(ARGUMENT, argument)
    for kind, key in [*CATALOGUE, *custom]:
        settings.setdefault((kind, key), setting_for(kind, key, custom))
    return settings


def custom_programs(custom=None):
    """Names of programs the user added, for parse()."""
    custom = custom if custom is not None else custom_settings()
    return {key for kind, key in custom if kind == WRAPPER}


SHORT_VALUE = 20  # Longer values are left out of summaries.


def summary(options, custom=None):
    """Launch options described by setting name, such as "GameMode, Wayland, DLSS Preset (render_preset_m)"."""
    custom = custom if custom is not None else custom_settings()
    parsed = parse(options, custom_programs(custom))
    items = (
        [(setting_for(WRAPPER, name, custom), "") for name in parsed.wrappers]
        + [(setting_for(ENV, name, custom), value) for name, value in parsed.env]
        + [(setting_for(ARGUMENT, argument, custom), "") for argument in parsed.arguments]
    )
    items.sort(key=lambda item: CATEGORIES.index(item[0].category) if item[0].category in CATEGORIES else len(CATEGORIES))
    parts = []
    for setting, value in items:
        value = value.strip("\"'")
        if setting.kind == ENV and value not in ("", "1") and len(value) <= SHORT_VALUE:
            parts.append(f"{setting.title}: {value}")
        else:
            parts.append(setting.title)
    parts += parsed.other
    return ", ".join(parts) if parts else "None"


def fix_label(warning):
    return {"duplicate": "Keep Last", "rename": "Rename"}.get(warning.rule, "Remove")


def fix(options, warning, remove=False):
    """The launch options with the warning's setting removed; a duplicate keeps its last value and an old name is
    replaced, unless remove is set."""
    parsed = parse(options, custom_programs())
    kind, key = warning.key
    if kind == ENV:
        last = max((i for i, (name, _value) in enumerate(parsed.env) if name == key), default=-1)
        env = []
        for i, (name, value) in enumerate(parsed.env):
            if name != key:
                env.append((name, value))
            elif warning.rule == "duplicate" and i == last:
                env.append((name, value))
            elif warning.rule == "rename" and not remove and i == last and RENAMES[key][0] not in dict(parsed.env):
                env.append((RENAMES[key][0], value))
        parsed.env = env
    elif kind == WRAPPER:
        parsed.wrappers.pop(key, None)
    else:
        parsed.arguments = [a for a in parsed.arguments if a != key]
    return compose(parsed.env, parsed.wrappers, parsed.other, parsed.arguments)


def has_setting(options, kind, key):
    parsed = parse(options, custom_programs())
    if kind == ENV:
        return key in dict(parsed.env)
    return key in (parsed.wrappers if kind == WRAPPER else parsed.arguments)


def with_setting(options, kind, key, value="", on=True):
    """The launch options with a setting switched on (with this value) or off; unchanged if already so."""
    parsed = parse(options, custom_programs())
    if kind == ENV:
        current = dict(parsed.env)
        if (current.get(key) == value) if on else key not in current:
            return options
        parsed.env = [(name, v) for name, v in parsed.env if name != key] + ([(key, value)] if on else [])
    elif kind == WRAPPER:
        if (parsed.wrappers.get(key, None) == value) if on else key not in parsed.wrappers:
            return options
        parsed.wrappers.pop(key, None)
        if on:
            parsed.wrappers[key] = value
    else:
        if (key in parsed.arguments) == on:
            return options
        parsed.arguments = [a for a in parsed.arguments if a != key] + ([key] if on else [])
    return compose(parsed.env, parsed.wrappers, parsed.other, parsed.arguments)


def _ignored_path():
    return config_mod.config_dir() / "ignored_warnings.json"


def ignored_warnings():
    """{app ID: {warning ID}} for the warnings the user chose to ignore."""
    try:
        data = json.loads(_ignored_path().read_text())
    except (OSError, ValueError):
        return {}
    return {int(appid): set(ids) for appid, ids in data.items() if appid.isdigit()}


def set_ignored(appid, warning, ignore=True):
    ignored = ignored_warnings()
    ids = ignored.setdefault(int(appid), set())
    if ignore:
        ids.add(warning.id)
    else:
        ids.discard(warning.id)
    path = _ignored_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({str(a): sorted(i) for a, i in ignored.items() if i}, indent=2))
    os.replace(tmp, path)
