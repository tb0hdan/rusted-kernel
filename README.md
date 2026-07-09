# rusted-kernel

Source for **[rusted-kernel.com](http://rusted-kernel.com)** — a data-driven,
version-by-version analysis of **Rust usage in the Linux kernel**.

The published site is a single self-contained `index.html` (dark "kernel
terminal" theme, inline SVG charts, no JavaScript, no external assets). It is
**generated** from measured data — do not hand-edit `index.html`; edit the
scripts and rebuild.

## What it measures
For every kernel series `>= 6.0` (the floor is configurable), the latest patch
release is analysed for its Rust footprint:

- number of `*.rs` files and their on-disk size
- **purpose** of each file (kernel abstraction crate, procedural macros,
  generated/UAPI bindings, pin-init, core shims, vendored crates, samples,
  production drivers — broken out by subsystem — build tooling, other subsystems)
- SLOC / comment / blank line counts via [`cloc`](https://github.com/AlDanial/cloc)

The `6.0` floor starts one series *before* Rust entered the tree (`6.0` ships
zero `.rs`; Rust first appears in `6.1`), so the report captures the moment Rust
landed and the growth from a true zero baseline.

## Rebuild

```sh
scripts/build.sh                       # full run: all series >= 6.0
scripts/build.sh --only 6.12.95,7.1.3  # quick subset while iterating
scripts/build.sh --floor 6.12          # raise the floor
```

`build.sh` runs:

1. `scripts/analyze.py` — discover releases from kernel.org → download (cached,
   integrity-checked) → extract only `*.rs` → `cloc` → `data/kernels.json`
2. `scripts/render.py` — `data/kernels.json` → `index.html` + `robots.txt` +
   `sitemap.xml`
3. `scripts/ogimage.py` — `data/kernels.json` → `og.png` (1200×630 Open Graph
   share image; skips with a warning if `rsvg-convert` is absent)

**Requirements:** `python3`, `curl`, `tar`, `xz`, `cloc`. The Open Graph image
step additionally needs `rsvg-convert` (librsvg) — it is optional and skipped
gracefully when missing.

Downloaded tarballs are cached in `data/tarballs/` (gitignored); the machine-
readable results in `data/kernels.json` are committed for reproducibility.

## Layout
```
index.html        generated site (do not edit by hand)
og.png            generated 1200x630 Open Graph share image
robots.txt        generated
sitemap.xml       generated (lastmod tracks the data build date)
scripts/          analysis + render pipeline
data/kernels.json committed analysis results
data/tarballs/    download cache (gitignored)
CNAME             rusted-kernel.com
LICENSE
```
