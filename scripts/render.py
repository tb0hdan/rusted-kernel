#!/usr/bin/env python3
"""Render the branded rusted-kernel.com report from data/kernels.json.

Produces a single self-contained ``index.html`` (inline CSS + inline SVG
charts, no external assets, no JavaScript) in the repository root.  Theme:
dark "kernel terminal" -- near-black canvas, Rust-orange accent, monospace
display type.
"""

from __future__ import annotations

import base64
import html
import json
import math
from pathlib import Path

# Inline SVG favicon (terminal ">" prompt + cursor, Rust orange) so the page is
# fully self-contained and emits no favicon 404.
_FAV_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    "<rect width='32' height='32' rx='6' fill='#0b0c0e'/>"
    "<rect x='3.5' y='3.5' width='25' height='25' rx='4' fill='none' stroke='#e4552e' stroke-width='2'/>"
    "<path d='M8 11 L13 16 L8 21' fill='none' stroke='#e4552e' stroke-width='2.6' "
    "stroke-linecap='round' stroke-linejoin='round'/>"
    "<rect x='15' y='19' width='9' height='2.8' fill='#e4552e'/></svg>"
)
FAVICON = "data:image/svg+xml;base64," + base64.b64encode(_FAV_SVG.encode()).decode()

# --- palette ---------------------------------------------------------------
BG = "#0b0c0e"
PANEL = "#15171c"
PANEL2 = "#1b1e24"
BORDER = "#282c34"
INK = "#e7e9ec"
MUTE = "#9aa0aa"
FAINT = "#6b7280"
RUST = "#e4552e"       # primary accent (Rust orange)
RUST_HI = "#f7a072"    # lighter accent

# --- branding / outbound links --------------------------------------------
SITE = "rusted-kernel.com"
SITE_URL = "https://rusted-kernel.com"
REPO_URL = "https://github.com/tb0hdan/rusted-kernel"
KERNEL_RUST_DOCS = "https://docs.kernel.org/rust/index.html"
CLOC_URL = "https://github.com/aldanial/cloc"
DP_URL = "https://domainsproject.org"
DP_NAME = "DomainsProject.org"

GH_ICON = (
    '<svg class="gh" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 0C3.58 0 0 '
    '3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49'
    '-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63'
    '-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64'
    '-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82'
    '.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 '
    '1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 '
    '1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58'
    '-8-8-8z"></path></svg>'
)


def wordmark_svg(x: float, y: float, anchor: str = "start", size: float = 13.0) -> str:
    """A `~/rusted-kernel.com` terminal-prompt wordmark as SVG <text>."""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" class="wm" '
        f'style="font-size:{size}px">'
        f'<tspan fill="{RUST}">~/</tspan>'
        f'<tspan fill="{INK}">rusted-kernel</tspan>'
        f'<tspan fill="{FAINT}">.com</tspan></text>'
    )

# Categorical palette for stacked chart / legend. "Kernel crate" gets the
# hero Rust orange; the rest are muted-but-distinct hues that read on black.
CAT_ORDER = [
    ("Kernel crate", RUST),
    ("Drivers", "#57b894"),
    ("Vendored crates", "#c9a227"),
    ("Procedural macros", "#c792ea"),
    ("Generated bindings", "#5aa9e6"),
    ("UAPI bindings", "#3fc8e6"),
    ("pin-init crate", "#f2c14e"),
    ("Core runtime & shims", "#e08ba8"),
    ("Samples & examples", "#9aa0a6"),
    ("Kernel build tooling", "#b08968"),
    ("Tooling & tests", "#8fa3ad"),
    ("io_uring", "#7f8cff"),
    ("Core kernel", "#d98c5f"),
    ("Library code", "#7bb0a8"),
    ("Other subsystems", "#5b667a"),
]
CAT_COLOR = dict(CAT_ORDER)

# The two "crate" blocks that dominate the SLOC totals — the first-party
# rust/kernel abstraction crate and the third-party vendored crates
# (syn/quote/proc-macro2, formerly rust/alloc). The companion chart drops both
# so the remaining categories become legible.
CRATE_CATEGORIES = {"Kernel crate", "Vendored crates"}


def color_for(cat: str) -> str:
    return CAT_COLOR.get(cat, "#5b667a")


# Editorial annotations surfaced inside a version's folded detail block, keyed by
# series. For anomalies the raw numbers alone would misrepresent. Trusted static
# HTML (rendered verbatim); keep identifiers in <span class="mono">…</span>.
VERSION_NOTES: dict[str, str] = {
    "6.10": (
        '<b>Why totals fall here — a one-time cleanup, not a retreat from Rust.</b> '
        '6.10 removed the in-tree <span class="mono">rust/alloc</span> fork: the '
        "kernel's private copy of Rust's standard <span class=\"mono\">alloc</span> "
        'library (<span class="mono">Vec</span>, <span class="mono">Box</span>, '
        '<span class="mono">slice</span>, <span class="mono">raw_vec</span>, …) — '
        '~4,360 SLOC across 14 files, counted here under <b>Vendored crates</b> — '
        'and replaced it with thin allocator abstractions in '
        '<span class="mono">rust/kernel/alloc/</span> '
        '(<span class="mono">box_ext</span>, <span class="mono">vec_ext</span>). '
        'First-party kernel Rust kept growing straight through the drop: the '
        'Kernel crate went 3,812 → 4,057 → 4,845 SLOC across 6.9 → 6.10 → 6.11. '
        'Only the vendored standard-library copy went away, so the total fell even '
        "as the kernel's own Rust expanded."
    ),
    "6.19": (
        'Total Rust '
        'leaps from 36,225 SLOC (6.18) to 89,336 — but almost all of that is '
        '<b>vendored crates</b>: third-party libraries from the Rust ecosystem '
        '(crates.io) copied verbatim into <span class="mono">rust/</span>, because '
        "the kernel build is self-contained and can't fetch dependencies over the "
        'network. In 6.19 the standard procedural-macro toolchain was vendored in '
        'one go — <span class="mono">syn</span> (41,716 SLOC, a full Rust-source '
        'parser), <span class="mono">proc-macro2</span> (3,782) and '
        '<span class="mono">quote</span> (1,460): 46,958 SLOC across 75 files — so '
        "the kernel's own macros (<span class=\"mono\">rust/macros/</span>) can lean "
        'on them instead of hand-rolled parsing. This is external tooling, not '
        'kernel logic: set it aside and first-party kernel Rust grew steadily, '
        '36,225 → 42,378 SLOC (6.18 → 6.19). The hero chart breaks it out as its own '
        '"Vendored crates" band for exactly this reason.'
    ),
}


# --- formatting ------------------------------------------------------------
def fi(n: int) -> str:
    return f"{n:,}"


def mabbr(n: int) -> str:
    """Compact SLOC count, e.g. 30101072 -> '30.1M', 4877 -> '4.9k'."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return f"{n:,}"


def share_pct(part: int, whole: int, decimals: int = 2) -> str:
    """Rust share as a percentage string; '—' when the total is unavailable."""
    return f"{100 * part / whole:.{decimals}f}%" if whole else "—"


def human_bytes(n: int) -> str:
    f = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if f < 1024 or unit == "GiB":
            return f"{f:.0f} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} GiB"


def e(s: str) -> str:
    return html.escape(str(s))


# --- SVG chart builders ----------------------------------------------------
def stacked_bars(versions: list[dict], title: str, source: str, note: str,
                 exclude: set[str] | None = None) -> str:
    """Stacked bar chart: Rust SLOC by category, one bar per version.

    ``exclude`` drops the named categories entirely (bars, totals and y-scale),
    so a companion chart can suppress a dominating block and let the rest of the
    categories become legible.

    Self-branding: carries a title + source caption at the top and a
    ``~/rusted-kernel.com`` wordmark + methodology note at the bottom, so the
    chart reads as a standalone artefact when shared.
    """
    exclude = exclude or set()
    W, H = 960, 500
    ml, mr, mt, mb = 64, 22, 66, 96
    plot_w = W - ml - mr
    plot_h = H - mt - mb
    n = len(versions)
    if n == 0:
        return ""

    # Per-version category -> code map, only categories present anywhere.
    present: list[str] = []
    for cat, _ in CAT_ORDER:
        if cat in exclude:
            continue
        if any(any(c["category"] == cat for c in v["categories"]) for v in versions):
            present.append(cat)

    def code_of(v, cat):
        return sum(c["code"] for c in v["categories"] if c["category"] == cat)

    totals = [sum(code_of(v, cat) for cat in present) for v in versions]
    ymax = max(totals) if totals else 1
    # round up to a "nice" number
    step = 10 ** (len(str(ymax)) - 1)
    ymax_r = ((ymax // step) + 1) * step

    gap = plot_w / n
    bw = min(gap * 0.62, 64)

    def x_center(i):
        return ml + gap * (i + 0.5)

    def y(val):
        return mt + plot_h * (1 - val / ymax_r)

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="Stacked bar chart of Rust source lines by category across kernel versions" '
             f'preserveAspectRatio="xMidYMid meet" class="chart">']

    # top branding: title + source caption
    parts.append(f'<text x="{ml-46}" y="26" class="ctitle">{e(title)}</text>')
    parts.append(f'<text x="{ml-46}" y="46" class="csrc">{e(source)}</text>')

    # y gridlines + labels
    ticks = 4
    for t in range(ticks + 1):
        val = ymax_r * t / ticks
        yy = y(val)
        parts.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{W-mr}" y2="{yy:.1f}" '
                     f'stroke="{BORDER}" stroke-width="1"/>')
        parts.append(f'<text x="{ml-10}" y="{yy+4:.1f}" text-anchor="end" '
                     f'class="axis">{fi(int(val))}</text>')

    # bars
    for i, v in enumerate(versions):
        cx = x_center(i)
        x0 = cx - bw / 2
        acc = 0
        for cat in present:
            val = code_of(v, cat)
            if val <= 0:
                continue
            y_top = y(acc + val)
            y_bot = y(acc)
            parts.append(
                f'<rect x="{x0:.1f}" y="{y_top:.1f}" width="{bw:.1f}" '
                f'height="{max(0.0, y_bot-y_top):.1f}" fill="{color_for(cat)}">'
                f'<title>{e(v["version"])} — {e(cat)}: {fi(val)} SLOC</title></rect>'
            )
            acc += val
        # total label above bar
        parts.append(f'<text x="{cx:.1f}" y="{y(acc)-8:.1f}" text-anchor="middle" '
                     f'class="bartot">{fi(acc)}</text>')
        # x label (series)
        parts.append(f'<text x="{cx:.1f}" y="{H-mb+22:.1f}" text-anchor="middle" '
                     f'class="axis strong">{e(v["series"])}</text>')

    # bottom branding band: divider + wordmark + methodology note
    parts.append(f'<line x1="{ml-46}" y1="{H-42}" x2="{W-mr}" y2="{H-42}" '
                 f'stroke="{BORDER}" stroke-width="1"/>')
    parts.append(wordmark_svg(ml - 46, H - 16, "start", 15))
    parts.append(f'<text x="{W-mr}" y="{H-17:.0f}" text-anchor="end" '
                 f'class="cnote">{e(note)}</text>')
    parts.append('</svg>')
    return "".join(parts)


def line_chart(versions: list[dict], key: str, label: str, color: str) -> str:
    """Simple single-series line+area chart across versions."""
    W, H = 460, 240
    ml, mr, mt, mb = 52, 14, 22, 40
    plot_w = W - ml - mr
    plot_h = H - mt - mb
    n = len(versions)
    if n == 0:
        return ""
    vals = [v[key] for v in versions]
    ymax = max(vals) or 1
    step = 10 ** (len(str(ymax)) - 1)
    ymax_r = ((ymax // step) + 1) * step
    gap = plot_w / max(1, n - 1) if n > 1 else plot_w

    def X(i):
        return ml + (gap * i if n > 1 else plot_w / 2)

    def Y(val):
        return mt + plot_h * (1 - val / ymax_r)

    pts = [(X(i), Y(vals[i])) for i in range(n)]
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="{e(label)} across kernel versions" '
             f'preserveAspectRatio="xMidYMid meet" class="chart">']
    # subtle brand mark, top-right corner
    parts.append(wordmark_svg(W - mr, 12, "end", 10.5))
    ticks = 3
    for t in range(ticks + 1):
        val = ymax_r * t / ticks
        yy = Y(val)
        parts.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{W-mr}" y2="{yy:.1f}" '
                     f'stroke="{BORDER}" stroke-width="1"/>')
        lab = fi(int(val)) if val < 1000 else f"{val/1000:.0f}k"
        parts.append(f'<text x="{ml-8}" y="{yy+4:.1f}" text-anchor="end" '
                     f'class="axis">{lab}</text>')
    # area
    area = f'M {pts[0][0]:.1f} {Y(0):.1f} ' + \
        " ".join(f'L {x:.1f} {y:.1f}' for x, y in pts) + \
        f' L {pts[-1][0]:.1f} {Y(0):.1f} Z'
    parts.append(f'<path d="{area}" fill="{color}" fill-opacity="0.14"/>')
    # line
    line = "M " + " L ".join(f'{x:.1f} {y:.1f}' for x, y in pts)
    parts.append(f'<path d="{line}" fill="none" stroke="{color}" stroke-width="2.5"/>')
    for i, (x, y) in enumerate(pts):
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}">'
                     f'<title>{e(versions[i]["version"])}: {fi(vals[i])} {e(label)}</title></circle>')
        # 22 series labels are too dense to sit horizontally, so render them
        # vertically (rotated 90deg, reading bottom-to-top) in the bottom margin.
        ly = H - mb / 2
        parts.append(f'<text x="{x:.1f}" y="{ly:.1f}" text-anchor="middle" '
                     f'dominant-baseline="central" '
                     f'transform="rotate(-90 {x:.1f} {ly:.1f})" '
                     f'class="axis small">{e(versions[i]["series"])}</text>')
    parts.append('</svg>')
    return "".join(parts)


def share_line_chart(versions: list[dict]) -> str:
    """Rust as a % of total kernel SLOC, across versions.

    Only versions that carry a whole-tree measurement (kernel_code > 0) are
    plotted; a zero-Rust release like 6.0 still contributes a real 0.00% point,
    which is the point of the chart — the share climbs from literally nothing.
    """
    pts_data = [(v, 100 * v["code"] / v["kernel_code"])
                for v in versions if v.get("kernel_code")]
    n = len(pts_data)
    if n == 0:
        return ""
    W, H = 460, 240
    ml, mr, mt, mb = 52, 14, 22, 40
    plot_w, plot_h = W - ml - mr, H - mt - mb
    shares = [s for _, s in pts_data]
    smax = max(shares) or 1
    # "nice" ceiling rounded up to the next 0.05 so the tiny values have headroom.
    ymax_r = max(0.05, math.ceil(smax * 20) / 20)
    gap = plot_w / max(1, n - 1) if n > 1 else plot_w

    def X(i):
        return ml + (gap * i if n > 1 else plot_w / 2)

    def Y(val):
        return mt + plot_h * (1 - val / ymax_r)

    pts = [(X(i), Y(shares[i])) for i in range(n)]
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="Rust share of total kernel SLOC across versions" '
             f'preserveAspectRatio="xMidYMid meet" class="chart">']
    parts.append(wordmark_svg(W - mr, 12, "end", 10.5))
    ticks = 3
    for t in range(ticks + 1):
        val = ymax_r * t / ticks
        yy = Y(val)
        parts.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{W-mr}" y2="{yy:.1f}" '
                     f'stroke="{BORDER}" stroke-width="1"/>')
        parts.append(f'<text x="{ml-8}" y="{yy+4:.1f}" text-anchor="end" '
                     f'class="axis">{val:.2f}%</text>')
    area = f'M {pts[0][0]:.1f} {Y(0):.1f} ' + \
        " ".join(f'L {x:.1f} {y:.1f}' for x, y in pts) + \
        f' L {pts[-1][0]:.1f} {Y(0):.1f} Z'
    parts.append(f'<path d="{area}" fill="{RUST}" fill-opacity="0.16"/>')
    line = "M " + " L ".join(f'{x:.1f} {y:.1f}' for x, y in pts)
    parts.append(f'<path d="{line}" fill="none" stroke="{RUST}" stroke-width="2.5"/>')
    for i, (x, y) in enumerate(pts):
        v = pts_data[i][0]
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{RUST}">'
                     f'<title>{e(v["version"])}: {shares[i]:.3f}% of kernel SLOC</title></circle>')
        ly = H - mb / 2
        parts.append(f'<text x="{x:.1f}" y="{ly:.1f}" text-anchor="middle" '
                     f'dominant-baseline="central" '
                     f'transform="rotate(-90 {x:.1f} {ly:.1f})" '
                     f'class="axis small">{e(v["series"])}</text>')
    parts.append('</svg>')
    return "".join(parts)


def composition_bar(buckets: list[tuple], total: int) -> str:
    """True-scale 100% stacked bar of kernel SLOC by language bucket.

    ``buckets`` is an ordered list of ``(name, code, color)``; the ``Rust``
    bucket is drawn true-to-scale (a bright hairline at ~0.3%) and given a
    leader-line callout so it can be found without distorting any proportion.
    """
    if not total:
        return ""
    W, H = 1000, 118
    bx, bw = 0, W
    by, bh = 52, 46
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="Kernel SLOC composition by language" '
             f'preserveAspectRatio="xMidYMid meet" class="compbar">']
    x = float(bx)
    for name, code, color in buckets:
        w = bw * code / total
        share = 100 * code / total
        parts.append(
            f'<rect x="{x:.2f}" y="{by}" width="{max(w,0.4):.2f}" height="{bh}" '
            f'fill="{color}"><title>{e(name)}: {fi(code)} SLOC ({share:.2f}%)</title></rect>')
        # inline label only where the segment is wide enough to hold text
        if w > 130:
            parts.append(
                f'<text x="{x + w/2:.1f}" y="{by + bh/2 - 3:.1f}" text-anchor="middle" '
                f'class="complab">{e(name)}</text>'
                f'<text x="{x + w/2:.1f}" y="{by + bh/2 + 13:.1f}" text-anchor="middle" '
                f'class="compsub">{share:.1f}%</text>')
        if name == "Rust":
            cx = x + w / 2
            # Rust is the rightmost (tiny) segment, so a centred label would clip
            # the edge — anchor the callout to whichever side keeps it on-canvas.
            if cx > W * 0.6:
                anchor, lx = "end", W - 2
            elif cx < W * 0.4:
                anchor, lx = "start", 2
            else:
                anchor, lx = "middle", cx
            parts.append(
                f'<line x1="{cx:.2f}" y1="{by-4:.1f}" x2="{cx:.2f}" y2="28" '
                f'stroke="{RUST}" stroke-width="1.5"/>'
                f'<circle cx="{cx:.2f}" cy="{by-4:.1f}" r="2.6" fill="{RUST}"/>'
                f'<text x="{lx:.1f}" y="20" text-anchor="{anchor}" '
                f'class="callout">Rust · {share:.2f}%</text>')
        x += w
    parts.append('</svg>')
    return "".join(parts)


def cat_bar_row(cat: dict, maxcode: int) -> str:
    pct = (cat["code"] / maxcode * 100) if maxcode else 0
    col = color_for(cat["category"])
    return (
        '<tr>'
        f'<td class="catname"><span class="dot" style="background:{col}"></span>{e(cat["category"])}</td>'
        f'<td class="purpose">{e(cat["purpose"])}</td>'
        f'<td class="num">{fi(cat["files"])}</td>'
        f'<td class="num">{human_bytes(cat["bytes"])}</td>'
        f'<td class="num">{fi(cat["code"])}</td>'
        f'<td class="barcell"><span class="bar" style="width:{pct:.1f}%;background:{col}"></span></td>'
        '</tr>'
    )


# --- CSS -------------------------------------------------------------------
CSS = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:__BG__;color:__INK__;
  font:15px/1.65 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  background-image:
    radial-gradient(1200px 600px at 80% -10%, rgba(228,85,46,0.10), transparent 60%),
    linear-gradient(rgba(255,255,255,0.015) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.015) 1px, transparent 1px);
  background-size:auto, 44px 44px, 44px 44px;}
.mono{font-family:ui-monospace,"SF Mono","JetBrains Mono","Cascadia Code",Menlo,Consolas,monospace}
a{color:__RUST_HI__;text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1040px;margin:0 auto;padding:0 22px}
header.hero{padding:64px 0 40px;border-bottom:1px solid __BORDER__}
.eyebrow{font-family:ui-monospace,Menlo,Consolas,monospace;letter-spacing:.28em;
  text-transform:uppercase;color:__RUST__;font-size:12px;margin:0 0 18px}
.eyebrow .cursor{display:inline-block;width:9px;height:15px;background:__RUST__;
  margin-left:4px;transform:translateY(2px);animation:blink 1.15s steps(1) infinite}
@keyframes blink{50%{opacity:0}}
h1{font-family:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
  font-size:clamp(30px,6vw,58px);line-height:1.02;margin:0 0 18px;font-weight:700;letter-spacing:-.01em}
h1 .accent{color:__RUST__}
h1 .h1link,h1 .h1link:hover{color:inherit;text-decoration:none}
h1 .h1link:hover .accent{color:__RUST_HI__}
.lede{font-size:clamp(16px,2.2vw,20px);color:__MUTE__;max-width:70ch;margin:0 0 8px}
.meta{margin-top:22px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;color:__FAINT__}
.meta b{color:__MUTE__;font-weight:600}
.headline{margin-top:30px;display:flex;flex-wrap:wrap;gap:14px;align-items:baseline}
.headline .big{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:clamp(28px,5vw,46px);
  color:__INK__;font-weight:700}
.headline .arrow{color:__RUST__;font-size:clamp(24px,4vw,38px)}
.headline .mult{color:__RUST_HI__;font-weight:700}

section{padding:46px 0;border-bottom:1px solid __BORDER__}
h2{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;letter-spacing:.22em;
  text-transform:uppercase;color:__MUTE__;margin:0 0 6px}
h2::before{content:"// ";color:__RUST__}
.subhead{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;letter-spacing:.16em;
  text-transform:uppercase;color:__INK__;margin:34px 0 6px}
.subhead::before{content:"└ ";color:__RUST__}
.sectlede{color:__MUTE__;margin:0 0 26px;max-width:74ch}

.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px}
.card{background:__PANEL__;border:1px solid __BORDER__;border-radius:10px;padding:18px 18px 16px}
.card .k{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11.5px;letter-spacing:.12em;
  text-transform:uppercase;color:__FAINT__;margin:0 0 8px}
.card .v{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:30px;font-weight:700;color:__INK__;line-height:1}
.card .s{font-size:12.5px;color:__MUTE__;margin-top:7px}
.card .v .u{font-size:15px;color:__MUTE__;font-weight:600}

.chartwrap{background:__PANEL__;border:1px solid __BORDER__;border-radius:12px;padding:20px 18px 12px;overflow-x:auto}
.chart{width:100%;height:auto;min-width:520px;display:block}
.chart .axis{fill:__FAINT__;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px}
.chart .axis.small{font-size:10px}
.chart .axis.strong{fill:__MUTE__;font-size:12px}
.chart .bartot{fill:__MUTE__;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:10.5px}
.chart text{font-family:ui-monospace,Menlo,Consolas,monospace}
.chart .ctitle{fill:__INK__;font-size:14px;font-weight:700;letter-spacing:.16em}
.chart .csrc{fill:__FAINT__;font-size:11.5px;letter-spacing:.02em}
.chart .csrc .src-accent{fill:__RUST__}
.chart .cnote{fill:__FAINT__;font-size:10.5px}
.chart .wm{font-weight:700}
.smallcharts{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}
.smallcharts .chart{min-width:0}
.smallcharts .chartwrap .cap{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;
  letter-spacing:.1em;text-transform:uppercase;color:__FAINT__;margin:2px 4px 8px}
@media(max-width:720px){.smallcharts{grid-template-columns:1fr}}

.legend{display:flex;flex-wrap:wrap;gap:8px 10px;margin:16px 2px 0}
.legend .item{display:flex;align-items:center;gap:7px;font-family:ui-monospace,Menlo,Consolas,monospace;
  font-size:11.5px;color:__MUTE__;background:__PANEL2__;border:1px solid __BORDER__;
  border-radius:20px;padding:4px 11px 4px 9px}
.dot{display:inline-block;width:11px;height:11px;border-radius:3px;flex:none}

/* Rust's share of the kernel */
.sharetop{display:grid;grid-template-columns:minmax(210px,320px) 1fr;gap:16px;
  align-items:stretch;margin-bottom:16px}
@media(max-width:720px){.sharetop{grid-template-columns:1fr}}
.bigshare{background:__PANEL__;border:1px solid __BORDER__;border-radius:12px;
  padding:24px 22px;display:flex;flex-direction:column;justify-content:center}
.bigshare .pct{font-family:ui-monospace,Menlo,Consolas,monospace;
  font-size:clamp(42px,8vw,66px);font-weight:700;color:__RUST__;line-height:1}
.bigshare .ofwhat{color:__INK__;margin-top:12px;font-size:14px;max-width:32ch}
.bigshare .ofwhat b{color:__RUST_HI__;font-weight:700}
.bigshare .caveat{color:__MUTE__;margin-top:10px;font-size:12.5px;max-width:34ch}
.compwrap .compbar{width:100%;height:auto;display:block;min-width:520px}
.compbar text{font-family:ui-monospace,Menlo,Consolas,monospace}
.compbar .complab{fill:#fff;font-size:15px;font-weight:700;letter-spacing:.02em}
.compbar .compsub{fill:rgba(255,255,255,.8);font-size:12px}
.compbar .callout{fill:__RUST__;font-size:15px;font-weight:700}

table{width:100%;border-collapse:collapse;font-size:13.5px}
.scroll{overflow-x:auto}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid __BORDER__;white-space:nowrap}
th{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;letter-spacing:.1em;
  text-transform:uppercase;color:__FAINT__;font-weight:600}
td.num,th.num{text-align:right;font-family:ui-monospace,Menlo,Consolas,monospace}
tbody tr:hover{background:__PANEL2__}
.delta-pos{color:__RUST_HI__}
.catname{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px}
.catname .dot{margin-right:9px;vertical-align:baseline}
.purpose{color:__MUTE__;white-space:normal;font-size:12.5px}
.barcell{width:180px}
.bar{display:block;height:9px;border-radius:5px;min-width:2px}

details{background:__PANEL__;border:1px solid __BORDER__;border-radius:10px;margin-bottom:10px}
summary{cursor:pointer;padding:14px 16px;list-style:none;display:flex;flex-wrap:wrap;
  align-items:baseline;gap:12px;font-family:ui-monospace,Menlo,Consolas,monospace}
summary::-webkit-details-marker{display:none}
summary::before{content:"▸";color:__RUST__;margin-right:2px}
details[open] summary::before{content:"▾"}
summary .ver{font-size:16px;font-weight:700;color:__INK__}
summary .sstat{font-size:12.5px;color:__MUTE__}
summary .sstat b{color:__RUST_HI__}
details .body{padding:4px 16px 16px}
.vnote{background:__PANEL2__;border:1px solid __BORDER__;border-left:3px solid __RUST__;
  border-radius:8px;padding:11px 14px;margin:2px 0 16px;color:__MUTE__;font-size:13px;line-height:1.62}
.vnote b{color:__INK__}
.vnote .mono{color:__RUST_HI__}

.glossary{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.gitem{background:__PANEL__;border:1px solid __BORDER__;border-radius:10px;padding:14px 15px}
.gitem .h{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;color:__INK__;
  display:flex;align-items:center;gap:8px;margin-bottom:5px}
.gitem .p{font-size:12.5px;color:__MUTE__;margin:0}

code{background:__PANEL2__;border:1px solid __BORDER__;border-radius:5px;padding:1px 6px;
  font-family:ui-monospace,Menlo,Consolas,monospace;color:__MUTE__;font-size:.92em}
.method{color:__MUTE__;max-width:80ch;margin:0}

footer{padding:40px 0 70px;color:__FAINT__;font-size:12.5px}

.brandfoot{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:16px;
  padding:6px 0}
.brandfoot .bfleft{display:flex;flex-wrap:wrap;align-items:baseline;gap:12px}
.brandfoot .fdate{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;color:__FAINT__}
.brandfoot .mark{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:19px;font-weight:700;color:__INK__}
.brandfoot .mark .p{color:__RUST__}
.brandfoot .mark .tld{color:__FAINT__}
.brandfoot .flinks{display:flex;flex-wrap:wrap;gap:8px}
.brandfoot .flinks a{display:inline-flex;align-items:center;gap:7px;font-family:ui-monospace,Menlo,Consolas,monospace;
  font-size:12px;color:__MUTE__;border:1px solid __BORDER__;border-radius:8px;padding:7px 12px;background:__PANEL__}
.brandfoot .flinks a:hover{color:__INK__;border-color:__RUST__;text-decoration:none}
.brandfoot .flinks a .gh{width:14px;height:14px;flex:none;fill:currentColor}
.dp-link{color:__RUST_HI__ !important}
.dp-link b{color:__INK__}
"""

CSS = (CSS.replace("__BG__", BG).replace("__PANEL2__", PANEL2).replace("__PANEL__", PANEL)
       .replace("__BORDER__", BORDER).replace("__INK__", INK).replace("__MUTE__", MUTE)
       .replace("__FAINT__", FAINT).replace("__RUST_HI__", RUST_HI).replace("__RUST__", RUST))


def build_seo(data: dict, first: dict, last: dict, baseline: dict) -> tuple[str, str, str, str]:
    """Return (title, description, <head> meta block, JSON-LD <script>)."""
    gen = data.get("generated_utc", "")
    canonical = SITE_URL + "/"
    og_image = SITE_URL + "/og.png"

    def growth(k):
        a, b = baseline[k], last[k]
        return (b / a) if a else 0

    title = "Rust in the Linux Kernel — a version-by-version analysis"
    desc = (f"How Rust is growing in the mainline Linux kernel, measured release "
            f"by release from {first['version']} to {last['version']}: files, size, "
            f"purpose and SLOC via cloc. {last['files']:,} Rust files and "
            f"{last['code']:,} SLOC in {last['series']} — {growth('code'):.1f}× the "
            f"SLOC of {baseline['series']}.")
    keywords = ("Rust in the Linux kernel, Rust for Linux, Linux kernel Rust, "
                "rust/kernel, kernel drivers in Rust, Rust abstractions, cloc, SLOC, "
                "kernel source analysis, Rust procedural macros, Linux "
                f"{first['series']}, Linux {last['series']}")
    img_alt = (f"Rust in the Linux kernel: {last['files']:,} files and "
               f"{last['code']:,} SLOC in {last['series']}")

    meta = "\n".join([
        f'<link rel="canonical" href="{canonical}">',
        '<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">',
        f'<meta name="author" content="{DP_NAME}">',
        f'<meta name="theme-color" content="{BG}">',
        f'<meta name="keywords" content="{e(keywords)}">',
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="Rusted Kernel">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(desc)}">',
        f'<meta property="og:url" content="{canonical}">',
        f'<meta property="og:image" content="{og_image}">',
        '<meta property="og:image:type" content="image/png">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        f'<meta property="og:image:alt" content="{e(img_alt)}">',
        '<meta property="og:locale" content="en_US">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{e(title)}">',
        f'<meta name="twitter:description" content="{e(desc)}">',
        f'<meta name="twitter:image" content="{og_image}">',
        f'<meta name="twitter:image:alt" content="{e(img_alt)}">',
    ])

    org = {"@type": "Organization", "@id": f"{DP_URL}/#org",
           "name": "DomainsProject", "url": DP_URL}
    website = {"@type": "WebSite", "@id": f"{SITE_URL}/#website", "url": canonical,
               "name": "Rusted Kernel", "description": desc, "inLanguage": "en-US",
               "publisher": {"@id": org["@id"]}}
    dataset = {
        "@type": "Dataset", "@id": f"{SITE_URL}/#dataset",
        "name": "Rust usage in the Linux kernel by release",
        "description": (f"Per-release counts of Rust source files, on-disk size, "
                        f"purpose category and cloc line counts across Linux kernel "
                        f"series {first['series']}–{last['series']} (latest patch of each)."),
        "url": canonical, "inLanguage": "en-US",
        "creator": {"@id": org["@id"]}, "publisher": {"@id": org["@id"]},
        "isBasedOn": data.get("source", ""),
        "measurementTechnique": "Line counting with cloc; file classification by kernel-tree path",
        "variableMeasured": ["Rust source file count", "Source lines of code (SLOC)",
                             "Comment lines", "Blank lines", "On-disk size (bytes)"],
        "keywords": ["Rust", "Linux kernel", "SLOC", "cloc", "kernel drivers"],
        "license": f"{REPO_URL}/blob/master/LICENSE",
        "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json",
                          "contentUrl": f"{SITE_URL}/data/kernels.json"}],
    }
    article = {
        "@type": "TechArticle", "@id": f"{SITE_URL}/#article",
        "headline": title, "description": desc, "url": canonical,
        "inLanguage": "en-US", "image": og_image,
        "isPartOf": {"@id": website["@id"]}, "mainEntityOfPage": canonical,
        "author": {"@id": org["@id"]}, "publisher": {"@id": org["@id"]},
        "about": [
            {"@type": "Thing", "name": "Rust (programming language)",
             "sameAs": "https://en.wikipedia.org/wiki/Rust_(programming_language)"},
            {"@type": "Thing", "name": "Linux kernel",
             "sameAs": "https://en.wikipedia.org/wiki/Linux_kernel"},
        ],
        "mentions": {"@id": dataset["@id"]},
    }
    if gen:
        for node in (dataset, article):
            node["datePublished"] = gen
            node["dateModified"] = gen

    ld = {"@context": "https://schema.org", "@graph": [website, org, dataset, article]}
    # Escape "<" so a string value can never terminate the <script> element.
    ld_json = json.dumps(ld, ensure_ascii=False).replace("<", "\\u003c")
    jsonld = f'<script type="application/ld+json">{ld_json}</script>'
    return title, desc, meta, jsonld


def render(data: dict) -> str:
    versions = data["versions"]
    if not versions:
        raise SystemExit("render: data/kernels.json has no versions to render")
    versions = sorted(versions, key=lambda v: [int(x) for x in v["series"].split(".")])
    first, last = versions[0], versions[-1]
    # Growth multipliers are measured from the first release that actually ships
    # Rust: when the window starts before Rust landed (a zero-Rust baseline like
    # 6.0), dividing by it is undefined, so anchor to the first non-zero release.
    baseline = next((v for v in versions if v["code"]), first)
    since = "" if baseline is first else f" since {e(baseline['series'])}"

    def growth(key):
        a, b = baseline[key], last[key]
        return (b / a) if a else 0

    # Rust's share of the whole kernel (all languages), latest release.
    ktotal = last.get("kernel_code", 0)
    share_str = share_pct(last["code"], ktotal, 2)      # "0.31%"
    share_has = ktotal > 0

    # legend (only categories present)
    present_cats = []
    for cat, _ in CAT_ORDER:
        if any(any(c["category"] == cat for c in v["categories"]) for v in versions):
            present_cats.append(cat)

    def legend_html(cats):
        return "".join(
            f'<span class="item"><span class="dot" style="background:{color_for(c)}">'
            f'</span>{e(c)}</span>' for c in cats)

    legend = legend_html(present_cats)
    # companion legend: the same categories minus the two dominating crate blocks
    legend_no_crates = legend_html(
        [c for c in present_cats if c not in CRATE_CATEGORIES])

    # metric cards (latest version)
    n_drivers = len(last["drivers"])
    n_cats = len(last["categories"])
    cards = f"""
    <div class="card"><p class="k">Files · {e(last['version'])}</p>
      <p class="v">{fi(last['files'])}</p><p class="s">Rust source files (.rs)</p></div>
    <div class="card"><p class="k">Lines of code</p>
      <p class="v">{fi(last['code'])}</p><p class="s">SLOC (cloc, excl. comments/blanks)</p></div>
    <div class="card"><p class="k">On-disk size</p>
      <p class="v">{human_bytes(last['bytes'])}</p><p class="s">total .rs payload</p></div>
    <div class="card"><p class="k">Comment lines</p>
      <p class="v">{fi(last['comment'])}</p><p class="s">doc density {(last['comment']/last['code']) if last['code'] else 0:.2f}× code</p></div>
    <div class="card"><p class="k">Share of kernel</p>
      <p class="v">{share_str}</p><p class="s">of {mabbr(ktotal) if share_has else "—"} SLOC · all languages</p></div>
    <div class="card"><p class="k">Categories</p>
      <p class="v">{n_cats}</p><p class="s">distinct purposes in-tree</p></div>
    <div class="card"><p class="k">Driver subsystems</p>
      <p class="v">{n_drivers}</p><p class="s">shipping Rust drivers</p></div>
    """

    # summary table with deltas
    rows = []
    prev = None
    for v in versions:
        if prev:
            d = v["code"] - prev["code"]
            delta = f'<span class="delta-pos">+{fi(d)}</span>' if d >= 0 else fi(d)
        else:
            delta = "—"
        kcode = v.get("kernel_code", 0)
        rows.append(
            f'<tr><td class="mono">{e(v["version"])}</td>'
            f'<td class="num">{fi(v["files"])}</td>'
            f'<td class="num">{human_bytes(v["bytes"])}</td>'
            f'<td class="num">{fi(v["code"])}</td>'
            f'<td class="num">{fi(v["comment"])}</td>'
            f'<td class="num">{fi(v["blank"])}</td>'
            f'<td class="num">{delta}</td>'
            f'<td class="num">{fi(kcode) if kcode else "—"}</td>'
            f'<td class="num">{share_pct(v["code"], kcode, 3)}</td></tr>')
        prev = v
    summary_rows = "".join(rows)

    # per-version detail (details/summary)
    detail_blocks = []
    for v in versions:  # ascending, to match the per-version totals table
        maxcode = max((c["code"] for c in v["categories"]), default=1)
        catrows = "".join(cat_bar_row(c, maxcode) for c in v["categories"])
        drv = ""
        if v["drivers"]:
            drv_items = "".join(
                f'<tr><td class="catname">{e(d["category"])}</td>'
                f'<td class="num">{fi(d["files"])}</td>'
                f'<td class="num">{human_bytes(d["bytes"])}</td>'
                f'<td class="num">{fi(d["code"])}</td></tr>'
                for d in v["drivers"])
            drv = f"""
            <h3 class="mono" style="color:{MUTE};font-size:12px;letter-spacing:.12em;
              text-transform:uppercase;margin:20px 0 8px">Driver subsystems</h3>
            <div class="scroll"><table><thead><tr><th>Subsystem</th><th class="num">Files</th>
            <th class="num">Size</th><th class="num">SLOC</th></tr></thead>
            <tbody>{drv_items}</tbody></table></div>"""
        top = "".join(
            f'<tr><td class="catname" style="white-space:normal">{e(f["path"])}</td>'
            f'<td class="num">{human_bytes(f["bytes"])}</td>'
            f'<td class="num">{fi(f["code"])}</td></tr>'
            for f in v["largest_files"][:8])
        note = VERSION_NOTES.get(v["series"], "")
        note_html = f'<p class="vnote">{note}</p>' if note else ""
        detail_blocks.append(f"""
        <details>
          <summary><span class="ver">{e(v['version'])}</span>
            <span class="sstat"><b>{fi(v['files'])}</b> files ·
            <b>{fi(v['code'])}</b> SLOC · {human_bytes(v['bytes'])}</span></summary>
          <div class="body">
            {note_html}
            <div class="scroll"><table>
              <thead><tr><th>Category</th><th>Purpose</th><th class="num">Files</th>
                <th class="num">Size</th><th class="num">SLOC</th><th>Share</th></tr></thead>
              <tbody>{catrows}</tbody>
            </table></div>
            {drv}
            <h3 class="mono" style="color:{MUTE};font-size:12px;letter-spacing:.12em;
              text-transform:uppercase;margin:20px 0 8px">Largest files</h3>
            <div class="scroll"><table><thead><tr><th>Path</th><th class="num">Size</th>
              <th class="num">SLOC</th></tr></thead><tbody>{top}</tbody></table></div>
          </div>
        </details>""")
    details_html = "".join(detail_blocks)

    # glossary from category_reference (only present ones)
    gloss = "".join(
        f'<div class="gitem"><div class="h"><span class="dot" style="background:{color_for(r["category"])}"></span>'
        f'{e(r["category"])}</div><p class="p">{e(r["purpose"])}</p></div>'
        for r in data.get("category_reference", []) if r["category"] in present_cats)

    gen = e(data.get("generated_utc", ""))
    cloc_v = e(data.get("cloc_version", ""))
    src = e(data.get("source", ""))
    cloc_link = f'<a href="{CLOC_URL}">CLOC tool v{cloc_v}</a>'

    stacked = stacked_bars(
        versions,
        title="RUST SLOC BY PURPOSE",
        source=f"source: kernel.org  ·  latest patch of each series  ·  "
               f"{first['series']} → {last['series']}",
        note=f"SLOC = code lines, excl. comments & blanks  ·  cloc {cloc_v}")
    # Companion chart: identical, but with the two dominating crate blocks removed
    # so the smaller categories (drivers, samples, bindings, macros, …) are legible.
    stacked_no_crates = stacked_bars(
        versions,
        title="RUST SLOC BY PURPOSE — CRATES EXCLUDED",
        source=f"excl. Kernel crate + Vendored crates  ·  "
               f"{first['series']} → {last['series']}",
        note=f"SLOC = code lines, excl. comments & blanks  ·  cloc {cloc_v}",
        exclude=CRATE_CATEGORIES)
    files_line = line_chart(versions, "files", "files", "#5aa9e6")
    comment_line = line_chart(versions, "comment", "comment lines", RUST_HI)

    # Rust's share of the kernel: composition bar + share-over-time line, plus a
    # legend of the language buckets. Built only when totals were measured.
    share_section = ""
    if share_has:
        langs = {l["language"]: l["code"] for l in last.get("languages", [])}
        c_code = langs.get("C", 0)
        hdr_code = langs.get("C/C++ Header", 0)
        asm_code = langs.get("Assembly", 0)
        rust_code = last["code"]
        other_code = max(0, ktotal - c_code - hdr_code - asm_code - rust_code)
        # ordered largest → smallest so Rust is the rightmost (called-out) sliver
        buckets = [
            ("C", c_code, "#4d6a8a"),
            ("C/C++ headers", hdr_code, "#6f8cab"),
            ("Other", other_code, "#39424f"),
            ("Assembly", asm_code, "#93a9c4"),
            ("Rust", rust_code, RUST),
        ]
        comp_svg = composition_bar(buckets, ktotal)
        comp_legend = "".join(
            f'<span class="item"><span class="dot" style="background:{col}"></span>'
            f'{e(nm)} · {share_pct(code, ktotal, 2)}</span>'
            for nm, code, col in buckets)
        share_line = share_line_chart(versions)
        first_rust = baseline  # first Rust-bearing release
        fr_share = share_pct(first_rust["code"], first_rust.get("kernel_code", 0), 3)
        # First-party kernel Rust excludes the in-tree vendored crates so the
        # caveat separates authored kernel code from third-party tooling deps.
        vendored = sum(c["code"] for c in last["categories"]
                       if "Vendored" in c["category"])
        firstparty = last["code"] - vendored
        share_section = f"""
<section><div class="wrap">
  <h2>Rust's share of the kernel</h2>
  <p class="sectlede">The whole mainline tree is about <b>{mabbr(ktotal)}</b> lines of code
     across {len(last.get('languages', []))} languages — overwhelmingly C and C headers.
     Rust is still a sliver, but a fast-growing one: it went from <b>0%</b> in
     {e(first['series'])} (no <span class="mono">.rs</span> at all) to
     <b>{fr_share}</b> when it first landed in {e(first_rust['series'])}, to
     <b>{share_str}</b> in {e(last['series'])}.</p>
  <div class="sharetop">
    <div class="bigshare">
      <span class="pct">{share_str}</span>
      <span class="ofwhat">of the kernel's <b>{mabbr(ktotal)}</b> SLOC is Rust
        ({fi(last['code'])} of {fi(ktotal)} lines).</span>
      <span class="caveat">Of that, ~{mabbr(vendored)} is vendored crates; first-party
        kernel Rust is {mabbr(firstparty)} ({share_pct(firstparty, ktotal, 3)}).</span>
    </div>
    <div class="chartwrap sharechart"><p class="cap">Rust share of kernel · per version</p>{share_line}</div>
  </div>
  <div class="chartwrap compwrap">
    <p class="cap">Kernel SLOC by language · {e(last['version'])}</p>
    {comp_svg}
    <div class="legend">{comp_legend}</div>
  </div>
</div></section>
"""

    seo_title, seo_desc, seo_meta, seo_jsonld = build_seo(data, first, last, baseline)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(seo_title)}</title>
<meta name="description" content="{e(seo_desc)}">
{seo_meta}
<link rel="icon" href="{FAVICON}">
{seo_jsonld}
<style>{CSS}</style>
</head>
<body>

<header class="hero"><div class="wrap">
  <p class="eyebrow">rusted-kernel.com<span class="cursor"></span></p>
  <h1><a class="h1link" href="{KERNEL_RUST_DOCS}">Rust in the <span class="accent">Linux&nbsp;Kernel</span></a></h1>
  <p class="lede">A version-by-version measurement of how Rust is growing inside the
     mainline kernel tree — every <span class="mono">.rs</span> file counted, sized,
     categorised by purpose and measured with <span class="mono">cloc</span>.</p>
  <div class="headline">
    <span class="big">{e(first['series'])}</span>
    <span class="arrow">→</span>
    <span class="big">{e(last['series'])}</span>
    <span class="mult">&nbsp;·&nbsp;{growth('code'):.1f}× SLOC · {growth('files'):.1f}× files{since}{f' · {share_str} of the kernel' if share_has else ''}</span>
  </div>
  <p class="meta"><b>Range</b> {e(first['version'])} … {e(last['version'])} &nbsp;·&nbsp;
     <b>Series</b> {len(versions)} &nbsp;·&nbsp; <b>Generated</b> {gen} &nbsp;·&nbsp;
     {cloc_link} &nbsp;·&nbsp; <b>Source</b> kernel.org</p>
</div></header>

<section><div class="wrap">
  <h2>Latest snapshot · {e(last['version'])}</h2>
  <p class="sectlede">Where Rust stands in the newest analysed release.</p>
  <div class="cards">{cards}</div>
</div></section>
{share_section}
<section><div class="wrap">
  <h2>Growth by category</h2>
  <p class="sectlede">Rust source lines (SLOC) per kernel release, stacked by purpose.
     Two stories overlap here: the kernel's <em>own</em> Rust — the safe-abstraction
     crate plus production drivers — grows steadily release over release, while the
     large step at <b>6.19</b> is the one-time in-tree vendoring of the proc-macro
     crates (<span class="mono">syn</span>, <span class="mono">quote</span>,
     <span class="mono">proc-macro2</span>) that the kernel's macros depend on.</p>
  <div class="chartwrap">{stacked}</div>
  <div class="legend">{legend}</div>

  <h3 class="subhead">Same chart, kernel &amp; vendored crates excluded</h3>
  <p class="sectlede">The <span class="mono">rust/kernel</span> abstraction crate and the
     vendored third-party crates together dwarf everything else, flattening the rest of
     the chart. Dropping both isolates the growth of Rust's <em>applied</em> surface —
     production drivers, samples, generated &amp; UAPI bindings, procedural macros,
     <span class="mono">pin-init</span> and core shims.</p>
  <div class="chartwrap">{stacked_no_crates}</div>
  <div class="legend">{legend_no_crates}</div>

  <div class="smallcharts">
    <div class="chartwrap"><p class="cap">Rust files per version</p>{files_line}</div>
    <div class="chartwrap"><p class="cap">Comment lines per version</p>{comment_line}</div>
  </div>
</div></section>

<section><div class="wrap">
  <h2>Per-version totals</h2>
  <p class="sectlede">Files, on-disk size and cloc line counts for each release, with the
     change in SLOC versus the previous series. <b>Kernel SLOC</b> is the whole tree
     (all languages) and <b>Rust %</b> is Rust's share of it.</p>
  <div class="scroll"><table>
    <thead><tr><th>Version</th><th class="num">Files</th><th class="num">Size</th>
      <th class="num">SLOC</th><th class="num">Comments</th><th class="num">Blank</th>
      <th class="num">Δ SLOC</th><th class="num">Kernel SLOC</th><th class="num">Rust %</th></tr></thead>
    <tbody>{summary_rows}</tbody>
  </table></div>
</div></section>

<section><div class="wrap">
  <h2>Version detail</h2>
  <p class="sectlede">Expand any release for its full category breakdown, driver subsystems
     and largest files.</p>
  {details_html}
</div></section>

<section><div class="wrap">
  <h2>What the categories mean</h2>
  <p class="sectlede">How each <span class="mono">.rs</span> file is classified by its
     location in the kernel tree.</p>
  <div class="glossary">{gloss}</div>
</div></section>

<section><div class="wrap">
  <h2>Methodology</h2>
  <p class="sectlede">How the numbers are produced — fully reproducible from the
     scripts in the repository.</p>
  <p class="method">For each kernel series ≥ {e(data.get('floor',''))} the latest patch release is
     resolved from <a href="{src}">{src}</a>, the source tarball downloaded and only
     <code>*.rs</code> files extracted. File sizes come from the extracted sources; line
     counts (code / comment / blank) from {cloc_link}. Generated bindings that
     are produced only at build time are <em>not</em> shipped in the tarball and therefore
     not counted. The <b>share-of-kernel</b> figures come from a second
     <code>cloc</code> pass over the <em>entire</em> extracted tree (all languages), so
     the denominator is the whole kernel's SLOC measured the same way as the Rust
     numerator. Data regenerated with <code>scripts/build.sh</code>;
     machine-readable results live in <code>data/kernels.json</code>.</p>
</div></section>

<footer><div class="wrap">
  <div class="brandfoot">
    <div class="bfleft">
      <span class="mark"><span class="p">~/</span>rusted-kernel<span class="tld">.com</span></span>
      <span class="fdate">· {gen}</span>
    </div>
    <div class="flinks">
      <a href="{REPO_URL}">{GH_ICON}tb0hdan/rusted-kernel <span class="arr" style="color:{RUST}">↗</span></a>
      <a class="dp-link" href="{DP_URL}">Part of <b>{DP_NAME}</b> ↗</a>
    </div>
  </div>
</div></footer>

</body>
</html>
"""


def write_seo_files(repo_root: Path, data: dict) -> None:
    """Emit robots.txt and sitemap.xml (lastmod tracks the data build date)."""
    lastmod = data.get("generated_utc", "")
    lastmod_el = f"\n    <lastmod>{e(lastmod)}</lastmod>" if lastmod else ""
    (repo_root / "robots.txt").write_text(
        "User-agent: *\n"
        "Allow: /\n\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )
    (repo_root / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        '  <url>\n'
        f'    <loc>{SITE_URL}/</loc>{lastmod_el}\n'
        '    <changefreq>monthly</changefreq>\n'
        '    <priority>1.0</priority>\n'
        '  </url>\n'
        '</urlset>\n'
    )


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    data = json.loads((repo_root / "data" / "kernels.json").read_text())
    out = repo_root / "index.html"
    out.write_text(render(data))
    write_seo_files(repo_root, data)
    print(f"[*] wrote {out} + robots.txt + sitemap.xml ({len(data['versions'])} versions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
