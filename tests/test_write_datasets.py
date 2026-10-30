"""Writer tests for scrape/write_datasets.py (Task 8, TDD)."""

import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scrape"))
import write_datasets as w

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _parse_shipped(name, variable):
    text = (ROOT / "data" / f"{name}.js").read_text(encoding="utf-8")
    payload = text.split("=", 1)[1].strip().rstrip(";")
    return json.loads(payload), text


def test_write_places_matches_shipped_format(tmp_path):
    obj = {"zones": [{"n": "Durotar", "ll": [0.449758, 0.467089], "mz": 0}]}
    out = w.write_places(obj)
    assert out.startswith("window.WH_PLACES=")
    assert json.loads(out.split("=", 1)[1].strip().rstrip(";")) == obj
    # golden: regenerating the shipped payload reproduces the shipped bytes
    parsed, original = _parse_shipped("places", "WH_PLACES")
    assert w.write_places(parsed) == original


def test_write_pois_and_nodes_and_routes(tmp_path):
    assert w.write_pois([{"n": "Inn", "c": "innkeeper", "ll": [0.1, 0.2]}]).startswith("window.WH_POIS=[")
    assert w.write_nodes({"herb-x": {"n": "X", "pts": [[0.1, 0.2]]}}).startswith("window.WH_NODES=")
    assert w.write_routes([]).startswith("window.WH_ROUTES=")
    assert w.write_voyages([]).startswith("window.WH_VOYAGES=")
    # golden: pois/nodes round-trip byte-for-byte (default spaced separators)
    parsed, original = _parse_shipped("pois", "WH_POIS")
    assert w.write_pois(parsed) == original
    parsed, original = _parse_shipped("nodes", "WH_NODES")
    assert w.write_nodes(parsed) == original


def test_counts_validation(tmp_path):
    try:
        w.build_all(str(tmp_path / "none"), str(tmp_path))
        assert False, "expected SystemExit on missing captures"
    except SystemExit as e:
        assert str(e)  # non-empty failure reason
