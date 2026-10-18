import gzip
import json
import struct
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import convert_tiles


class ConvertTilesTests(unittest.TestCase):
    def test_hilbert_tile_ids_match_pmtiles_cumulative_order(self):
        self.assertEqual([convert_tiles.zxy_to_tileid(1, x, y) for y in range(2) for x in range(2)], [1, 4, 2, 3])

    def test_archive_round_trips_xyz_tiles_with_gzip_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tiles"
            (root / "kalimdor" / "2").mkdir(parents=True)
            (root / "eastern-kingdoms" / "2").mkdir(parents=True)
            payloads = {
                root / "kalimdor" / "2" / "1_2.webp": b"kalimdor-webp-payload",
                root / "eastern-kingdoms" / "2" / "3_1.webp": b"eastern-webp-payload",
            }
            for path, payload in payloads.items():
                path.write_bytes(payload)

            archive = Path(tmp) / "tiles.pmtiles"
            convert_tiles.convert(root, archive)

            data = archive.read_bytes()
            self.assertEqual(data[:7], b"PMTiles")
            self.assertEqual(data[7], 3)
            self.assertEqual(data[97], convert_tiles.COMPRESSION_GZIP)
            self.assertEqual(data[98], convert_tiles.COMPRESSION_NONE)
            self.assertEqual(data[99], convert_tiles.TILE_TYPE_WEBP)
            header = convert_tiles.parse_header(data[:127])
            metadata = json.loads(gzip.decompress(data[header["metadata_offset"]:header["metadata_offset"] + header["metadata_length"]]))
            self.assertEqual(metadata["format"], "webp")
            self.assertEqual(metadata["contigs"], ["eastern-kingdoms", "kalimdor"])
            self.assertEqual(convert_tiles.read_source_tile(data, "kalimdor", 2, 2, 1), b"kalimdor-webp-payload")
            self.assertEqual(convert_tiles.read_source_tile(data, "eastern-kingdoms", 2, 1, 3), b"eastern-webp-payload")

    def test_namespaces_overlapping_source_grids_in_archive_xyz(self):
        kalimdor = convert_tiles.Tile(7, 38, 25, Path("kalimdor.webp"), "kalimdor")
        eastern = convert_tiles.Tile(7, 38, 25, Path("eastern.webp"), "eastern-kingdoms")
        self.assertEqual(convert_tiles.archive_xyz(kalimdor), (8, 38, 25))
        self.assertEqual(convert_tiles.archive_xyz(eastern), (8, 166, 25))
        self.assertNotEqual(
            convert_tiles.zxy_to_tileid(*convert_tiles.archive_xyz(kalimdor)),
            convert_tiles.zxy_to_tileid(*convert_tiles.archive_xyz(eastern)),
        )

    def test_tile_lookups_cross_every_leaf_boundary_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tiles"
            folder = root / "kalimdor" / "7"
            folder.mkdir(parents=True)
            for y in range(20):
                for x in range(20):
                    (folder / f"{y}_{x}.webp").write_bytes(f"tile-{x}-{y}".encode())
            archive = Path(tmp) / "many.pmtiles"
            convert_tiles.convert(root, archive, ("kalimdor",))
            data = archive.read_bytes()
            for x, y in ((0, 0), (9, 3), (10, 3), (19, 19)):
                self.assertEqual(convert_tiles.read_source_tile(data, "kalimdor", 7, x, y), f"tile-{x}-{y}".encode())

    def test_contiguous_tiles_have_compliant_root_leaf_indexing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tiles"
            folder = root / "kalimdor" / "7"
            folder.mkdir(parents=True)
            for y in range(20):
                for x in range(20):
                    (folder / f"{y}_{x}.webp").write_bytes(f"tile-{x}-{y}".encode())
            archive = Path(tmp) / "many.pmtiles"
            convert_tiles.convert(root, archive, ("kalimdor",))
            data = archive.read_bytes()
            header = convert_tiles.parse_header(data[:127])
            self.assertLessEqual(header["root_offset"] + header["root_length"], 16384)
            root_entries = convert_tiles.parse_directory(gzip.decompress(
                data[header["root_offset"]:header["root_offset"] + header["root_length"]]))
            self.assertTrue(root_entries)
            self.assertTrue(all(entry.run_length == 0 for entry in root_entries))
            self.assertEqual(convert_tiles.read_tile(data, 8, 5, 6), b"tile-5-6")

    def test_keeps_tiles_with_same_source_xyz_from_both_continents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tiles"
            for contig, value in (("kalimdor", b"kalimdor"), ("eastern-kingdoms", b"eastern")):
                folder = root / contig / "2"
                folder.mkdir(parents=True)
                (folder / "1_2.webp").write_bytes(value)
            archive = Path(tmp) / "both.pmtiles"
            result = convert_tiles.convert(root, archive)
            self.assertEqual(result["tiles"], 2)
            self.assertEqual(convert_tiles.read_tile(archive, 3, 2, 1), b"kalimdor")
            self.assertEqual(convert_tiles.read_tile(archive, 3, 6, 1), b"eastern")

    def test_rejects_duplicate_xyz_addresses_in_same_continent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tiles"
            folder = root / "kalimdor" / "2"
            folder.mkdir(parents=True)
            (folder / "1_2.webp").write_bytes(b"one")
            (folder / "01_2.webp").write_bytes(b"two")
            with self.assertRaisesRegex(ValueError, "duplicate XYZ"):
                convert_tiles.convert(root, Path(tmp) / "bad.pmtiles", ("kalimdor",))

    def test_rejects_tile_zoom_outside_configured_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tiles" / "kalimdor" / "9"
            root.mkdir(parents=True)
            (root / "0_0.webp").write_bytes(b"tile")
            with self.assertRaisesRegex(ValueError, "zoom"):
                convert_tiles.convert(root.parents[1], Path(tmp) / "bad.pmtiles")


if __name__ == "__main__":
    unittest.main()
