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

# Categorical palette for stacked chart / legend. "Kernel crate" gets the
# hero Rust orange; the rest are muted-but-distinct hues that read on black.
CAT_ORDER = [
    ("Kernel crate", RUST),
    ("Drivers", "#57b894"),
    ("Vendored crates", "#c9a227"),
    ("Procedural macros", "#c792ea"),
    ("Generated bindings", "#5aa9e6"),
    ("UAPI bindings", "#66d1c4"),
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


def color_for(cat: str) -> str:
    return CAT_COLOR.get(cat, "#5b667a")


# --- formatting ------------------------------------------------------------
def fi(n: int) -> str:
    return f"{n:,}"


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
def stacked_bars(versions: list[dict]) -> str:
    """Stacked bar chart: Rust SLOC by category, one bar per version."""
    W, H = 960, 440
    ml, mr, mt, mb = 64, 20, 24, 56
    plot_w = W - ml - mr
    plot_h = H - mt - mb
    n = len(versions)
    if n == 0:
        return ""

    # Per-version category -> code map, only categories present anywhere.
    present: list[str] = []
    for cat, _ in CAT_ORDER:
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

    parts.append(f'<text x="{ml-46}" y="{mt-8}" class="axis">SLOC</text>')
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
        parts.append(f'<text x="{x:.1f}" y="{H-mb+20:.1f}" text-anchor="middle" '
                     f'class="axis small">{e(versions[i]["series"])}</text>')
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
.smallcharts{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}
.smallcharts .chartwrap .cap{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;
  letter-spacing:.1em;text-transform:uppercase;color:__FAINT__;margin:2px 4px 8px}
@media(max-width:720px){.smallcharts{grid-template-columns:1fr}}

.legend{display:flex;flex-wrap:wrap;gap:10px 18px;margin:18px 2px 0}
.legend .item{display:flex;align-items:center;gap:7px;font-size:12.5px;color:__MUTE__}
.dot{display:inline-block;width:11px;height:11px;border-radius:3px;flex:none}

table{width:100%;border-collapse:collapse;font-size:13.5px}
.scroll{overflow-x:auto}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid __BORDER__;white-space:nowrap}
th{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;letter-spacing:.1em;
  text-transform:uppercase;color:__FAINT__;font-weight:600}
td.num,th.num{text-align:right;font-family:ui-monospace,Menlo,Consolas,monospace}
tbody tr:hover{background:__PANEL2__}
.delta-pos{color:__RUST_HI__}
.catname{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px}
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

.glossary{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.gitem{background:__PANEL__;border:1px solid __BORDER__;border-radius:10px;padding:14px 15px}
.gitem .h{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;color:__INK__;
  display:flex;align-items:center;gap:8px;margin-bottom:5px}
.gitem .p{font-size:12.5px;color:__MUTE__;margin:0}

footer{padding:40px 0 70px;color:__FAINT__;font-size:12.5px}
footer code{background:__PANEL2__;border:1px solid __BORDER__;border-radius:5px;padding:1px 6px;
  font-family:ui-monospace,Menlo,Consolas,monospace;color:__MUTE__}
footer p{max-width:80ch}
.tag{display:inline-block;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;
  color:__RUST__;border:1px solid __BORDER__;border-radius:20px;padding:2px 10px;margin-right:6px}
"""

CSS = (CSS.replace("__BG__", BG).replace("__PANEL2__", PANEL2).replace("__PANEL__", PANEL)
       .replace("__BORDER__", BORDER).replace("__INK__", INK).replace("__MUTE__", MUTE)
       .replace("__FAINT__", FAINT).replace("__RUST_HI__", RUST_HI).replace("__RUST__", RUST))


def render(data: dict) -> str:
    versions = data["versions"]
    if not versions:
        raise SystemExit("render: data/kernels.json has no versions to render")
    versions = sorted(versions, key=lambda v: [int(x) for x in v["series"].split(".")])
    first, last = versions[0], versions[-1]

    def growth(key):
        a, b = first[key], last[key]
        return (b / a) if a else 0

    # legend (only categories present)
    present_cats = []
    for cat, _ in CAT_ORDER:
        if any(any(c["category"] == cat for c in v["categories"]) for v in versions):
            present_cats.append(cat)
    legend = "".join(
        f'<span class="item"><span class="dot" style="background:{color_for(c)}"></span>{e(c)}</span>'
        for c in present_cats)

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
        rows.append(
            f'<tr><td class="mono">{e(v["version"])}</td>'
            f'<td class="num">{fi(v["files"])}</td>'
            f'<td class="num">{human_bytes(v["bytes"])}</td>'
            f'<td class="num">{fi(v["code"])}</td>'
            f'<td class="num">{fi(v["comment"])}</td>'
            f'<td class="num">{fi(v["blank"])}</td>'
            f'<td class="num">{delta}</td></tr>')
        prev = v
    summary_rows = "".join(rows)

    # per-version detail (details/summary)
    detail_blocks = []
    for v in reversed(versions):  # newest first
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
        detail_blocks.append(f"""
        <details>
          <summary><span class="ver">{e(v['version'])}</span>
            <span class="sstat"><b>{fi(v['files'])}</b> files ·
            <b>{fi(v['code'])}</b> SLOC · {human_bytes(v['bytes'])}</span></summary>
          <div class="body">
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

    stacked = stacked_bars(versions)
    files_line = line_chart(versions, "files", "files", "#5aa9e6")
    comment_line = line_chart(versions, "comment", "comment lines", RUST_HI)

    gen = e(data.get("generated_utc", ""))
    cloc_v = e(data.get("cloc_version", ""))
    src = e(data.get("source", ""))

    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rusted Kernel — Rust in the Linux Kernel</title>
<meta name="description" content="A version-by-version analysis of Rust adoption in the Linux kernel, from {e(first['version'])} to {e(last['version'])}: files, size, purpose and SLOC.">
<link rel="icon" href="{FAVICON}">
<style>{CSS}</style>

<header class="hero"><div class="wrap">
  <p class="eyebrow">rusted-kernel.com<span class="cursor"></span></p>
  <h1>Rust in the <span class="accent">Linux&nbsp;Kernel</span></h1>
  <p class="lede">A version-by-version measurement of how Rust is growing inside the
     mainline kernel tree — every <span class="mono">.rs</span> file counted, sized,
     categorised by purpose and measured with <span class="mono">cloc</span>.</p>
  <div class="headline">
    <span class="big">{e(first['series'])}</span>
    <span class="arrow">→</span>
    <span class="big">{e(last['series'])}</span>
    <span class="mult">&nbsp;·&nbsp;{growth('code'):.1f}× SLOC · {growth('files'):.1f}× files</span>
  </div>
  <p class="meta"><b>Range</b> {e(first['version'])} … {e(last['version'])} &nbsp;·&nbsp;
     <b>Series</b> {len(versions)} &nbsp;·&nbsp; <b>Generated</b> {gen} &nbsp;·&nbsp;
     <b>Tool</b> {cloc_v} &nbsp;·&nbsp; <b>Source</b> kernel.org</p>
</div></header>

<section><div class="wrap">
  <h2>Latest snapshot · {e(last['version'])}</h2>
  <p class="sectlede">Where Rust stands in the newest analysed release.</p>
  <div class="cards">{cards}</div>
</div></section>

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
  <div class="smallcharts">
    <div class="chartwrap"><p class="cap">Rust files per version</p>{files_line}</div>
    <div class="chartwrap"><p class="cap">Comment lines per version</p>{comment_line}</div>
  </div>
</div></section>

<section><div class="wrap">
  <h2>Per-version totals</h2>
  <p class="sectlede">Files, on-disk size and cloc line counts for each release, with the
     change in SLOC versus the previous series.</p>
  <div class="scroll"><table>
    <thead><tr><th>Version</th><th class="num">Files</th><th class="num">Size</th>
      <th class="num">SLOC</th><th class="num">Comments</th><th class="num">Blank</th>
      <th class="num">Δ SLOC</th></tr></thead>
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

<footer><div class="wrap">
  <p><span class="tag">methodology</span></p>
  <p>For each kernel series ≥ {e(data.get('floor',''))} the latest patch release is
     resolved from <a href="{src}">{src}</a>, the source tarball downloaded and only
     <code>*.rs</code> files extracted. File sizes come from the extracted sources; line
     counts (code / comment / blank) from <code>{cloc_v}</code>. Generated bindings that
     are produced only at build time are <em>not</em> shipped in the tarball and therefore
     not counted. Data regenerated with <code>scripts/build.sh</code>;
     machine-readable results live in <code>data/kernels.json</code>.</p>
  <p style="margin-top:14px">Generated {gen} · rusted-kernel.com</p>
</div></footer>
"""


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    data = json.loads((repo_root / "data" / "kernels.json").read_text())
    out = repo_root / "index.html"
    out.write_text(render(data))
    print(f"[*] wrote {out} ({len(data['versions'])} versions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
