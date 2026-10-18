#!/usr/bin/env python3
"""Pack the project's XYZ WebP tiles into a PMTiles v3 archive.

No third-party packages are required. Tiles are indexed as standard PMTiles XYZ
addresses; metadata records the original continent to retain the distinction
between the project's two separate map coordinate spaces.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MAGIC = b"PMTiles"
VERSION = 3
HEADER_LEN = 127
ZOOM_MIN = 0
ZOOM_MAX = 8
COMPRESSION_NONE = 1
COMPRESSION_GZIP = 2
TILE_TYPE_WEBP = 4
DEFAULT_CONTIGS = ("kalimdor", "eastern-kingdoms")


@dataclass(frozen=True)
class Tile:
    z: int
    x: int
    y: int
    path: Path
    contig: str


@dataclass(frozen=True)
class Entry:
    tile_id: int
    offset: int
    length: int
    run_length: int = 1


def uvarint(value: int) -> bytes:
    """Encode an unsigned little-endian base-128 variable-length integer."""
    if value < 0:
        raise ValueError("varint value must be non-negative")
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def read_uvarint(data: bytes, offset: int) -> tuple[int, int]:
    value = shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        if shift > 63:
            raise ValueError("invalid varint")
    raise ValueError("truncated varint")


def zxy_to_tileid(z: int, x: int, y: int) -> int:
    """Convert XYZ to PMTiles' cumulative Hilbert TileID."""
    if z < 0 or x < 0 or y < 0 or x >= 1 << z or y >= 1 << z:
        raise ValueError(f"invalid XYZ coordinate: {z}/{x}/{y}")
    tile_id = (4 ** z - 1) // 3
    side = 1 << z
    tx, ty = x, y
    distance = 0
    scale = side // 2
    while scale:
        rx = 1 if tx & scale else 0
        ry = 1 if ty & scale else 0
        distance += scale * scale * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                tx = side - 1 - tx
                ty = side - 1 - ty
            tx, ty = ty, tx
        scale //= 2
    return tile_id + distance


def serialize_directory(entries: list[Entry]) -> bytes:
    """Serialize one PMTiles v3 directory (uncompressed)."""
    entries = sorted(entries, key=lambda entry: entry.tile_id)
    out = bytearray(uvarint(len(entries)))
    previous_id = 0
    for entry in entries:
        out += uvarint(entry.tile_id - previous_id)
        previous_id = entry.tile_id
    for entry in entries:
        out += uvarint(entry.run_length)
    for entry in entries:
        out += uvarint(entry.length)
    next_byte = 0
    for index, entry in enumerate(entries):
        if index and entry.offset == next_byte:
            out += uvarint(0)
        else:
            out += uvarint(entry.offset + 1)
        next_byte = entry.offset + entry.length
    return bytes(out)


def parse_directory(data: bytes) -> list[Entry]:
    """Decode a PMTiles directory to support tests and archive readers."""
    count, offset = read_uvarint(data, 0)
    tile_ids = []
    previous_id = 0
    for _ in range(count):
        delta, offset = read_uvarint(data, offset)
        previous_id += delta
        tile_ids.append(previous_id)
    run_lengths = []
    for _ in range(count):
        value, offset = read_uvarint(data, offset)
        run_lengths.append(value)
    lengths = []
    for _ in range(count):
        value, offset = read_uvarint(data, offset)
        lengths.append(value)
    entries = []
    previous_end = 0
    for index in range(count):
        encoded_offset, offset = read_uvarint(data, offset)
        tile_offset = previous_end if index and encoded_offset == 0 else encoded_offset - 1
        entries.append(Entry(tile_ids[index], tile_offset, lengths[index], run_lengths[index]))
        previous_end = tile_offset + lengths[index]
    if offset != len(data):
        raise ValueError("unexpected bytes after directory")
    return entries


def archive_xyz(tile: Tile) -> tuple[int, int, int]:
    """Namespace each continent in a disjoint half of the next zoom grid.

    Source z is preserved in the URL API by this reversible transform. PMTiles
    requires unique XYZ addresses, but the source sets share 66 z/x/y addresses.
    """
    archive_z = tile.z + 1
    x = tile.x + ((1 << tile.z) if tile.contig == "eastern-kingdoms" else 0)
    return archive_z, x, tile.y


def collect_tiles(root: Path, contigs: Iterable[str] = DEFAULT_CONTIGS) -> list[Tile]:
    tiles = []
    seen_ids: dict[int, Path] = {}
    for contig in contigs:
        directory = root / contig
        if not directory.is_dir():
            raise FileNotFoundError(f"missing tile directory: {directory}")
        for path in sorted(directory.glob("*/*.webp")):
            try:
                z = int(path.parent.name)
                y, x = (int(part) for part in path.stem.split("_"))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"invalid tile path: {path}") from exc
            if not ZOOM_MIN <= z <= ZOOM_MAX:
                raise ValueError(f"zoom {z} in {path} is outside supported range {ZOOM_MIN}-{ZOOM_MAX}")
            tile = Tile(z, x, y, path, contig)
            archive_z, archive_x, archive_y = archive_xyz(tile)
            tile_id = zxy_to_tileid(archive_z, archive_x, archive_y)
            if tile_id in seen_ids:
                raise ValueError(f"duplicate XYZ tile address {archive_z}/{archive_x}/{archive_y}: {seen_ids[tile_id]} and {path}")
            seen_ids[tile_id] = path
            tiles.append(Tile(z, x, y, path, contig))
    return sorted(tiles, key=lambda tile: zxy_to_tileid(*archive_xyz(tile)))


def _make_header(root_offset: int, root_length: int, metadata_offset: int,
                 metadata_length: int, tile_data_offset: int, tile_data_length: int,
                 tile_count: int, min_zoom: int, max_zoom: int) -> bytes:
    header = bytearray(HEADER_LEN)
    header[:7] = MAGIC
    header[7] = VERSION
    struct.pack_into("<Q", header, 8, root_offset)
    struct.pack_into("<Q", header, 16, root_length)
    struct.pack_into("<Q", header, 24, metadata_offset)
    struct.pack_into("<Q", header, 32, metadata_length)
    struct.pack_into("<Q", header, 40, metadata_offset + metadata_length)
    struct.pack_into("<Q", header, 48, 0)  # no leaf directories
    struct.pack_into("<Q", header, 56, tile_data_offset)
    struct.pack_into("<Q", header, 64, tile_data_length)
    struct.pack_into("<Q", header, 72, tile_count)  # addressed tiles
    struct.pack_into("<Q", header, 80, tile_count)  # tile entries
    struct.pack_into("<Q", header, 88, tile_count)  # tile contents (no dedup)
    header[96] = 1  # clustered by TileID
    header[97] = COMPRESSION_GZIP  # internal compression
    header[98] = COMPRESSION_NONE  # WebP is already compressed
    header[99] = TILE_TYPE_WEBP
    header[100] = min_zoom
    header[101] = max_zoom
    return bytes(header)


def parse_header(header: bytes) -> dict[str, int]:
    if len(header) != HEADER_LEN or header[:7] != MAGIC or header[7] != VERSION:
        raise ValueError("not a PMTiles v3 header")
    names = ("root_offset", "root_length", "metadata_offset", "metadata_length",
             "leaf_offset", "leaf_length", "tile_data_offset", "tile_data_length",
             "addressed_tiles", "tile_entries", "tile_contents")
    positions = (8, 16, 24, 32, 40, 48, 56, 64, 72, 80, 88)
    values = {name: struct.unpack_from("<Q", header, pos)[0] for name, pos in zip(names, positions)}
    values.update({"internal_compression": header[97], "tile_compression": header[98],
                   "tile_type": header[99], "min_zoom": header[100], "max_zoom": header[101]})
    return values


def convert(root: Path | str, output: Path | str,
            contigs: Iterable[str] = DEFAULT_CONTIGS) -> dict[str, int]:
    """Build a PMTiles v3 archive atomically; source tiles remain untouched."""
    root, output = Path(root), Path(output)
    tiles = collect_tiles(root, contigs)
    if not tiles:
        raise ValueError(f"no WebP tiles found under {root}")

    tile_data = bytearray()
    entries = []
    for tile in tiles:
        blob = tile.path.read_bytes()
        if not blob:
            raise ValueError(f"empty tile: {tile.path}")
        entries.append(Entry(zxy_to_tileid(*archive_xyz(tile)), len(tile_data), len(blob)))
        tile_data.extend(blob)

    leaf_blobs = []
    root_entries = []
    for start in range(0, len(entries), 256):
        chunk = entries[start:start + 256]
        leaf_blob = gzip.compress(serialize_directory(chunk), mtime=0)
        root_entries.append(Entry(chunk[0].tile_id, sum(len(blob) for blob in leaf_blobs), len(leaf_blob), 0))
        leaf_blobs.append(leaf_blob)
    directory = gzip.compress(serialize_directory(root_entries), mtime=0)
    if HEADER_LEN + len(directory) > 16 * 1024:
        raise ValueError("root directory exceeds PMTiles v3 16 KiB limit")
    leaves = b"".join(leaf_blobs)
    archive_min_zoom = min(tile.z for tile in tiles) + 1
    archive_max_zoom = max(tile.z for tile in tiles) + 1
    metadata = gzip.compress(json.dumps({
        "name": output.name,
        "format": "webp",
        "type": "raster",
        "version": "1",
        "minzoom": archive_min_zoom,
        "maxzoom": archive_max_zoom,
        "contigs": sorted(set(tile.contig for tile in tiles)),
        "description": "WoW WebP tile bundle. Archive addresses namespace the original tile grid at z+1: Kalimdor x unchanged; Eastern Kingdoms x shifted by 2^z. This preserves every source tile despite overlapping input z/x/y.",
        "addressing": "archive_z=source_z+1; archive_x=source_x for kalimdor, source_x+2^source_z for eastern-kingdoms; archive_y=source_y",
        "source_zoom_min": min(tile.z for tile in tiles),
        "source_zoom_max": max(tile.z for tile in tiles),
        "archive_zoom_offset": 1,
    }, separators=(",", ":"), sort_keys=True).encode("utf-8"), mtime=0)

    root_offset = HEADER_LEN
    metadata_offset = root_offset + len(directory)
    leaf_offset = metadata_offset + len(metadata)
    tile_data_offset = leaf_offset + len(leaves)
    header = _make_header(root_offset, len(directory), metadata_offset, len(metadata),
                          tile_data_offset, len(tile_data), len(tiles),
                          archive_min_zoom, archive_max_zoom)
    header = bytearray(header)
    struct.pack_into("<Q", header, 40, leaf_offset)
    struct.pack_into("<Q", header, 48, len(leaves))
    struct.pack_into("<Q", header, 80, len(tiles))
    struct.pack_into("<Q", header, 88, len(tiles))
    header = bytes(header)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=output.parent, prefix=output.name + ".",
                                         suffix=".tmp", delete=False) as stream:
            tmp_path = Path(stream.name)
            stream.write(header)
            stream.write(directory)
            stream.write(metadata)
            stream.write(leaves)
            stream.write(tile_data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, output)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise
    return {"tiles": len(tiles), "bytes": output.stat().st_size,
            "min_zoom": archive_min_zoom, "max_zoom": archive_max_zoom}


def read_tile(archive: bytes | Path | str, z: int, x: int, y: int) -> bytes:
    """Read one archive XYZ tile from a PMTiles file, for validation."""
    if isinstance(archive, (Path, str)):
        archive = Path(archive).read_bytes()
    header = parse_header(archive[:HEADER_LEN])
    root_start = header["root_offset"]
    compressed = archive[root_start:root_start + header["root_length"]]
    entries = parse_directory(gzip.decompress(compressed))
    requested_id = zxy_to_tileid(z, x, y)
    selected_leaf = None
    for entry in entries:
        if entry.tile_id > requested_id:
            break
        if entry.run_length == 0:
            selected_leaf = entry
        elif entry.tile_id <= requested_id < entry.tile_id + entry.run_length:
            start = header["tile_data_offset"] + entry.offset
            return archive[start:start + entry.length]
    if selected_leaf is not None:
        leaf_start = header["leaf_offset"] + selected_leaf.offset
        leaf = gzip.decompress(archive[leaf_start:leaf_start + selected_leaf.length])
        tile_entries = parse_directory(leaf)
        for tile_entry in tile_entries:
            if tile_entry.tile_id == requested_id:
                start = header["tile_data_offset"] + tile_entry.offset
                return archive[start:start + tile_entry.length]
    raise KeyError(f"tile not found: {z}/{x}/{y}")


def read_source_tile(archive: bytes | Path | str, contig: str, z: int, x: int, y: int) -> bytes:
    """Read a tile by original continent/source z/x/y coordinates."""
    tile = Tile(z, x, y, Path("."), contig)
    return read_tile(archive, *archive_xyz(tile))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tiles", type=Path, default=Path(__file__).parent / "tiles",
                        help="tile root containing kalimdor/ and eastern-kingdoms/ (default: ./tiles)")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "wow-forever.pmtiles",
                        help="output PMTiles archive (default: ./wow-forever.pmtiles)")
    parser.add_argument("--contigs", nargs="+", default=list(DEFAULT_CONTIGS),
                        help="continent directories to include")
    args = parser.parse_args()
    result = convert(args.tiles, args.output, args.contigs)
    print(f"Wrote {args.output}: {result['tiles']:,} tiles, {result['bytes']:,} bytes, "
          f"zoom {result['min_zoom']}-{result['max_zoom']}")


if __name__ == "__main__":
    main()
