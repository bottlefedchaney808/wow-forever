#!/usr/bin/env python3
"""Dataset writers for the world-map scrape (Task 8).

Emits the shipped `window.WH_*` file formats byte-compatibly:

- Terminator (verified from the shipped files, tail -c 50 of
  data/places.js, data/pois.js, data/nodes.js — all identical): the file
  ENDS with `;` and has NO trailing newline. `TERMINATOR` encodes that.
- `write_places` serializes with compact separators (`,`, `:`) because the
  shipped places.js is compact; pois/nodes use json.dumps default spacing.
  All writers use ensure_ascii=False.
- The shipped places.js record schema is {n, ll, mz}. `mz` is NOT present in
  the tree-16 endpoint payload (probe report 2026-10-30); the adapter must
  not invent it. Writers pass through whatever keys the caller supplies.

`build_all(captures_dir, out_dir)` is the end-to-end path used by
adapt_captures.py: it loads the five capture files pinned in
scrape/ENDPOINTS.md, applies the endpoint->writer mapping/hardening from
adapt_captures (documented there), enforces the BASELINE count guard
BEFORE writing anything, writes only into out_dir, and returns the counts.

Baseline guard: each capture's raw counts must be >= 90% of the
2026-09-20 shipped baseline (places records, pois records, node points)
and the 2026-10-29 audit floors for routes/voyages (no shipped file for
those; the probe audit counts 160/14 are the only defensible floors).
Any shortfall raises SystemExit before a single file is written.
"""

from __future__ import annotations

import json
from pathlib import Path

# 2026-09-20 shipped dataset counts (index.html footer / README baseline):
#   305 places records (49 zones + 256 landmarks), 1,285 POIs, 17,637 node
#   points. routes/voyages have no shipped file; their floors are the
#   2026-10-29 audit counts (160 routes, 14 voyages) recorded in ENDPOINTS.md.
BASELINE = {
    "places": 305,
    "pois": 1285,
    "nodes": 17637,
    "routes": 160,
    "voyages": 14,
}

MIN_RATIO = 0.90

# Capture filenames pinned in scrape/ENDPOINTS.md (extracted from the one
# world-map document; not separate fetches).
CAPTURE_FILES = {
    "places": "places.json",
    "pois": "pois.json",
    "nodes": "nodes.json",
    "routes": "routes.json",
    "voyages": "voyages.json",
}

# Exact file terminator copied from the shipped files: trailing ';' only,
# no trailing newline (verified: tail -c 50 ends `...};` at EOF).
TERMINATOR = ";"

PREFIXES = {
    "places": "window.WH_PLACES=",
    "pois": "window.WH_POIS=",
    "nodes": "window.WH_NODES=",
    "routes": "window.WH_ROUTES=",
    "voyages": "window.WH_VOYAGES=",
}


def _emit(name: str, obj, separators=None) -> str:
    payload = json.dumps(obj, ensure_ascii=False, separators=separators)
    return PREFIXES[name] + payload + TERMINATOR


def write_places(obj) -> str:
    """places.js body: compact separators to match the shipped file."""
    return _emit("places", obj, separators=(",", ":"))


def write_pois(obj) -> str:
    return _emit("pois", obj)


def write_nodes(obj) -> str:
    return _emit("nodes", obj)


def write_routes(obj) -> str:
    return _emit("routes", obj)


def write_voyages(obj) -> str:
    return _emit("voyages", obj)


def _load_captures(captures_dir: Path) -> dict:
    captures = {}
    for name, filename in CAPTURE_FILES.items():
        path = captures_dir / filename
        if not path.is_file():
            raise SystemExit(f"build_all: missing capture {path}")
        captures[name] = json.loads(path.read_text(encoding="utf-8"))
    return captures


def _capture_counts(captures: dict) -> dict:
    """Raw capture counts used by the baseline guard (ENDPOINTS.md basis):
    places/pois records, node POINTS, routes/voyages records."""
    return {
        "places": len(captures["places"]),
        "pois": len(captures["pois"]),
        "nodes": sum(len(group["points"]) for group in captures["nodes"]),
        "routes": len(captures["routes"]),
        "voyages": len(captures["voyages"]),
    }


def _check_baseline(capture_counts: dict) -> None:
    for name, baseline in BASELINE.items():
        got = capture_counts[name]
        floor = baseline * MIN_RATIO
        if got < floor:
            raise SystemExit(
                f"build_all: capture {name}={got} below 90% of 2026-09-20 "
                f"baseline {baseline} (floor {floor:.1f}) — refusing to write"
            )


def build_all(captures_dir, out_dir) -> dict:
    """Map the five captures to writer inputs, guard, write, return counts.

    Mapping/hardening (kind split, pixel->normalized coords, half-open
    rejection, (n, ll) dedupe) lives in adapt_captures; the guard here runs
    on RAW capture counts before any file is written.
    """
    captures_dir = Path(captures_dir)
    out_dir = Path(out_dir)
    captures = _load_captures(captures_dir)
    _check_baseline(_capture_counts(captures))
    import adapt_captures  # after the guard: writers stay importable standalone
    prepared = adapt_captures.prepare_all(captures)

    writers = {
        "places": write_places,
        "pois": write_pois,
        "nodes": write_nodes,
        "routes": write_routes,
        "voyages": write_voyages,
    }
    for name, obj in prepared["objects"].items():
        (out_dir / f"{name}.js").write_text(writers[name](obj), encoding="utf-8")
    return prepared["counts"]


if __name__ == "__main__":
    raise SystemExit("write_datasets: library module; run scrape/adapt_captures.py")
