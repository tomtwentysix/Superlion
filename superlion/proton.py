"""Custom Proton builds in Steam's compatibilitytools.d, installed from GitHub releases.

Proton builds carry a "version" file holding "<unix time> <release tag>", which is
how an installed build is matched to its source, whatever its folder is called.
"""

import hashlib
import shutil
import tarfile
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from . import vdf
from .steam_settings import COMPAT_PATH, config_vdf_path

RELEASES_URL = "https://api.github.com/repos/{}/releases"
TIMEOUT = 20
CHUNK = 1 << 20
RELEASES_SHOWN = 15
CACHE_SECONDS = 600
V3_FLAGS = {"avx2", "bmi1", "bmi2", "f16c", "fma", "movbe", "xsave"}


@dataclass(frozen=True)
class Source:
    name: str
    repo: str
    tag_prefix: str
    description: str
    variants: tuple = ("",)

    def archive_names(self, tag, variant):
        if self.repo == "GloriousEggroll/proton-ge-custom":
            return [f"{tag}-x86_64.tar.gz", f"{tag}.tar.gz"]  # Older releases have no architecture.
        return [f"proton-{tag}-{variant}.tar.xz"]

    def version(self, tag):
        """The tag as shown to the user, such as "GE-Proton11-11" or "Proton-CachyOS 11.0-20261014"."""
        if tag.startswith(self.name):
            return tag
        return f"{self.name} {tag.removeprefix(self.tag_prefix).removesuffix('-slr')}"

    def variant_of(self, folder_name):
        return next((v for v in self.variants if v and folder_name.endswith(v)), self.variants[-1])

    def default_variant(self):
        if "x86_64_v3" in self.variants and _cpu_has_v3():
            return "x86_64_v3"
        return self.variants[-1]


SOURCES = [
    Source(
        "GE-Proton", "GloriousEggroll/proton-ge-custom", "GE-Proton",
        "Valve's Proton with extra fixes and media codecs, by GloriousEggroll",
    ),
    Source(
        "Proton-CachyOS", "CachyOS/proton-cachyos", "cachyos-",
        "Proton tuned for performance, with fixes from the CachyOS project",
        variants=("x86_64_v3", "x86_64"),
    ),
]


@dataclass
class Release:
    tag: str
    published: str  # ISO 8601
    assets: dict  # name: {"url", "size", "digest"}

    def archive(self, source, variant):
        return next((self.assets[n] | {"name": n} for n in source.archive_names(self.tag, variant)
                     if n in self.assets), None)


@dataclass
class Build:
    path: Path
    name: str  # Internal name written to CompatToolMapping.
    label: str
    tag: str  # "" when the folder has no version file, as with SteamTinkerLaunch.
    source: Source | None
    variant: str

    @property
    def rolling(self):
        """Whether the folder keeps one name across versions, as ProtonPlus's "Latest" builds do."""
        return bool(self.tag) and self.tag not in self.path.name


class Cancelled(Exception):
    pass


def _cpu_has_v3():
    try:
        text = Path("/proc/cpuinfo").read_text()
    except OSError:
        return False
    line = next((l for l in text.splitlines() if l.startswith("flags")), "")
    return V3_FLAGS <= set(line.split())


def tools_dir(config):
    return config.root / "compatibilitytools.d"


def source_for(tag):
    return next((s for s in SOURCES if tag.startswith(s.tag_prefix)), None)


def installed(config):
    builds = []
    for manifest in sorted(tools_dir(config).glob("*/compatibilitytool.vdf")):
        folder = manifest.parent
        try:
            entries = vdf.get_path(vdf.load(manifest), "compatibilitytools", "compat_tools") or {}
        except (OSError, ValueError):
            continue
        name, info = next(iter(entries.items()), (folder.name, {}))
        try:
            tag = (folder / "version").read_text().split()[-1]
        except (OSError, IndexError):
            tag = ""
        source = source_for(tag)
        variant = source.variant_of(folder.name) if source else ""
        label = info.get("display_name", name) if isinstance(info, dict) else name
        builds.append(Build(folder, name, label, tag, source, variant))
    return builds


_cache = {}
_cache_lock = threading.Lock()


def releases(source):
    """The newest releases first. Cached for a while, as GitHub allows 60 requests an hour."""
    with _cache_lock:
        cached = _cache.get(source.repo)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            return cached[1]
    response = requests.get(
        RELEASES_URL.format(source.repo), params={"per_page": RELEASES_SHOWN + 5},
        headers={"Accept": "application/vnd.github+json"}, timeout=TIMEOUT,
    )
    response.raise_for_status()
    found = [
        Release(
            item["tag_name"], item.get("published_at") or "",
            {a["name"]: {"url": a["browser_download_url"], "size": a.get("size", 0), "digest": a.get("digest")}
             for a in item.get("assets", [])},
        )
        for item in response.json()
        if not item.get("draft") and not item.get("prerelease")
    ][:RELEASES_SHOWN]
    with _cache_lock:
        _cache[source.repo] = (time.monotonic(), found)
    return found


def update_for(build, builds, found):
    """The release that updates build, or None.

    A rolling build updates in place. Versioned builds are left alone, so games set to
    them keep working, and only the newest one of each kind offers the new release.
    """
    if not build.source or not found or build.tag == found[0].tag:
        return None
    if not found[0].archive(build.source, build.variant):
        return None
    if build.rolling:
        return found[0]
    order = {r.tag: i for i, r in enumerate(found)}
    siblings = [b for b in builds if b.source == build.source and b.variant == build.variant and not b.rolling]
    if any(b.tag == found[0].tag for b in siblings):
        return None
    newest = min(siblings, key=lambda b: order.get(b.tag, len(order)))
    return found[0] if newest is build else None


def _expected_checksum(release, archive):
    """("sha512" or "sha256", hex digest) from the published .sha512sum, else GitHub's digest."""
    stem = archive["name"].removesuffix(".tar.gz").removesuffix(".tar.xz")
    sums = release.assets.get(f"{stem}.sha512sum")
    if sums:
        response = requests.get(sums["url"], timeout=TIMEOUT)
        response.raise_for_status()
        return "sha512", response.text.split()[0].lower()
    if archive.get("digest") and ":" in archive["digest"]:
        algorithm, value = archive["digest"].split(":", 1)
        return algorithm, value.lower()
    raise ValueError("The release has no published checksum")


def install(config, source, release, variant, progress, cancelled, replace=None):
    """Download, check and unpack a release into compatibilitytools.d.

    progress(stage, fraction) is called from this thread with stage "download",
    "check" or "unpack". replace is a rolling Build whose files are swapped for the
    new ones, keeping its folder and manifest so games set to it keep using it.
    Returns the installed folder.
    """
    archive = release.archive(source, variant)
    if archive is None:
        raise ValueError(f"{release.tag} has no build for this computer")
    base = tools_dir(config)
    base.mkdir(parents=True, exist_ok=True)
    algorithm, expected = _expected_checksum(release, archive)
    with tempfile.TemporaryDirectory(dir=base, prefix=".superlion-") as work:
        work = Path(work)
        download = work / archive["name"]
        digest = hashlib.new(algorithm)
        with requests.get(archive["url"], stream=True, timeout=TIMEOUT) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or archive["size"] or 0)
            done = 0
            with open(download, "wb") as fh:
                for chunk in response.iter_content(CHUNK):
                    if cancelled():
                        raise Cancelled()
                    fh.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    progress("download", done / total if total else 0.0)
        progress("check", 1.0)
        if digest.hexdigest() != expected:
            raise ValueError("The download did not match its published checksum")
        progress("unpack", 0.0)
        unpacked = work / "unpacked"
        with tarfile.open(download) as tar:
            tar.extractall(unpacked, filter="data")
        download.unlink()
        folders = [p for p in unpacked.iterdir() if p.is_dir()]
        if len(folders) != 1 or not (folders[0] / "compatibilitytool.vdf").is_file():
            raise ValueError("The download is not a Proton build")
        new = folders[0]
        if cancelled():
            raise Cancelled()
        if replace is None:
            target = base / new.name
            if target.exists():
                raise FileExistsError(f"{new.name} is already installed")
            new.rename(target)
            return target
        shutil.copy2(replace.path / "compatibilitytool.vdf", new / "compatibilitytool.vdf")
        old = work / "old"
        replace.path.rename(old)
        new.rename(replace.path)
        return replace.path


def remove(build):
    shutil.rmtree(build.path)


def games_using(config, build):
    """App IDs that Steam is set to run with build."""
    try:
        mapping = vdf.get_path(vdf.load(config_vdf_path(config.steam_root)), *COMPAT_PATH) or {}
    except (OSError, ValueError):
        return []
    return [int(a) for a, e in mapping.items()
            if a.isdigit() and int(a) and isinstance(e, dict) and e.get("name") == build.name]
