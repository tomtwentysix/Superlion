#!/bin/sh
# Runs Superlion from this checkout as a separate app, with its own settings,
# keys and cache, so the installed copy is left alone.
cd "$(dirname "$0")" && SUPERLION_DEVEL=1 exec python3 -m superlion "$@"
