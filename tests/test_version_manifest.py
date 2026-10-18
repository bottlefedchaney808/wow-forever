import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "version_manifest.py"
spec = importlib.util.spec_from_file_location("version_manifest", SCRIPT)
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)


class VersionManifestTests(unittest.TestCase):
    def make_root(self, root):
        (root / "data").mkdir()
        (root / "tiles" / "kalimdor").mkdir(parents=True)
        (root / "data" / "places.js").write_text(
            'window.WH_PLACES={"zones":[{"n":"Durotar","ll":[0.1,0.2],"mz":0}],"landmarks":[]};\n',
            encoding="utf-8",
        )
        (root / "data" / "pois.js").write_text(
            'window.WH_POIS=[{"n":"Innkeeper A","c":"innkeeper","ll":[0.1,0.2],"npc":42,"side":2}];\n',
            encoding="utf-8",
        )
        (root / "data" / "nodes.js").write_text("window.WH_NODES={};\n", encoding="utf-8")
        (root / "tiles" / "kalimdor" / "tile.webp").write_bytes(b"tile")

    def test_manifest_pins_dv_and_is_stable_across_invocations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_root(root)
            first = vm.build_manifest(root)
            second = vm.build_manifest(root)
            self.assertEqual(first, second)
            self.assertEqual(first["wowhead_data_version"], 14)
            self.assertEqual(len(bytes.fromhex(first["dataset_version"])), 8)
            self.assertIn("kalimdor", first["tile_packs"])
            self.assertNotIn("tile.webp", json.dumps(first))

    def test_id_map_uses_stable_ids_and_migrates_changed_wowhead_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_root(root)
            old = vm.build_id_map(root)
            old["entities"][0]["wowhead_id"] = 42
            (root / "data" / "pois.js").write_text(
                'window.WH_POIS=[{"n":"Innkeeper A","c":"innkeeper","ll":[0.1,0.2],"npc":99,"side":2}];\n',
                encoding="utf-8",
            )
            current = vm.build_id_map(root, old)
            migration = current["migration"]
            self.assertEqual(current["entities"][0]["stable_id"], old["entities"][0]["stable_id"])
            self.assertEqual(migration["mappings"][0]["old_wowhead_id"], 42)
            self.assertEqual(migration["mappings"][0]["new_wowhead_id"], 99)

    def test_duplicate_identity_is_disambiguated_deterministically(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_root(root)
            (root / "data" / "pois.js").write_text(
                'window.WH_POIS=[{"n":"Innkeeper A","c":"innkeeper","ll":[0.1,0.2],"npc":42},{"n":"Innkeeper A","c":"innkeeper","ll":[0.4,0.5],"npc":43}];',
                encoding="utf-8",
            )
            ids = [e["stable_id"] for e in vm.build_id_map(root)["entities"]]
            self.assertEqual(len(ids), len(set(ids)))


    def test_index_html_footer_matches_manifest_dataset_version(self):
        # Guards against the footer hash going stale relative to the manifest
        # (a hand-copied hash previously drifted from dataset_version).
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "version-manifest.json").read_text(encoding="utf-8"))
        index = (root / "index.html").read_text(encoding="utf-8")
        self.assertIn(manifest["dataset_version"], index)


if __name__ == "__main__":
    unittest.main()
