"""Assembles the website in _site: the pages here, the app's screenshots as WebP, and the icons."""

import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "_site")

shutil.rmtree(OUT, ignore_errors=True)
shutil.copytree(ROOT / "site", OUT, ignore=shutil.ignore_patterns("build.py", "DESIGN.md"))
images = OUT / "images"
images.mkdir()
for shot in (ROOT / "screenshots").glob("*.png"):
    Image.open(shot).save(images / f"{shot.stem}.webp", quality=82, method=6)
shutil.copy(ROOT / "data/icons/hicolor/scalable/apps/uk.co.solarflareit.Superlion.svg", images / "icon.svg")
shutil.copy(ROOT / "data/social-preview.png", images / "social-preview.png")
# Google Search Console checks this file at the site's root.
for verification in ROOT.glob("google*.html"):
    shutil.copy(verification, OUT)
(OUT / ".nojekyll").touch()
