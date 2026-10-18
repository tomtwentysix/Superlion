#!/bin/sh
# Builds the Superlion RPM into dist/. Run from anywhere: packaging/build-rpm.sh
set -eu

project=$(cd "$(dirname "$0")/.." && pwd)
version=$(sed -n 's/^Version:[[:space:]]*//p' "$project/packaging/superlion.spec")
work="$project/build"
top="$work/rpmbuild"

rm -rf "$work"
mkdir -p "$top/SOURCES" "$top/SPECS" "$project/dist" "$project/packaging/icons"

# PNG icons at the usual sizes, made from the 512 px original.
python3 - "$project" <<'PYTHON'
import sys
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
project = sys.argv[1]
source = GdkPixbuf.Pixbuf.new_from_file(f"{project}/data/icons/uk.co.solarflareit.Superlion-512.png")
for size in (16, 24, 32, 48, 64, 96, 128, 192, 256, 512):
    source.scale_simple(size, size, GdkPixbuf.InterpType.HYPER).savev(
        f"{project}/packaging/icons/{size}.png", "png", [], []
    )
PYTHON

# Source archive of the files the package needs, without caches.
stage="$work/superlion-$version"
mkdir -p "$stage"
cp -a "$project/superlion" "$project/data" "$project/packaging" "$project/README.md" "$project/LICENSE" "$stage/"
find "$stage" -name __pycache__ -type d -prune -exec rm -rf {} +
tar -C "$work" -czf "$top/SOURCES/superlion-$version.tar.gz" "superlion-$version"
cp "$project/packaging/superlion.spec" "$top/SPECS/"

rpmbuild --define "_topdir $top" -bb "$top/SPECS/superlion.spec"
cp "$top"/RPMS/noarch/superlion-*.rpm "$project/dist/"
rm -rf "$work"
ls -1 "$project"/dist/superlion-*.rpm
