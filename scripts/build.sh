#!/usr/bin/env bash
# Regenerate the rusted-kernel.com report end to end:
#   1. analyze.py  -> download/extract/cloc every kernel series -> data/kernels.json
#   2. render.py   -> data/kernels.json -> index.html
#
# Usage:
#   scripts/build.sh            # full run, all series >= 6.12
#   scripts/build.sh --only 6.12.95,7.1.3   # quick subset (passed to analyze.py)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(dirname "$here")"
cd "$repo"

for tool in python3 curl tar xz cloc; do
  command -v "$tool" >/dev/null 2>&1 || { echo "error: '$tool' not found in PATH" >&2; exit 1; }
done

export RK_BUILD_DATE="${RK_BUILD_DATE:-$(date -u +%Y-%m-%d)}"

echo "==> analyzing kernels"
python3 scripts/analyze.py "$@"

echo "==> rendering site"
python3 scripts/render.py

echo "==> generating Open Graph image"
python3 scripts/ogimage.py   # skips with a warning if rsvg-convert is absent

echo "==> done: index.html, sitemap.xml, robots.txt, og.png"
