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
from dataclasses import asdict, dataclass, field

from . import config as config_mod

COMMAND = "%command%"
VARIABLE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
NEEDS_QUOTES = re.compile(r"[\s;&|<>()]")

# Programs that start the game, in the order they are written before %command%.
WRAPPERS = ["prime-run", "gamemoderun", "obs-gamecapture", "mangohud", "gamescope"]

ENV, WRAPPER, ARGUMENT = "env", "wrapper", "argument"

# Categories, in the order the editor shows them.
CATEGORIES = [
    "Tools",
    "Display and HDR",
    "NVIDIA and DLSS",
    "Proton and Wine",
    "Audio",
    "VR",
    "Other Variables",
    "Game Arguments",
]


@dataclass
class Known:
    title: str
    category: str
    description: str = ""
    default: str = "1"


# Settings Superlion can describe. Others found in the user's games are shown by name.
CATALOGUE = {
    (WRAPPER, "gamemoderun"): Known("GameMode", "Tools", "Applies Feral GameMode's performance tweaks while the game runs.", ""),
    (WRAPPER, "mangohud"): Known("MangoHud", "Tools", "Shows the MangoHud overlay with frame rate and usage.", ""),
    (WRAPPER, "gamescope"): Known(
        "Gamescope", "Tools", "Runs the game inside Valve's Gamescope compositor with these options.", "-f"
    ),
    (WRAPPER, "prime-run"): Known("NVIDIA PRIME", "Tools", "Runs the game on the NVIDIA graphics card of a laptop.", ""),
    (WRAPPER, "obs-gamecapture"): Known("OBS Game Capture", "Tools", "Lets OBS Studio capture the game directly.", ""),
    (ENV, "PROTON_ENABLE_WAYLAND"): Known(
        "Wayland", "Display and HDR", "Runs the game in a native Wayland window instead of through Xwayland."
    ),
    (ENV, "PROTON_ENABLE_HDR"): Known("Proton HDR", "Display and HDR", "Turns on HDR output in Proton. Needs Wayland."),
    (ENV, "DXVK_HDR"): Known("DXVK HDR", "Display and HDR", "Lets DirectX games running through DXVK output HDR."),
    (ENV, "ENABLE_HDR_WSI"): Known("HDR Vulkan Layer", "Display and HDR", "Turns on the Vulkan layer used for HDR."),
    (ENV, "DISABLE_HDR_WSI"): Known("Disable HDR Vulkan Layer", "Display and HDR", "Turns off the Vulkan layer used for HDR."),
    (ENV, "DISABLE_LSFGVK"): Known(
        "Disable Lossless Scaling", "Display and HDR", "Turns off lsfg-vk frame generation for this game."
    ),
    (ENV, "PROTON_ENABLE_NVAPI"): Known(
        "NVAPI", "NVIDIA and DLSS", "Gives the game NVIDIA's NVAPI, which DLSS and Reflex need in some games."
    ),
    (ENV, "PROTON_DLSS_UPGRADE"): Known("Upgrade DLSS", "NVIDIA and DLSS", "Replaces the game's DLSS with the latest version."),
    (ENV, "PROTON_ENABLE_NGX_UPDATER"): Known(
        "NGX Updater", "NVIDIA and DLSS", "Lets NVIDIA's NGX updater download newer DLSS files."
    ),
    (ENV, "DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE"): Known(
        "DLSS Super Resolution Override", "NVIDIA and DLSS", "Overrides the game's DLSS Super Resolution settings.", "on"
    ),
    (ENV, "DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE_RENDER_PRESET_SELECTION"): Known(
        "DLSS Preset", "NVIDIA and DLSS", "Chooses the DLSS Super Resolution preset.", "render_preset_m"
    ),
    (ENV, "DXVK_NVAPI_DRS_SETTINGS"): Known(
        "NVIDIA Driver Settings", "NVIDIA and DLSS", "NVIDIA driver profile settings, applied through DXVK-NVAPI.", ""
    ),
    (ENV, "NVPRESENT_ENABLE_SMOOTH_MOTION"): Known(
        "Smooth Motion", "NVIDIA and DLSS", "Turns on NVIDIA Smooth Motion frame generation."
    ),
    (ENV, "PROTON_NVIDIA_NVCUDA"): Known(
        "NVIDIA CUDA", "NVIDIA and DLSS",
        "Uses an alternative nvcuda.dll so games can use CUDA and GPU PhysX (Proton-CachyOS). "
        "Not used in WoW64 mode.",
    ),
    (ENV, "VKLayer_DLSS5"): Known(
        "DLSS 5 Vulkan Layer", "NVIDIA and DLSS",
        "Turns on the experimental DLSS5VKLayer, which sends the game's frames to NVIDIA's neural rendering.",
    ),
    (ENV, "WINE_MOUSE_GRAB"): Known(
        "Keep Mouse in Window", "Proton and Wine",
        "Locks the mouse to the game window, so it cannot drift to another monitor or break mouse-look.",
    ),
    (ENV, "VK_INSTANCE_LAYERS"): Known("Vulkan Layers", "Other Variables", "Vulkan layers to load, separated by colons.", ""),
    (ENV, "LD_PRELOAD"): Known(
        "Clear Preloaded Libraries", "Proton and Wine",
        'Set to "" to stop libraries such as the Steam overlay being loaded into the game.', '""',
    ),
    (ENV, "WINEDLLOVERRIDES"): Known(
        "DLL Overrides", "Proton and Wine",
        "Loads the game's own copies of these DLLs (n) before Wine's (b), as mods such as ReShade need.", "",
    ),
    (ENV, "WINE_DLL_OVERRIDES"): Known(
        "DLL Overrides (Misspelt)", "Proton and Wine",
        "Wine does not read this name. Use DLL Overrides (WINEDLLOVERRIDES) instead.", "",
    ),
    (ENV, "PROTON_USE_WINED3D"): Known(
        "WineD3D", "Proton and Wine", "1 draws DirectX through OpenGL with WineD3D instead of DXVK; 0 keeps DXVK."
    ),
    (ENV, "PROTON_USE_WOW64"): Known("WoW64 Mode", "Proton and Wine", "Runs 32-bit Windows code with Wine's newer WoW64 mode."),
    (ENV, "PROTON_USE_EAC_LINUX"): Known("Easy Anti-Cheat for Linux", "Proton and Wine", "Uses the Linux Easy Anti-Cheat runtime."),
    (ENV, "PROTON_LOG"): Known("Proton Log", "Proton and Wine", "Writes a log to steam-<app ID>.log in your home folder."),
    (ENV, "PROTON_NO_ESYNC"): Known(
        "Disable Esync", "Proton and Wine", "Turns off eventfd synchronisation, which fixes some games."
    ),
    (ENV, "PROTON_NO_FSYNC"): Known(
        "Disable Fsync", "Proton and Wine", "Turns off futex synchronisation, which fixes some games."
    ),
    (ENV, "PROTON_FORCE_LARGE_ADDRESS_AWARE"): Known(
        "Large Address Aware", "Proton and Wine", "Lets 32-bit games use up to 4 GB of memory."
    ),
    (ENV, "PROTON_HIDE_NVIDIA_GPU"): Known(
        "Hide NVIDIA Graphics Card", "NVIDIA and DLSS", "Reports the graphics card as AMD, for games that misbehave on NVIDIA."
    ),
    (ENV, "DXVK_HUD"): Known(
        "DXVK Overlay", "Display and HDR", "Shows DXVK's overlay; fps shows the frame rate.", "fps"
    ),
    (ENV, "DXVK_FRAME_RATE"): Known(
        "DXVK Frame Rate Limit", "Display and HDR", "Limits the frame rate of DirectX games running through DXVK.", "60"
    ),
    (ENV, "MANGOHUD"): Known(
        "MangoHud in Vulkan Games", "Display and HDR", "1 shows MangoHud in Vulkan games without the mangohud command."
    ),
    (ENV, "MANGOHUD_CONFIG"): Known(
        "MangoHud Settings", "Display and HDR", "MangoHud settings separated by commas.", "fps_limit=60"
    ),
    (ENV, "SteamDeck"): Known("Steam Deck Mode", "Other Variables", "Makes some games use their Steam Deck settings."),
    (WRAPPER, "game-performance"): Known(
        "Performance Power Profile", "Tools", "Switches to the performance power profile while the game runs (CachyOS).", ""
    ),
    (ENV, "PULSE_SINK"): Known("Audio Output", "Audio", "Sends the game's sound to this audio output.", ""),
    (ENV, "PRESSURE_VESSEL_IMPORT_OPENXR_1_RUNTIMES"): Known(
        "OpenXR Runtime", "VR", "Makes your OpenXR runtime, such as WiVRn, available inside Steam's container."
    ),
    (ENV, "PRESSURE_VESSEL_FILESYSTEMS_RW"): Known(
        "Container Folders", "VR", "Folders Steam's container may write to, such as your VR runtime's.", ""
    ),
}


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
        elif name in WRAPPERS:
            parsed.wrappers[name] = ""
        elif name in programs:
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


# Shown even when none of the user's games use them yet.
ALWAYS_OFFERED = [(WRAPPER, "gamemoderun"), (WRAPPER, "mangohud"), (WRAPPER, "gamescope"), (ENV, "PROTON_LOG")]


def baseline(all_options):
    """Every setting used in the given launch options, plus common and user-added ones.

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
    for kind, key in [*ALWAYS_OFFERED, *custom]:
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
