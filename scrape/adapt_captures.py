#!/usr/bin/env python3
"""adapt_captures.py — map scrape/raw captures (Task 7) to writer inputs.

Endpoint_key -> WH key table (field mapping per scrape/ENDPOINTS.md):

  places.json  -> window.WH_PLACES (dict of two arrays)
    name        -> n
    x, y        -> ll                (pixels -> normalized; formulas below)
    kind        -> array choice ONLY, never a stored field:
                   kind in {zone, capital}  -> "zones"      (50 records live)
                   kind in {town, landmark} -> "landmarks"  (276 records live)
                   kind == subzone          -> NOT SHIPPED (ENDPOINTS.md: 0
                   name overlap with shipped zones/landmarks; the reason
                   894 != 49+256). No other kind filter is invented.
    mz          -> NOT present in the tree-16 payload (probe report 2026-10-30);
                   NEVER invented from uiMap/area/side. The shipped schema
                   carries one constant per array (verified over the shipped
                   file: all 49 zones mz 0, all 256 landmarks mz 4), so zones
                   emit mz:0 and landmarks emit mz:4 as the array-level default.
    rect, area, uiMap, side, levels, minZoom, roomZoom, new -> dropped (not in
                   the shipped record schema).

  pois.json    -> window.WH_POIS (list)
    name        -> n
    category    -> c
    x, y        -> ll
    npc         -> npc (int, may be null as shipped)
    side        -> side
    model, body, quests, levels, new, newLevel, instance, item, image, paths,
    wraps, group, groupName, groupWraps, slot -> dropped (not in shipped pois)

  nodes.json   -> window.WH_NODES (dict keyed "<prefix>-<slug>", e.g.
                  "herb-arthas-tears", preserving shipped slug style)
    category    -> dict key
    points[i][0], points[i][1] -> pts[i] = [lat, lng]
    points[i][2] -> SPAWN INDEX (0-9), NOT a coordinate (probe report) —
                   dropped; never treated as a coordinate.
    n           -> display name from scrape/raw/categories.json (key ==
                   category; 99/99 coverage verified; matches shipped names)

  routes.json  -> window.WH_ROUTES (list)
    path, category, vessel, color -> passthrough
    points[i] = [x, y] (pixels, no third component) -> [[lat, lng], ...]

  voyages.json -> window.WH_VOYAGES (list)
    path, vessel, legs, yards, dwell, rides -> passthrough
    stops[i].x, stops[i].y -> stops[i].ll = [lat, lng]; name/side/dwell kept

Coordinate formulas (endpoint x, y are canvas PIXELS — probe report):

    CANVAS_WIDTH  = 44544
    CANVAS_HEIGHT = 29696   # the OLD canvas height (README / audit.py CANVAS).
                            # Live config canvasHeight is 37888 and does NOT
                            # reproduce shipped coords (probe report).
    lng = x / 44544
    lat = (29696 - y) / 29696
    ll  = [round(lat, 6), round(lng, 6)]

  Verified before use: for all 49 shipped zone names, these formulas
  reproduce shipped ll exactly (6 decimals).

Half-open acceptance rule (audit.py bound `0 <= cx < CANVAS[0] and
0 <= cy < CANVAS[1]` with cx = lng*44544, cy = (1-lat)*29696):

    keep only 0 <= lng < 1 and 0 < lat <= 1
    out-of-range points are REJECTED, never clamped (lat == 0 and lng == 1
    fail the canvas test).

Dedupe (plan Task 9 Step 3): places use (n, ll), first occurrence wins.
Same landmark name at a different coordinate is a second entrance
(ENDPOINTS.md: 13 names, 2 records) and is kept. Pois are NOT collapsed on
(n, ll) alone: 573/4469 share a name and pixel but differ in category, npc,
or side (innkeeper vs quest-giver). audit.py flags only full-record
identity, so pois/routes/voyages dedupe on canonical JSON of the shipped
record. Collapsing those pois would delete 12.8% of a valid capture.

STOP: coordinate rejections only (never clamps). If out-of-range points
exceed 1% of a dataset, --write REFUSES and leaves data/ untouched.
Intentional exact-duplicate removal is reported separately and does not
trip the ceiling — the 7 identical landmark (n, ll) copies are 2.15% of
zone+town+landmark records and would otherwise block a clean capture.
--dry-run prints counts, coord rejections, and dedupe counts. Count floors
live only in write_datasets.BASELINE; audit.py has no count baselines.

Usage:
    /usr/bin/python3 scrape/adapt_captures.py --dry-run   # counts + drops only
    /usr/bin/python3 scrape/adapt_captures.py --write     # temp -> validate -> mv into data/
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrape"))

import write_datasets as wd

RAW = ROOT / "scrape" / "raw"
DATA = ROOT / "data"

CANVAS_WIDTH = 44544
CANVAS_HEIGHT = 29696

STOP_RATIO = 0.01  # dropped points > 1% of a dataset => --write refuses

ZONE_KINDS = ("zone", "capital")
LANDMARK_KINDS = ("town", "landmark")
# shipped array-level schema constants for the `mz` key (payload lacks it)
MZ_ZONES = 0
MZ_LANDMARKS = 4

DATASETS = ("places", "pois", "nodes", "routes", "voyages")
VARIABLES = {"places": "WH_PLACES", "pois": "WH_POIS", "nodes": "WH_NODES",
             "routes": "WH_ROUTES", "voyages": "WH_VOYAGES"}


def normalize(x, y) -> tuple[float, float]:
    """Canvas pixels -> shipped [lat, lng] 6-decimal pair."""
    return round((CANVAS_HEIGHT - y) / CANVAS_HEIGHT, 6), round(x / CANVAS_WIDTH, 6)


def in_half_open(ll) -> bool:
    lat, lng = ll
    return 0 <= lng < 1 and 0 < lat <= 1


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _node_names() -> dict[str, str]:
    cats = _load_json(RAW / "categories.json")
    return {c["key"]: c["name"] for c in cats}


def _record_identity(record: dict) -> str:
    """audit.py's own duplicate identity (canonical sorted JSON)."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def prepare_all(captures: dict, dedupe: str = "plan", max_drop: float = STOP_RATIO) -> dict:
    """Hardened writer inputs + counts + drop report (STOP enforced by caller).

    dedupe="plan" (default): places use (n, ll). Different coordinates for the
    same name are kept. Pois use full-record identity (category/npc/side are
    part of the record — see module docstring). routes/voyages have no `n`;
    their identity is the full record.
    dedupe="audit": same full-record identity audit.py flags, including places.
    max_drop: STOP ratio on coordinate rejections only. The plan's 1% floor is
    the default; only a controller-authorized --max-drop relaxes it.
    """
    place_key = _record_identity if dedupe == "audit" else (lambda r: (r["n"], tuple(r["ll"])))
    names = _node_names()
    # coord = out-of-range rejections (STOP numerator). deduped = intentional copies.
    coord = {"zones": 0, "landmarks": 0, "pois": 0, "nodes": 0, "routes": 0, "voyages": 0}
    deduped = {"zones": 0, "landmarks": 0, "pois": 0, "nodes": 0, "routes": 0, "voyages": 0}
    totals = {"zones": 0, "landmarks": 0, "pois": len(captures["pois"]),
              "nodes": sum(len(g["points"]) for g in captures["nodes"]),
              "routes": len(captures["routes"]), "voyages": len(captures["voyages"])}

    # ---- places ----
    zones = []
    landmarks = []
    seen = {"zones": set(), "landmarks": set()}
    for p in captures["places"]:
        kind = p.get("kind")
        if kind in ZONE_KINDS:
            bucket = "zones"
        elif kind in LANDMARK_KINDS:
            bucket = "landmarks"
        else:
            continue  # subzone (and any other kind): not shipped
        totals[bucket] += 1
        record = {"n": p["name"], "ll": list(normalize(p["x"], p["y"])),
                  "mz": MZ_ZONES if bucket == "zones" else MZ_LANDMARKS}
        if not in_half_open(record["ll"]):
            coord[bucket] += 1
            continue
        key = place_key(record)
        if key in seen[bucket]:
            deduped[bucket] += 1
            continue
        seen[bucket].add(key)
        (zones if bucket == "zones" else landmarks).append(record)

    # ---- pois ----
    pois = []
    seen_poi = set()
    for p in captures["pois"]:
        record = {
            "n": p["name"],
            "c": p["category"],
            "ll": list(normalize(p["x"], p["y"])),
            "npc": p.get("npc"),
            "side": p.get("side"),
        }
        if not in_half_open(record["ll"]):
            coord["pois"] += 1
            continue
        key = _record_identity(record)
        if key in seen_poi:
            deduped["pois"] += 1
            continue
        seen_poi.add(key)
        pois.append(record)

    # ---- nodes ----
    nodes = {}
    for group in captures["nodes"]:
        key = group["category"]
        pts = []
        group_seen = set()
        for pt in group["points"]:
            ll = normalize(pt[0], pt[1])  # pt[2] is a spawn index, not a coord
            if not in_half_open(ll):
                coord["nodes"] += 1
                continue
            if ll in group_seen:
                deduped["nodes"] += 1
                continue
            group_seen.add(ll)
            pts.append(list(ll))
        nodes[key] = {"n": names.get(key, key), "pts": pts}

    # ---- routes ----
    routes = []
    seen_route = set()
    for r in captures["routes"]:
        rid = json.dumps(r, sort_keys=True, ensure_ascii=False)
        if rid in seen_route:
            deduped["routes"] += 1
            continue
        seen_route.add(rid)
        pts = []
        for pt in r["points"]:
            ll = normalize(pt[0], pt[1])
            if not in_half_open(ll):
                coord["routes"] += 1
                continue
            pts.append(list(ll))
        routes.append({
            "path": r.get("path"),
            "category": r.get("category"),
            "vessel": r.get("vessel"),
            "color": r.get("color"),
            "points": pts,
        })

    # ---- voyages ----
    voyages = []
    seen_voyage = set()
    for v in captures["voyages"]:
        vid = json.dumps(v, sort_keys=True, ensure_ascii=False)
        if vid in seen_voyage:
            deduped["voyages"] += 1
            continue
        seen_voyage.add(vid)
        stops = []
        for st in v["stops"]:
            ll = normalize(st["x"], st["y"])
            if not in_half_open(ll):
                coord["voyages"] += 1
                continue
            stops.append({"name": st.get("name"), "side": st.get("side"),
                          "dwell": st.get("dwell"), "ll": list(ll)})
        voyages.append({
            "path": v.get("path"),
            "vessel": v.get("vessel"),
            "stops": stops,
            "legs": v.get("legs"),
            "yards": v.get("yards"),
            "dwell": v.get("dwell"),
            "rides": v.get("rides"),
        })

    counts = {
        "places": len(zones) + len(landmarks),
        "pois": len(pois),
        "nodes": sum(len(g["pts"]) for g in nodes.values()),
        "routes": len(routes),
        "voyages": len(voyages),
    }
    # Coordinate rejections are the STOP numerator. Exact-duplicate removal
    # is reported beside them and is not a scrape failure.
    drop_report = {}
    for name in DATASETS:
        if name == "places":
            rejected = coord["zones"] + coord["landmarks"]
            copied = deduped["zones"] + deduped["landmarks"]
            total = totals["zones"] + totals["landmarks"]
        else:
            rejected = coord[name]
            copied = deduped[name]
            total = totals[name]
        drop_report[name] = {"dropped": rejected, "deduped": copied, "total": total,
                             "pct": rejected / total if total else 0.0}
    return {
        "objects": {
            "places": {"zones": zones, "landmarks": landmarks},
            "pois": pois,
            "nodes": nodes,
            "routes": routes,
            "voyages": voyages,
        },
        "counts": counts,
        "drops": drop_report,
    }


def refused_datasets(drop_report: dict, max_drop: float = STOP_RATIO) -> list[str]:
    return [name for name in DATASETS if drop_report[name]["pct"] > max_drop]


def load_captures() -> dict:
    return wd._load_captures(RAW)


def validate(tmp_dir: Path) -> list[str]:
    """Re-parse the generated temp files with audit.py's own rules; no clamping."""
    import audit

    issues: list[str] = []
    for name in DATASETS:
        path = tmp_dir / f"{name}.js"
        try:
            data = audit.parse_js_assignment(path.read_text(encoding="utf-8"), VARIABLES[name])
        except (ValueError, json.JSONDecodeError) as exc:
            issues.append(f"{name}: {exc}")
            continue
        _count, found = audit.audit_dataset(data, name)
        issues.extend(found)
    return issues


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print counts + drop report only")
    mode.add_argument("--write", action="store_true", help="temp -> validate -> mv into data/")
    parser.add_argument("--dedupe", choices=("plan", "audit"), default="plan",
                        help="dedupe key: 'plan' = (n, ll) [default]; 'audit' = "
                             "only what audit.py flags as a duplicate record")
    parser.add_argument("--max-drop", type=float, default=STOP_RATIO, metavar="RATIO",
                        help="STOP ceiling per dataset (plan floor 0.01); raising "
                             "it is a controller decision, not a clamp")
    args = parser.parse_args(argv)

    captures = load_captures()
    prepared = prepare_all(captures, dedupe=args.dedupe, max_drop=args.max_drop)

    print("counts:", json.dumps(prepared["counts"]))
    for name, info in prepared["drops"].items():
        print(f"drops:  {name:8s} coords {info['dropped']:5d}/{info['total']:5d} "
              f"= {100 * info['pct']:.3f}%  deduped {info['deduped']}")

    refused = refused_datasets(prepared["drops"], args.max_drop)
    if refused:
        detail = ", ".join(
            f"{name} {prepared['drops'][name]['dropped']}/{prepared['drops'][name]['total']} "
            f"({100 * prepared['drops'][name]['pct']:.2f}%)"
            for name in refused
        )
        print(f"adapt_captures: STOP — dropped points exceed {args.max_drop:.0%} of a dataset: {detail} "
              "— no clamping, no partial ship.", file=sys.stderr)
        if args.write:
            print("adapt_captures: refusing to write; data/ untouched.", file=sys.stderr)
            return 3
        print("adapt_captures: dry-run reports the STOP; --write would refuse.", file=sys.stderr)

    if args.dry_run:
        return 0

    # Task 8's count guard runs before anything is written (raw capture counts).
    wd._check_baseline(wd._capture_counts(captures))
    with tempfile.TemporaryDirectory(prefix="adapt_captures-") as tmp:
        tmp_dir = Path(tmp)
        writers = {"places": wd.write_places, "pois": wd.write_pois,
                   "nodes": wd.write_nodes, "routes": wd.write_routes,
                   "voyages": wd.write_voyages}
        for name, writer in writers.items():
            (tmp_dir / f"{name}.js").write_text(writer(prepared["objects"][name]), encoding="utf-8")
        issues = validate(tmp_dir)
        if issues:
            print("adapt_captures: validation FAILED, data/ untouched:", file=sys.stderr)
            for issue in issues[:20]:
                print(f"  - {issue}", file=sys.stderr)
            return 2
        import os
        import shutil
        # tempfile may land on another filesystem than data/; os.replace then
        # raises EXDEV. Stage beside the destination and replace in-place.
        for name in writers:
            dest = DATA / f"{name}.js"
            staged = dest.with_suffix(".js.swap")
            shutil.copy2(tmp_dir / f"{name}.js", staged)
            os.replace(staged, dest)
    print(f"wrote {len(writers)} datasets into {DATA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
