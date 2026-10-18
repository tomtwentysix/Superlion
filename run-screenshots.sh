#!/bin/sh
# Runs the development copy for taking screenshots: edits such as removing
# collections show in the app, but nothing is ever written to Steam.
cd "$(dirname "$0")" && SUPERLION_DEVEL=1 SUPERLION_SCREENSHOTS=1 exec python3 -m superlion "$@"
