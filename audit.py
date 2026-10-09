#!/usr/bin/env python3
"""Integrity audit for the offline WoW Forever map assets."""

from __future__ import annotations

import json
import math
import re
import struct
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CANVAS = (44544, 29696)
TILE_SIZE = 256
BASE_ZOOM = 7
CONTINENTS = {
    "kalimdor": (25088, 28672),
    "eastern-kingdoms": (11776, 21504),
}
DATA_FILES = {
    "places": ("data/places.js", "WH_PLACES"),
    "pois": ("data/pois.js", "WH_POIS"),
    "nodes": ("data/nodes.js", "WH_NODES"),
}

# A small set of well-known settlements/landmarks paired with their zone-label
# anchor. Zones are labels, not polygons, so this deliberately uses a generous
# 0.09 normalized-coordinate tolerance as a gross placement sanity check.
LANDMARK_ZONE_CHECKS = {
    "Bloodhoof Village": "Mulgore",
    "Camp Narache": "Mulgore",
    "Razor Hill": "Durotar",
    "The Den": "Durotar",
    "Sen'jin Village": "Durotar",
    "The Crossroads": "The Barrens",
    "Ratchet": "The Barrens",
    "Astranaar": "Ashenvale",
    "Stonetalon Peak": "Stonetalon Mountains",
    "Freewind Post": "Thousand Needles",
    "Gadgetzan": "Tanaris",
    "Camp Mojache": "Feralas",
    "Theramore Isle": "Dustwallow Marsh",
    "Everlook": "Winterspring",
    "Auberdine": "Darkshore",
    "Nijel's Point": "Desolace",
    "Tarren Mill": "Hillsbrad Foothills",
    "Southshore": "Hillsbrad Foothills",
    "Eastwall Tower": "Eastern Plaguelands",
    "Chillwind Camp": "Western Plaguelands",
}


def expected_grid_dimensions(continent: str, zoom: int) -> tuple[int, int]:
    """Maximum tile columns/rows at a zoom, rounding partial edge tiles up."""
    scale = 2 ** (BASE_ZOOM - zoom)
    # These are the defined z7 map grids; coarser zooms scale that grid down.
    columns = 100 if continent == "kalimdor" else 46
    rows = 112 if continent == "kalimdor" else 84
    return (math.ceil(columns / scale), math.ceil(rows / scale))


def parse_js_assignment(text: str, variable: str) -> Any:
    """Read the JSON literal assigned to a known window variable."""
    # anchor to start of file to avoid matching a later occurrence
    text_stripped = text.lstrip()
    match = re.search(r"(?:window\.)?" + re.escape(variable) + r"\s*=\s*", text_stripped)
    if not match:
        raise ValueError(f"assignment {variable} not found")
    payload = text[match.end():].strip()
    if payload.endswith(";"):
        payload = payload[:-1]
    return json.loads(payload)


def _coordinate_issues(record: Any, label: str) -> list[str]:
    if not isinstance(record, dict):
        return [f"{label}: record is not an object"]
    ll = record.get("ll")
    if not isinstance(ll, list) or len(ll) != 2:
        return []
    try:
        lat, lng = float(ll[0]), float(ll[1])
    except (TypeError, ValueError):
        return [f"{label}: invalid ll coordinates {ll!r}"]
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return [f"{label}: non-finite ll coordinates {ll!r}"]
    cx, cy = lng * CANVAS[0], (1 - lat) * CANVAS[1]
    if not (0 <= cx < CANVAS[0] and 0 <= cy < CANVAS[1]):
        return [f"{label}: out of bounds coordinates {ll!r} -> ({cx:.1f}, {cy:.1f})"]
    return []


def audit_dataset(data: Any, name: str) -> tuple[int, list[str]]:
    """Count entries and find exact duplicate records and invalid coordinates."""
    issues: list[str] = []
    if name == "places" and isinstance(data, dict):
        # Zone and landmark records with equal JSON objects are duplicates,
        # regardless of their respective list position.
        records = [item for group in ("zones", "landmarks") for item in data.get(group, [])]
    elif name == "pois" and isinstance(data, list):
        records = data
    elif name == "nodes" and isinstance(data, dict):
        records = data
    else:
        records = data if isinstance(data, list) else []

    seen: set[str] = set()
    count = 0
    def visit(record: Any, label: str) -> None:
        nonlocal count
        count += 1
        try:
            key = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        except (TypeError, ValueError):
            key = repr(record)
        if key in seen:
            issues.append(f"{label}: duplicate entry")
        seen.add(key)
        issues.extend(_coordinate_issues(record, label))

    if name == "nodes" and isinstance(data, dict):
        for node_key, node in data.items():
            for index, point in enumerate(node.get("pts", [])):
                visit({"n": node.get("n"), "ll": point}, f"nodes.{node_key}[{index}]")
    else:
        for index, record in enumerate(records):
            visit(record, f"{name}[{index}]")
    return count, issues


def check_tile_tree(tiles_root: Path) -> tuple[dict[str, dict[int, int]], list[str]]:
    """Count tiles at every zoom and ensure tile coordinates fit the expected grid."""
    counts: dict[str, dict[int, int]] = {}
    issues: list[str] = []
    for continent in CONTINENTS:
        counts[continent] = {}
        cont_dir = tiles_root / continent
        if not cont_dir.is_dir():
            issues.append(f"missing continent tile directory: {cont_dir}")
            continue
        for zoom_dir in sorted((p for p in cont_dir.iterdir() if p.is_dir()), key=lambda p: int(p.name) if p.name.isdigit() else -1):
            if not zoom_dir.name.isdigit():
                issues.append(f"unexpected zoom directory: {zoom_dir}")
                continue
            zoom = int(zoom_dir.name)
            max_x, max_y = expected_grid_dimensions(continent, zoom)
            tile_files = sorted(zoom_dir.glob("*.webp"))
            counts[continent][zoom] = len(tile_files)
            if not tile_files:
                issues.append(f"{continent} z{zoom}: no WebP tiles")
            for tile in tile_files:
                match = re.fullmatch(r"(\d+)_(\d+)\.webp", tile.name)
                if not match:
                    issues.append(f"{tile}: unexpected tile filename")
                    continue
                y, x = map(int, match.groups())
                if not (x < max_x and y < max_y):
                    issues.append(f"{tile}: tile index outside z{zoom} grid ({max_x}x{max_y})")
    return counts, issues


def check_webp_magic(tiles_root: Path) -> tuple[int, list[str]]:
    checked = 0
    issues: list[str] = []
    for tile in sorted(tiles_root.rglob("*.webp")):
        checked += 1
        try:
            with tile.open("rb") as stream:
                header = stream.read(12)
            if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WEBP":
                issues.append(f"{tile}: invalid WebP RIFF/WEBP magic bytes")
        except OSError as exc:
            issues.append(f"{tile}: unable to read ({exc})")
    if checked == 0:
        issues.append(f"no .webp tiles found under {tiles_root}")
    return checked, issues


def spot_check_landmarks(places: dict[str, Any]) -> tuple[int, list[str]]:
    zones = {zone.get("n"): zone.get("ll") for zone in places.get("zones", [])}
    landmarks = {item.get("n"): item.get("ll") for item in places.get("landmarks", [])}
    checked = 0
    issues: list[str] = []
    for landmark_name, zone_name in LANDMARK_ZONE_CHECKS.items():
        point = landmarks.get(landmark_name)
        zone = zones.get(zone_name)
        if point is None:
            issues.append(f"landmark spot-check: missing {landmark_name}")
            continue
        if zone is None:
            issues.append(f"landmark spot-check: missing zone {zone_name}")
            continue
        checked += 1
        if len(point) != 2 or len(zone) != 2 or any(abs(float(point[i]) - float(zone[i])) > 0.09 for i in (0, 1)):
            issues.append(f"landmark spot-check: {landmark_name} is implausibly far from {zone_name}")
    if checked < 20:
        issues.append(f"landmark spot-check: checked only {checked}/20 expected landmarks")
    return checked, issues


def run_audit(root: Path = ROOT) -> int:
    failed = False

    grid_counts, grid_issues = check_tile_tree(root / "tiles")
    for continent in CONTINENTS:
        zooms = grid_counts.get(continent, {})
        if zooms:
            details = ", ".join(
                f"z{zoom}: {count} tiles within {expected_grid_dimensions(continent, zoom)[0]}x{expected_grid_dimensions(continent, zoom)[1]} grid"
                for zoom, count in sorted(zooms.items())
            )
            print(f"{'FAIL' if grid_issues else 'PASS'} tile grid {continent}: {details}")
    _report("tile grid details", grid_issues)
    failed |= bool(grid_issues)

    tile_count, magic_issues = check_webp_magic(root / "tiles")
    _report(f"WebP magic ({tile_count} tiles)", magic_issues)
    failed |= bool(magic_issues)

    loaded: dict[str, Any] = {}
    for name, (relpath, variable) in DATA_FILES.items():
        try:
            loaded[name] = parse_js_assignment((root / relpath).read_text(encoding="utf-8"), variable)
            count, issues = audit_dataset(loaded[name], name)
            _report(f"{name} data ({count} entries)", issues)
            failed |= bool(issues)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _report(f"{name} data", [str(exc)])
            failed = True

    if "places" in loaded:
        checked, issues = spot_check_landmarks(loaded["places"])
        _report(f"landmark-zone spot-check ({checked}/20)", issues)
        failed |= bool(issues)
    return 1 if failed else 0


def _report(label: str, issues: list[str]) -> None:
    print(f"{'FAIL' if issues else 'PASS'} {label}")
    for issue in issues[:20]:
        print(f"  - {issue}")
    if len(issues) > 20:
        print(f"  - ... and {len(issues) - 20} more issue(s)")


if __name__ == "__main__":
    sys.exit(run_audit())
