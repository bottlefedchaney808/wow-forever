#!/usr/bin/env python3
"""Build deterministic data-version hashes and Wowhead ID migrations.

Only the Python standard library is used. Data files are hashed individually;
tile contents are folded into per-continent tile-pack hashes so the manifest
stays compact while still changing whenever a tile or tile path changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

WOWHEAD_DATA_VERSION = 14
DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_TILE_DIR = Path(__file__).resolve().parent / "tiles"
# Every dataset the manifest pins, with the window variable its file must
# define. routes/voyages joined the set in the tree-16 refresh (Task 9);
# they are OPTIONAL — the September generation ships without them, and a
# missing optional dataset gets a null-hash entry so the manifest schema
# names it explicitly.
MANIFEST_DATASETS = (
    ("data/places.js", "WH_PLACES", False),
    ("data/pois.js", "WH_POIS", False),
    ("data/nodes.js", "WH_NODES", False),
    ("data/routes.js", "WH_ROUTES", True),
    ("data/voyages.js", "WH_VOYAGES", True),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_manifest(root: Path | str) -> dict[str, Any]:
    """Return a deterministic manifest for data files and tile packs under root."""
    root = Path(root).resolve()
    data_dir = root / "data"
    tile_dir = root / "tiles"
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")
    if not tile_dir.is_dir():
        raise FileNotFoundError(f"Tile directory not found: {tile_dir}")

    data_files = []
    for path in sorted(p for p in data_dir.rglob("*") if p.is_file()):
        data_files.append({"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)})
    # The manifest explicitly names every dataset (Task 9 routes/voyages
    # guard). Required files must exist and define their window variable;
    # an absent optional dataset is named with a null hash.
    listed = {entry["path"] for entry in data_files}
    for relpath, variable, optional in MANIFEST_DATASETS:
        file_path = root / relpath
        if file_path.is_file():
            _parse_js_data(file_path, variable)
            if relpath not in listed:
                data_files.append({"path": relpath, "sha256": sha256_file(file_path)})
        elif optional:
            data_files.append({"path": relpath, "sha256": None})
        else:
            raise FileNotFoundError(f"required dataset missing: {relpath}")
    data_files.sort(key=lambda entry: entry["path"])

    packs: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for path in sorted(p for p in tile_dir.rglob("*") if p.is_file()):
        relative = path.relative_to(tile_dir)
        pack = relative.parts[0] if len(relative.parts) > 1 else "_root"
        packs[pack].append((relative.as_posix(), sha256_file(path)))

    tile_packs = {}
    for pack in sorted(packs):
        # Include both paths and content hashes; the individual tiles are never
        # emitted in the manifest, only in the pack's aggregate digest.
        digest = hashlib.sha256()
        for relpath, file_hash in sorted(packs[pack]):
            digest.update(relpath.encode("utf-8"))
            digest.update(b"\0")
            digest.update(file_hash.encode("ascii"))
            digest.update(b"\n")
        tile_packs[pack] = {"file_count": len(packs[pack]), "sha256": digest.hexdigest()}
    # Preserve empty pack directories too: directory layout is part of the data version.
    for path in sorted(p for p in tile_dir.rglob("*") if p.is_dir()):
        relative = path.relative_to(tile_dir)
        pack = relative.parts[0]
        tile_packs.setdefault(pack, {"file_count": 0, "sha256": hashlib.sha256(b"").hexdigest()})

    content = {
        "manifest_format": 1,
        "wowhead_data_version": WOWHEAD_DATA_VERSION,
        "data_files": data_files,
        "tile_packs": tile_packs,
    }
    content["dataset_version"] = hashlib.sha256(_canonical_json(content)).digest()[:8].hex()
    return content


def _parse_js_data(path: Path, variable: str) -> Any:
    text = path.read_text(encoding="utf-8").lstrip("\ufeff")
    match = re.match(r"\s*window\." + re.escape(variable) + r"\s*=\s*", text)
    if not match:
        raise ValueError(f"Expected window.{variable}= JSON assignment in {path}")
    payload = text[match.end():].strip()
    if payload.endswith(";"):
        payload = payload[:-1]
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(text.casefold().split())


def _coordinates(item: dict[str, Any]) -> tuple[float, float]:
    ll = item.get("ll")
    if isinstance(ll, list) and len(ll) >= 2:
        try:
            return float(ll[0]), float(ll[1])
        except (TypeError, ValueError):
            pass
    return 0.0, 0.0


def _load_entities(root: Path) -> list[dict[str, Any]]:
    data = root / "data"
    places = _parse_js_data(data / "places.js", "WH_PLACES")
    pois = _parse_js_data(data / "pois.js", "WH_POIS")
    entities: list[dict[str, Any]] = []
    for group in ("zones", "landmarks"):
        for item in places.get(group, []):
            name = item.get("n", "")
            entities.append({
                "kind": group[:-1] if group.endswith("s") else group,
                "name": name,
                "category": str(item.get("c", "")),
                "identity_key": f"{group[:-1]}|{_normalize(name)}|{_normalize(item.get('c', ''))}",
                "coordinates": _coordinates(item),
                "wowhead_id": item.get("id", item.get("npc")),
            })
    for item in pois:
        name = item.get("n", "")
        category = str(item.get("c", ""))
        entities.append({
            "kind": "poi",
            "name": name,
            "category": category,
            "identity_key": f"poi|{_normalize(name)}|{_normalize(category)}",
            "coordinates": _coordinates(item),
            "wowhead_id": item.get("npc", item.get("id")),
            "side": item.get("side"),
        })

    # Duplicate labels/categories receive coordinate-ordered occurrence numbers,
    # avoiding dependency on source-array ordering in a regenerated dataset.
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entity in entities:
        grouped[entity["identity_key"]].append(entity)
    for identity, group in grouped.items():
        group.sort(key=lambda entity: (entity["coordinates"], entity.get("side", -1), entity.get("wowhead_id") or -1))
        for occurrence, entity in enumerate(group):
            entity["occurrence"] = occurrence
            entity["stable_id"] = f"{entity['kind']}:{hashlib.sha256(f'{identity}|{occurrence}'.encode('utf-8')).hexdigest()[:16]}"
    return sorted(entities, key=lambda entity: entity["stable_id"])


def build_id_map(root: Path | str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return current stable IDs and the old-to-current Wowhead ID migration."""
    root = Path(root).resolve()
    entities = _load_entities(root)
    previous_by_stable = {
        item.get("stable_id"): item
        for item in (previous or {}).get("entities", [])
        if item.get("stable_id")
    }
    migration = []
    for entity in entities:
        old = previous_by_stable.get(entity["stable_id"])
        old_id = old.get("wowhead_id") if old else None
        new_id = entity.get("wowhead_id")
        if old and old_id != new_id:
            migration.append({
                "stable_id": entity["stable_id"],
                "kind": entity["kind"],
                "name": entity["name"],
                "old_wowhead_id": old_id,
                "new_wowhead_id": new_id,
            })
    return {
        "wowhead_data_version": WOWHEAD_DATA_VERSION,
        "entities": [{key: value for key, value in entity.items() if key != "coordinates"}
                     for entity in entities],
        "migration": {"mappings": migration},
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent,
                        help="dataset root containing data/ and tiles/ (default: script directory)")
    parser.add_argument("--manifest", type=Path, help="manifest output (default: ROOT/version-manifest.json)")
    parser.add_argument("--id-map", type=Path, help="current ID map output (default: ROOT/id-map.json)")
    parser.add_argument("--migration", type=Path, help="migration output (default: ROOT/id-migration.json)")
    parser.add_argument("--previous-id-map", type=Path,
                        help="prior id-map.json; defaults to existing ROOT/id-map.json when present")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    manifest_path = (args.manifest or root / "version-manifest.json").resolve()
    id_map_path = (args.id_map or root / "id-map.json").resolve()
    migration_path = (args.migration or root / "id-migration.json").resolve()
    previous_path = args.previous_id_map.resolve() if args.previous_id_map else id_map_path

    try:
        manifest = build_manifest(root)
        previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.is_file() else None
        current = build_id_map(root, previous)
        _write_json(manifest_path, manifest)
        _write_json(id_map_path, current)
        _write_json(migration_path, {
            "from_wowhead_data_version": previous.get("wowhead_data_version") if previous else None,
            "to_wowhead_data_version": WOWHEAD_DATA_VERSION,
            **current["migration"],
        })
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"version_manifest: {exc}", file=sys.stderr)
        return 2
    print(f"Dataset version: {manifest['dataset_version']}")
    print(f"Hashed {len(manifest['data_files'])} data files and {len(manifest['tile_packs'])} tile packs")
    print(f"Wrote {manifest_path}, {id_map_path}, {migration_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
