#!/usr/bin/env python3
"""Analyze Rust usage across Linux kernel releases.

For every stable kernel series >= a configurable floor (default 6.0), this
script resolves the latest patch release from kernel.org, downloads the source
tarball (cached), extracts only the Rust (``*.rs``) sources, and produces a
detailed breakdown of:

  * number of Rust files
  * their on-disk size (bytes)
  * their purpose (categorised by location in the kernel tree)
  * SLOC / comment / blank counts (via the ``cloc`` tool)

It also measures the **whole tree** (all languages) with a second ``cloc`` pass
so the report can express Rust as a share of the total kernel SLOC and show the
per-language composition. That pass fully extracts each tarball (unlike the
cheap ``*.rs``-only path), so it is cached independently and can be disabled
with ``--skip-kernel-totals``.

Results are written to ``data/kernels.json`` for the site renderer to consume.

The script shells out to ``curl``, ``tar``, ``xz`` and ``cloc``; the ``*.rs``
path streams only Rust files straight out of each compressed tarball (small peak
disk), while the totals path extracts the full tree one release at a time.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

CDN = "https://cdn.kernel.org/pub/linux/kernel"
DEFAULT_FLOOR = (6, 0)

# ---------------------------------------------------------------------------
# Categorisation: map a kernel-relative path to a (category, purpose) pair.
# Rules are evaluated top to bottom; first match wins.  Keep the human-readable
# purpose text short -- it is surfaced verbatim in the report.
# ---------------------------------------------------------------------------
CATEGORY_RULES: list[tuple[str, str, str]] = [
    ("rust/kernel/",   "Kernel crate",        "Safe Rust abstractions layered over the C kernel APIs"),
    ("rust/macros/",   "Procedural macros",   "Compiler plumbing: module!, #[vtable], pin-data, etc."),
    ("rust/pin-init/", "pin-init crate",      "Safe in-place (pinned) initialisation primitives"),
    ("rust/bindings/", "Generated bindings",  "Auto-generated raw FFI bindings to C kernel symbols"),
    ("rust/uapi/",     "UAPI bindings",       "Raw bindings to the kernel's userspace API headers"),
    ("samples/rust/",  "Samples & examples",  "Reference modules demonstrating the Rust API"),
    ("drivers/",       "Drivers",             "Production device drivers written in Rust"),
    ("scripts/",       "Kernel build tooling", "Codegen and helpers used during the kernel build"),
    ("tools/",         "Tooling & tests",     "Out-of-tree tooling and test harnesses"),
    ("io_uring/",      "io_uring",            "io_uring subsystem Rust code"),
    ("lib/",           "Library code",        "Shared library-style Rust code"),
    ("kernel/",        "Core kernel",         "Core kernel subsystem Rust code"),
]

# First-party subdirectories under rust/ (everything else there is a vendored,
# third-party crate: syn, quote, proc-macro2, ...).
RUST_FIRST_PARTY = {"kernel", "macros", "pin-init", "bindings", "uapi", "helpers"}

VENDORED = ("Vendored crates",
            "Third-party crates vendored in-tree (syn, quote, proc-macro2) to "
            "build the kernel's procedural macros")
CORE_SHIMS = ("Core runtime & shims",
              "compiler_builtins, ffi and other crate-root shims")
DEFAULT_CATEGORY = ("Other subsystems", "Rust code elsewhere in the tree")

# Full ordered reference of every purpose the report can surface.
CATEGORY_REFERENCE: list[tuple[str, str]] = (
    [(c, p) for _, c, p in CATEGORY_RULES] + [VENDORED, CORE_SHIMS, DEFAULT_CATEGORY]
)


def categorise(relpath: str) -> tuple[str, str]:
    for prefix, cat, purpose in CATEGORY_RULES:
        if relpath.startswith(prefix):
            return cat, purpose
    if relpath.startswith("rust/"):
        rest = relpath[len("rust/"):]
        if "/" in rest and rest.split("/", 1)[0] not in RUST_FIRST_PARTY:
            return VENDORED          # rust/<crate>/... third-party crate
        return CORE_SHIMS            # rust/foo.rs crate-root shim
    return DEFAULT_CATEGORY


def driver_subsystem(relpath: str) -> str | None:
    """For a drivers/* path return a friendly subsystem name, else None."""
    if not relpath.startswith("drivers/"):
        return None
    parts = relpath.split("/")
    if len(parts) < 3:
        return "drivers (misc)"
    sub = parts[1]
    friendly = {
        "gpu": "GPU / DRM",
        "net": "Networking",
        "block": "Block",
        "char": "Character devices",
        "cpufreq": "CPU frequency",
        "hwmon": "Hardware monitoring",
        "android": "Android (binder)",
        "usb": "USB",
        "pci": "PCI",
        "firmware": "Firmware",
        "gpio": "GPIO",
        "regulator": "Regulators",
    }.get(sub, sub)
    return f"drivers/{sub} ({friendly})"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class CategoryStat:
    category: str
    purpose: str
    files: int = 0
    bytes: int = 0
    code: int = 0
    comment: int = 0
    blank: int = 0


@dataclass
class VersionReport:
    version: str
    series: str
    tarball: str
    url: str
    files: int = 0
    bytes: int = 0
    code: int = 0
    comment: int = 0
    blank: int = 0
    categories: list[dict] = field(default_factory=list)
    drivers: list[dict] = field(default_factory=list)
    largest_files: list[dict] = field(default_factory=list)
    # Whole-tree (all languages) totals from the second cloc pass. Zero until a
    # kernel-totals measurement has run for this version (see measure_kernel_totals).
    kernel_files: int = 0
    kernel_code: int = 0
    kernel_comment: int = 0
    kernel_blank: int = 0
    # Per-language SLOC breakdown, [{language, files, code, comment, blank}]
    # sorted by code desc. Feeds the language-composition bar.
    languages: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Version discovery
# ---------------------------------------------------------------------------
def http_get(url: str) -> str:
    out = subprocess.run(
        ["curl", "-fsSL", "--retry", "3", "--retry-delay", "2", url],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(f"curl failed for {url}: {out.stderr.strip()}")
    return out.stdout


def discover_versions(floor: tuple[int, int]) -> list[dict]:
    """Return latest patch release per series >= floor, as list of dicts:
    {version, series, tarball, url} sorted ascending by version.
    """
    pat = re.compile(r"linux-(\d+)\.(\d+)(?:\.(\d+))?\.tar\.xz")
    latest: dict[tuple[int, int], tuple[int, str, str]] = {}
    # Probe v6.x, v7.x, v8.x ... until a directory 404s.
    major = floor[0]
    while True:
        base = f"{CDN}/v{major}.x/"
        try:
            html = http_get(base)
        except RuntimeError:
            # No such major directory -> stop probing higher majors.
            if major > floor[0]:
                break
            raise
        found_any = False
        for m in pat.finditer(html):
            maj, minr = int(m.group(1)), int(m.group(2))
            patch = int(m.group(3)) if m.group(3) else 0
            if (maj, minr) < floor:
                continue
            found_any = True
            key = (maj, minr)
            cur = latest.get(key)
            if cur is None or patch > cur[0]:
                latest[key] = (patch, m.group(0), base + m.group(0))
        # Stop once we reach a major with no tarballs at all (future-proof).
        if not found_any and major > floor[0]:
            break
        major += 1
        if major > floor[0] + 10:  # hard safety stop
            break

    result = []
    for (maj, minr), (patch, tarball, url) in sorted(latest.items()):
        version = f"{maj}.{minr}.{patch}" if patch else f"{maj}.{minr}"
        result.append({
            "version": version,
            "series": f"{maj}.{minr}",
            "tarball": tarball,
            "url": url,
        })
    return result


# ---------------------------------------------------------------------------
# Download + extract
# ---------------------------------------------------------------------------
def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        # Verify cached copy integrity; re-download if corrupt.
        if subprocess.run(["xz", "-t", str(dest)], capture_output=True).returncode == 0:
            print(f"    cached: {dest.name}")
            return
        print(f"    cached copy corrupt, re-downloading: {dest.name}")
        dest.unlink()
    print(f"    downloading: {url}")
    rc = subprocess.run(
        ["curl", "-fL", "--retry", "3", "--retry-delay", "2",
         "-C", "-", "-o", str(dest), url]
    ).returncode
    if rc != 0:
        raise RuntimeError(f"download failed ({rc}): {url}")
    if subprocess.run(["xz", "-t", str(dest)], capture_output=True).returncode != 0:
        raise RuntimeError(f"downloaded tarball failed integrity check: {dest}")


def extract_rust(tarball: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    # Stream the whole archive but only write out *.rs members.
    proc = subprocess.run(
        ["tar", "-xf", str(tarball), "-C", str(dest),
         "--wildcards", "--no-anchored", "*.rs"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        # GNU tar exits non-zero when the pattern matched no members -- that is a
        # legitimate "this kernel ships no Rust" result. Any *other* failure
        # (I/O error, ENOSPC, truncated/killed extraction) must NOT be swallowed,
        # or a partial tree could be cached as if complete.
        if "Not found in archive" in proc.stderr:
            return
        raise RuntimeError(
            f"extract failed for {tarball.name}: {proc.stderr.strip()[:300]}")


def extract_full(tarball: Path, dest: Path) -> None:
    """Extract the *entire* tree (all files, every language).

    Used only by the whole-tree totals pass; far larger on disk than
    :func:`extract_rust`, so callers extract one release at a time and clean up.
    """
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    proc = subprocess.run(
        ["tar", "-xf", str(tarball), "-C", str(dest)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"full extract failed for {tarball.name}: {proc.stderr.strip()[:300]}")


# ---------------------------------------------------------------------------
# cloc
# ---------------------------------------------------------------------------
def run_cloc(root: Path) -> dict[str, dict]:
    """Return {relpath -> {code, comment, blank}} keyed by kernel-relative path."""
    out = subprocess.run(
        ["cloc", "--by-file", "--json", "--quiet", "--follow-links", str(root)],
        capture_output=True, text=True,
    )
    if not out.stdout.strip():
        return {}
    data = json.loads(out.stdout)
    result: dict[str, dict] = {}
    root_str = str(root)
    for key, val in data.items():
        if key in ("header", "SUM"):
            continue
        rel = key
        if rel.startswith(root_str):
            rel = rel[len(root_str):].lstrip("/")
        rel = strip_top(rel)
        result[rel] = {
            "code": val.get("code", 0),
            "comment": val.get("comment", 0),
            "blank": val.get("blank", 0),
        }
    return result


def run_cloc_totals(root: Path) -> dict:
    """Whole-tree cloc summary across *all* languages.

    Returns ``{"total": {files, code, comment, blank}, "languages": [...]}``
    where ``languages`` is ``[{language, files, code, comment, blank}]`` sorted
    by code descending. Raises on cloc failure so a silent zero is never cached.
    """
    # No --follow-links here: the kernel tree symlinks directories across arches
    # (e.g. arch/*/boot/dts), which makes cloc's File::Find abort with "encountered
    # a second time", and following them would double-count anyway.
    out = subprocess.run(
        ["cloc", "--json", "--quiet", str(root)],
        capture_output=True, text=True,
    )
    if not out.stdout.strip():
        raise RuntimeError(
            "cloc produced no output for full tree "
            f"(rc={out.returncode}, stderr={out.stderr.strip()[:300]!r})")
    data = json.loads(out.stdout)
    summ = data.get("SUM")
    if not summ:
        raise RuntimeError("cloc output missing SUM for full tree")
    languages = []
    for lang, val in data.items():
        if lang in ("header", "SUM"):
            continue
        languages.append({
            "language": lang,
            "files": val.get("nFiles", 0),
            "code": val.get("code", 0),
            "comment": val.get("comment", 0),
            "blank": val.get("blank", 0),
        })
    languages.sort(key=lambda x: x["code"], reverse=True)
    return {
        "total": {
            "files": summ.get("nFiles", 0),
            "code": summ.get("code", 0),
            "comment": summ.get("comment", 0),
            "blank": summ.get("blank", 0),
        },
        "languages": languages,
    }


def strip_top(rel: str) -> str:
    """Strip the leading ``linux-<ver>/`` component from a path."""
    parts = rel.split("/", 1)
    if parts and re.match(r"linux-[\d.]+", parts[0]) and len(parts) > 1:
        return parts[1]
    return rel


# ---------------------------------------------------------------------------
# Per-version analysis
# ---------------------------------------------------------------------------
def measure_files(info: dict, cache_dir: Path, work_dir: Path,
                  meas_cache: Path, keep_extract: bool,
                  refresh: bool) -> list[dict]:
    """Return per-file measurements [{path, bytes, code, comment, blank}].

    Cached to ``meas_cache/<version>.json`` so re-runs that only change
    categorisation or rendering skip the expensive download/extract/cloc.
    """
    cache_file = meas_cache / f"{info['version']}.json"
    if cache_file.exists() and not refresh:
        try:
            records = json.loads(cache_file.read_text())
            print("    using cached measurements")
            return records
        except (json.JSONDecodeError, ValueError):
            # A run killed mid-write leaves a truncated cache file; treat it as a
            # miss and re-measure rather than failing this version forever.
            print("    cached measurements corrupt -> re-measuring")
            cache_file.unlink(missing_ok=True)

    tarball = cache_dir / info["tarball"]
    download(info["url"], tarball)

    extract_dir = work_dir / f"linux-{info['version']}"
    print("    extracting *.rs ...")
    extract_rust(tarball, extract_dir)

    sizes: dict[str, int] = {}
    for p in extract_dir.rglob("*.rs"):
        if p.is_file():
            sizes[strip_top(str(p.relative_to(extract_dir)))] = p.stat().st_size

    print(f"    running cloc on {len(sizes)} files ...")
    cloc = run_cloc(extract_dir)
    # Guard against a silent cloc failure recording all-zero line counts: if we
    # extracted .rs files but cloc returned nothing, fail loudly (main() will
    # skip this version) rather than caching bogus zeros.
    if sizes and not cloc:
        raise RuntimeError("cloc produced no output for extracted sources")

    records = []
    for rel, size in sizes.items():
        loc = cloc.get(rel, {"code": 0, "comment": 0, "blank": 0})
        records.append({"path": rel, "bytes": size, "code": loc["code"],
                        "comment": loc["comment"], "blank": loc["blank"]})

    if not keep_extract:
        shutil.rmtree(extract_dir, ignore_errors=True)

    # Write atomically so an interrupted run can't leave a truncated cache file.
    meas_cache.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_name(cache_file.name + ".tmp")
    tmp.write_text(json.dumps(records))
    os.replace(tmp, cache_file)
    return records


def measure_kernel_totals(info: dict, cache_dir: Path, work_dir: Path,
                          meas_cache: Path, keep_extract: bool,
                          refresh: bool) -> dict:
    """Whole-tree (all languages) totals for one release.

    Fully extracts the tarball, runs a summary ``cloc`` across every language,
    then removes the tree. Cached to ``meas_cache/kernel-<version>.json`` so the
    expensive extraction only happens once per release. Returned dict matches
    :func:`run_cloc_totals` (``{"total": {...}, "languages": [...]}``).
    """
    cache_file = meas_cache / f"kernel-{info['version']}.json"
    if cache_file.exists() and not refresh:
        try:
            totals = json.loads(cache_file.read_text())
            print("    using cached kernel totals")
            return totals
        except (json.JSONDecodeError, ValueError):
            print("    cached kernel totals corrupt -> re-measuring")
            cache_file.unlink(missing_ok=True)

    tarball = cache_dir / info["tarball"]
    download(info["url"], tarball)

    extract_dir = work_dir / f"full-linux-{info['version']}"
    print("    extracting full tree (all languages) ...")
    extract_full(tarball, extract_dir)
    try:
        print("    running cloc on full tree ...")
        totals = run_cloc_totals(extract_dir)
    finally:
        if not keep_extract:
            shutil.rmtree(extract_dir, ignore_errors=True)

    print(f"    => kernel {totals['total']['code']:,} SLOC across "
          f"{len(totals['languages'])} languages")

    meas_cache.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_name(cache_file.name + ".tmp")
    tmp.write_text(json.dumps(totals))
    os.replace(tmp, cache_file)
    return totals


def build_report(info: dict, records: list[dict]) -> VersionReport:
    rep = VersionReport(version=info["version"], series=info["series"],
                        tarball=info["tarball"], url=info["url"])
    cats: dict[str, CategoryStat] = {}
    drivers: dict[str, CategoryStat] = {}

    for r in records:
        rel = r["path"]
        cat, purpose = categorise(rel)
        cs = cats.get(cat)
        if cs is None:
            cs = cats[cat] = CategoryStat(category=cat, purpose=purpose)
        cs.files += 1
        cs.bytes += r["bytes"]
        cs.code += r["code"]
        cs.comment += r["comment"]
        cs.blank += r["blank"]

        sub = driver_subsystem(rel)
        if sub:
            ds = drivers.get(sub)
            if ds is None:
                ds = drivers[sub] = CategoryStat(category=sub, purpose="")
            ds.files += 1
            ds.bytes += r["bytes"]
            ds.code += r["code"]
            ds.comment += r["comment"]
            ds.blank += r["blank"]

        rep.files += 1
        rep.bytes += r["bytes"]
        rep.code += r["code"]
        rep.comment += r["comment"]
        rep.blank += r["blank"]

    rep.categories = [asdict(c) for c in sorted(
        cats.values(), key=lambda c: c.code, reverse=True)]
    rep.drivers = [asdict(d) for d in sorted(
        drivers.values(), key=lambda d: d.code, reverse=True)]
    rep.largest_files = sorted(
        ({"path": r["path"], "bytes": r["bytes"], "code": r["code"]} for r in records),
        key=lambda r: r["code"], reverse=True)[:15]

    print(f"    => {rep.files} files, {rep.bytes:,} bytes, {rep.code:,} SLOC")
    return rep


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--floor", default="6.0",
                    help="lowest kernel series to include (default 6.0)")
    ap.add_argument("--only", default="",
                    help="comma-separated list of exact versions to analyze "
                         "(for quick validation), e.g. 6.12.95")
    ap.add_argument("--cache-dir", default=None,
                    help="tarball cache dir (default data/tarballs)")
    ap.add_argument("--work-dir", default=None,
                    help="scratch extraction dir (default a temp dir)")
    ap.add_argument("--out", default=None,
                    help="output JSON (default data/kernels.json)")
    ap.add_argument("--keep-extract", action="store_true",
                    help="do not delete extracted trees (debugging)")
    ap.add_argument("--refresh", action="store_true",
                    help="ignore the per-file measurement cache and re-measure")
    ap.add_argument("--skip-kernel-totals", action="store_true",
                    help="skip the whole-tree (all languages) cloc pass that "
                         "measures total kernel SLOC (fast .rs-only run)")
    args = ap.parse_args()

    # Fail fast on a missing external dependency, before any expensive work --
    # note cloc may otherwise not be exercised at all on an all-cache-hit run.
    for tool in ("curl", "tar", "xz", "cloc"):
        if shutil.which(tool) is None:
            raise SystemExit(f"error: required tool '{tool}' not found in PATH")

    repo_root = Path(__file__).resolve().parent.parent
    data_dir = repo_root / "data"
    cache_dir = Path(args.cache_dir) if args.cache_dir else data_dir / "tarballs"
    meas_cache = data_dir / ".cache"
    out_path = Path(args.out) if args.out else data_dir / "kernels.json"
    created_work_dir = args.work_dir is None
    work_dir = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="rk-"))

    floor = tuple(int(x) for x in args.floor.split("."))  # type: ignore

    try:
        print(f"[*] discovering kernel versions >= {args.floor} ...")
        versions = discover_versions(floor)  # type: ignore
        if args.only:
            wanted = set(args.only.split(","))
            versions = [v for v in versions if v["version"] in wanted]
        print(f"[*] {len(versions)} versions: " + ", ".join(v["version"] for v in versions))

        reports: list[VersionReport] = []
        for i, info in enumerate(versions, 1):
            print(f"[{i}/{len(versions)}] {info['version']}")
            try:
                records = measure_files(info, cache_dir, work_dir, meas_cache,
                                        args.keep_extract, args.refresh)
                rep = build_report(info, records)
                if not args.skip_kernel_totals:
                    # Supplementary, non-fatal: a totals failure must not drop the
                    # (primary) Rust breakdown for this release. The renderer
                    # treats kernel_code == 0 as "share unavailable".
                    try:
                        totals = measure_kernel_totals(
                            info, cache_dir, work_dir, meas_cache,
                            args.keep_extract, args.refresh)
                        rep.kernel_files = totals["total"]["files"]
                        rep.kernel_code = totals["total"]["code"]
                        rep.kernel_comment = totals["total"]["comment"]
                        rep.kernel_blank = totals["total"]["blank"]
                        rep.languages = totals["languages"]
                    except Exception as e:  # noqa: BLE001
                        print(f"    !! kernel totals failed: {e}", file=sys.stderr)
                reports.append(rep)
            except Exception as e:  # noqa: BLE001
                print(f"    !! failed: {e}", file=sys.stderr)

        cloc_ver = subprocess.run(
            ["cloc", "--version"], capture_output=True, text=True).stdout.strip()
        payload = {
            "generated_utc": os.environ.get("RK_BUILD_DATE", ""),
            "cloc_version": cloc_ver,
            "floor": args.floor,
            "source": CDN,
            "category_reference": [
                {"category": c, "purpose": p} for c, p in CATEGORY_REFERENCE
            ],
            "versions": [asdict(r) for r in reports],
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2))
        print(f"[*] wrote {out_path} ({len(reports)} versions)")
        return 0
    finally:
        # Clean up only the scratch dir we created ourselves.
        if created_work_dir and not args.keep_extract:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
