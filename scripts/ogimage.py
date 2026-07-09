#!/usr/bin/env python3
"""Generate the 1200x630 Open Graph share image (og.png) from data/kernels.json.

Builds a branded SVG card (same dark kernel-terminal identity as the site) and
rasterises it to PNG with ``rsvg-convert``. If that tool is unavailable the step
is skipped with a warning -- the HTML still references og.png, so just re-run
this once ``rsvg-convert`` (librsvg) is installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

W, H = 1200, 630
BG = "#0b0c0e"
INK = "#e7e9ec"
MUTE = "#9aa0aa"
FAINT = "#6b7280"
RUST = "#e4552e"
RUST_HI = "#f7a072"
GOLD = "#c9a227"      # vendored crates
GREEN = "#57b894"     # drivers
GREY = "#5b667a"      # everything else
BORDER = "#282c34"
FONT = "'DejaVu Sans Mono','Liberation Mono','Nimbus Mono',monospace"


def fi(n: int) -> str:
    return f"{n:,}"


def group(v: dict, name: str) -> int:
    return sum(c["code"] for c in v["categories"] if c["category"] == name)


def build_svg(data: dict) -> str:
    V = sorted(data["versions"], key=lambda v: [int(x) for x in v["series"].split(".")])
    if not V:
        raise SystemExit("ogimage: no versions in data")
    first, last = V[0], V[-1]
    # Anchor the growth multiple to the first release that ships Rust, so a
    # zero-Rust starting series (e.g. 6.0) doesn't yield a meaningless 0.0x.
    baseline = next((v for v in V if v["code"]), first)
    gcode = last["code"] / baseline["code"] if baseline["code"] else 0
    n = len(V)
    cloc = data.get("cloc_version", "cloc")

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="{FONT}">']
    p.append(f'<defs><radialGradient id="glow" cx="82%" cy="2%" r="72%">'
             f'<stop offset="0%" stop-color="{RUST}" stop-opacity="0.22"/>'
             f'<stop offset="60%" stop-color="{RUST}" stop-opacity="0"/>'
             f'</radialGradient></defs>')
    p.append(f'<rect width="{W}" height="{H}" fill="{BG}"/>')
    p.append(f'<rect width="{W}" height="{H}" fill="url(#glow)"/>')
    p.append(f'<rect x="0" y="0" width="{W}" height="6" fill="{RUST}"/>')
    p.append(f'<rect x="1" y="1" width="{W-2}" height="{H-2}" fill="none" '
             f'stroke="{BORDER}" stroke-width="1"/>')

    PAD = 72
    # eyebrow wordmark
    p.append(f'<text x="{PAD}" y="112" font-size="26" font-weight="700">'
             f'<tspan fill="{RUST}">~/</tspan><tspan fill="{INK}">rusted-kernel</tspan>'
             f'<tspan fill="{FAINT}">.com</tspan></text>')
    # title (two lines)
    p.append(f'<text x="{PAD}" y="230" font-size="82" font-weight="700" fill="{INK}">Rust in the</text>')
    p.append(f'<text x="{PAD}" y="322" font-size="82" font-weight="700" fill="{RUST}">Linux Kernel</text>')
    # subtitle
    p.append(f'<text x="{PAD}" y="372" font-size="24" fill="{MUTE}">'
             f'A version-by-version analysis of Rust in the mainline kernel tree</text>')
    # stat line (non-breaking spaces: SVG collapses/strips ordinary whitespace)
    sep = "    ·    "
    p.append(f'<text x="{PAD}" y="424" font-size="27" font-weight="700" xml:space="preserve">'
             f'<tspan fill="{RUST_HI}">{fi(last["files"])}</tspan>'
             f'<tspan fill="{MUTE}"> files</tspan>'
             f'<tspan fill="{FAINT}">{sep}</tspan>'
             f'<tspan fill="{RUST_HI}">{fi(last["code"])}</tspan>'
             f'<tspan fill="{MUTE}"> SLOC</tspan>'
             f'<tspan fill="{FAINT}">{sep}</tspan>'
             f'<tspan fill="{RUST_HI}">{gcode:.1f}×</tspan>'
             f'<tspan fill="{MUTE}"> since {baseline["series"]}</tspan></text>')

    # mini stacked bars (the signature growth viz)
    x0, x1, base_y, top_y = PAD, W - PAD, 560, 452
    maxh = base_y - top_y
    ymax = max((v["code"] for v in V), default=1) or 1
    slot = (x1 - x0) / n
    bw = slot * 0.6
    segs_def = [("Kernel crate", RUST), ("Vendored crates", GOLD), ("Drivers", GREEN)]
    for i, v in enumerate(V):
        cx = x0 + slot * (i + 0.5)
        bx = cx - bw / 2
        used = 0
        segs = []
        for name, col in segs_def:
            val = group(v, name)
            used += val
            segs.append((val, col))
        segs.append((max(0, v["code"] - used), GREY))
        yb = base_y
        for val, col in segs:
            if val <= 0:
                continue
            hh = maxh * val / ymax
            p.append(f'<rect x="{bx:.1f}" y="{yb-hh:.1f}" width="{bw:.1f}" '
                     f'height="{hh:.1f}" fill="{col}"/>')
            yb -= hh
        p.append(f'<text x="{cx:.1f}" y="{base_y+22:.0f}" text-anchor="middle" '
                 f'font-size="15" fill="{FAINT}">{v["series"]}</text>')

    # footer strip
    p.append(f'<line x1="{PAD}" y1="{H-56}" x2="{W-PAD}" y2="{H-56}" stroke="{BORDER}"/>')
    p.append(f'<text x="{PAD}" y="{H-22}" font-size="20" fill="{MUTE}">Part of '
             f'<tspan fill="{RUST_HI}" font-weight="700">DomainsProject.org</tspan></text>')
    p.append(f'<text x="{W-PAD}" y="{H-22}" text-anchor="end" font-size="18" fill="{FAINT}">'
             f'kernel.org  ·  {n} releases  ·  measured with cloc {cloc}</text>')
    p.append('</svg>')
    return "".join(p)


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    data = json.loads((repo / "data" / "kernels.json").read_text())
    svg = build_svg(data)
    png = repo / "og.png"
    if shutil.which("rsvg-convert") is None:
        print("warning: rsvg-convert (librsvg) not found; og.png NOT regenerated",
              file=sys.stderr)
        return 0
    proc = subprocess.run(
        ["rsvg-convert", "-w", str(W), "-h", str(H), "-o", str(png)],
        input=svg.encode(),
    )
    if proc.returncode != 0:
        print("warning: rsvg-convert failed; og.png NOT regenerated", file=sys.stderr)
        return 0
    print(f"[*] wrote {png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
