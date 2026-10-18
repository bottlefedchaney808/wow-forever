"""pytest-style unit tests for audit.py."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from audit import (
    expected_grid_dimensions,
    parse_js_assignment,
    _coordinate_issues,
    audit_dataset,
    check_tile_tree,
    check_webp_magic,
    spot_check_landmarks,
    LANDMARK_ZONE_CHECKS,
)


# ── Tile grid dimensions ───────────────────────────────────────────────────

def test_expected_grid_dimensions_kalimdor_z7():
    cols, rows = expected_grid_dimensions("kalimdor", 7)
    assert cols == 100
    assert rows == 112


def test_expected_grid_dimensions_eastern_z7():
    cols, rows = expected_grid_dimensions("eastern-kingdoms", 7)
    assert cols == 46
    assert rows == 84


def test_expected_grid_dimensions_kalimdor_z8():
    """z8 scale is 0.5 → grid doubles: ceil(100/0.5)=200, ceil(112/0.5)=224."""
    cols, rows = expected_grid_dimensions("kalimdor", 8)
    assert cols == 200
    assert rows == 224


def test_expected_grid_dimensions_kalimdor_z9():
    """z9 scale is 0.25 → grid quadruples: ceil(100/0.25)=400, ceil(112/0.25)=448."""
    cols, rows = expected_grid_dimensions("kalimdor", 9)
    assert cols == 400
    assert rows == 448


def test_expected_grid_dimensions_eastern_z9():
    """z9 Eastern: scale=0.25 → ceil(46/0.25)=184, ceil(84/0.25)=336."""
    cols, rows = expected_grid_dimensions("eastern-kingdoms", 9)
    assert cols == 184
    assert rows == 336


# ── JS parsing ─────────────────────────────────────────────────────────────

def test_parse_js_assignment_window_variable():
    text = "window.X = {\"a\": 1, \"b\": 2};\n"
    result = parse_js_assignment(text, "X")
    assert result == {"a": 1, "b": 2}


def test_parse_js_assignment_no_prefix():
    text = 'X = [{"name":"foo"}];\n'
    result = parse_js_assignment(text, "X")
    assert result == [{"name": "foo"}]


def test_parse_js_assignment_missing_variable():
    try:
        parse_js_assignment("window.Y = {};", "Z")
        assert False  # should not reach here
    except ValueError:
        pass


# ── Coordinate validation ─────────────────────────────────────────────────

def test_coordinate_issues_valid():
    record = {"ll": [0.5, 0.5]}
    issues = _coordinate_issues(record, "test")
    assert not issues


def test_coordinate_issues_out_of_bounds():
    record = {"ll": [1.0, 2.0]}
    issues = _coordinate_issues(record, "test")
    assert any("out of bounds" in i for i in issues)


def test_coordinate_issues_non_finite():
    record = {"ll": [float("inf"), 0.5]}
    issues = _coordinate_issues(record, "test")
    assert any("non-finite" in i for i in issues)


# ── audit_dataset — counting & duplicates ─────────────────────────────────

def test_audit_dataset_places_count():
    data = {
        "zones": [{"n": "Mulgore", "ll": [0.1, 0.2]}],
        "landmarks": [{"n": "Bloodhoof Village", "ll": [0.15, 0.25]}]
    }
    count, issues = audit_dataset(data, "places")
    assert count == 2


def test_audit_dataset_places_duplicate():
    data = {
        "zones": [
            {"n": "Mulgore", "ll": [0.1, 0.2]},
            {"n": "Mulgore", "ll": [0.1, 0.2]}
        ]
    }
    count, issues = audit_dataset(data, "places")
    assert count == 2
    assert any("duplicate" in i for i in issues)


def test_audit_dataset_pois_count():
    data = [{"n": "A", "ll": [0.1, 0.2]}, {"n": "B", "ll": [0.3, 0.4]}]
    count, issues = audit_dataset(data, "pois")
    assert count == 2


def test_audit_dataset_pois_duplicate():
    data = [{"n": "A", "ll": [0.1, 0.2]}, {"n": "A", "ll": [0.1, 0.2]}]
    count, issues = audit_dataset(data, "pois")
    assert any("duplicate" in i for i in issues)


def test_audit_dataset_nodes_count():
    data = {
        "node1": {"n": "A", "pts": [[0.1, 0.2], [0.3, 0.4]]},
        "node2": {"n": "B", "pts": [[0.5, 0.6]]}
    }
    count, issues = audit_dataset(data, "nodes")
    assert count == 3


def test_audit_dataset_nodes_duplicate_point():
    data = {
        "node1": {"n": "A", "pts": [[0.1, 0.2], [0.1, 0.2]]}
    }
    count, issues = audit_dataset(data, "nodes")
    assert any("duplicate" in i for i in issues)


def test_audit_dataset_out_of_bounds():
    data = {
        "zones": [{"n": "Mulgore", "ll": [1.5, 2.0]}],
        "landmarks": []
    }
    count, issues = audit_dataset(data, "places")
    assert any("out of bounds" in i for i in issues)


# ── check_tile_tree ───────────────────────────────────────────────────────

def test_check_tile_tree_basic():
    tmp = tempfile.mkdtemp()
    tiles_dir = Path(tmp) / "tiles"
    kalimdor = tiles_dir / "kalimdor" / "7"
    eastern = tiles_dir / "eastern-kingdoms" / "7"
    kalimdor.mkdir(parents=True)
    eastern.mkdir(parents=True)
    for x, y in [(0, 0), (1, 0), (2, 0)]:
        tile = kalimdor / f"{y}_{x}.webp"
        tile.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
    for x, y in [(0, 0), (1, 0)]:
        tile = eastern / f"{y}_{x}.webp"
        tile.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
    counts, issues = check_tile_tree(tiles_dir)
    assert counts["kalimdor"][7] == 3
    assert not issues


def test_check_tile_tree_out_of_bounds():
    tmp = tempfile.mkdtemp()
    tiles_dir = Path(tmp) / "tiles"
    kalimdor = tiles_dir / "kalimdor" / "7"
    kalimdor.mkdir(parents=True)
    tile = kalimdor / f"{112}_99.webp"
    tile.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
    counts, issues = check_tile_tree(tiles_dir)
    assert any("outside z7 grid" in i for i in issues)


def test_check_tile_tree_missing_continent():
    tmp = tempfile.mkdtemp()
    tiles_dir = Path(tmp) / "tiles"
    counts, issues = check_tile_tree(tiles_dir)
    assert any("missing continent" in i for i in issues)


def test_check_tile_tree_empty_zoom():
    tmp = tempfile.mkdtemp()
    tiles_dir = Path(tmp) / "tiles"
    kalimdor = tiles_dir / "kalimdor" / "7"
    kalimdor.mkdir(parents=True)
    counts, issues = check_tile_tree(tiles_dir)
    assert any("no WebP tiles" in i for i in issues)


# ── check_webp_magic ─────────────────────────────────────────────────────

def test_check_webp_magic_valid():
    tmp = tempfile.mkdtemp()
    tile_path = Path(tmp) / "test.webp"
    tile_path.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
    checked, issues = check_webp_magic(Path(tmp))
    assert checked == 1
    assert not issues


def test_check_webp_magic_invalid():
    tmp = tempfile.mkdtemp()
    tile_path = Path(tmp) / "test.webp"
    tile_path.write_bytes(b"NOTRIF\x00\x00\x00WEBP")
    checked, issues = check_webp_magic(Path(tmp))
    assert any("invalid WebP" in i for i in issues)


def test_check_webp_magic_empty_dir():
    tmp = tempfile.mkdtemp()
    checked, issues = check_webp_magic(Path(tmp))
    assert checked == 0
    assert any("no .webp tiles" in i for i in issues)


# ── spot_check_landmarks ─────────────────────────────────────────────────

def test_spot_check_landmarks_proximity_pass():
    places = {
        "zones": [{"n": "Mulgore", "ll": [0.1, 0.2]}],
        "landmarks": [{"n": "Bloodhoof Village", "ll": [0.15, 0.25]}]
    }
    checked, issues = spot_check_landmarks(places)
    assert any("checked only" in i for i in issues)


def test_spot_check_landmarks_far_apart():
    places = {
        "zones": [{"n": "Mulgore", "ll": [0.1, 0.2]}],
        "landmarks": [{"n": "Bloodhoof Village", "ll": [0.5, 0.6]}]
    }
    checked, issues = spot_check_landmarks(places)
    assert any("implausibly far" in i for i in issues)


def test_spot_check_landmarks_missing():
    places = {"zones": [], "landmarks": []}
    checked, issues = spot_check_landmarks(places)
    assert any("missing Bloodhoof Village" in i for i in issues)


# ── Integration: run_audit exit codes ─────────────────────────────────────

def test_run_audit_no_duplicates():
    tmp = tempfile.mkdtemp()
    data_dir = Path(tmp) / "data"
    tiles_root = Path(tmp) / "tiles"
    data_dir.mkdir(parents=True)

    # Create both continent tile dirs (audit.py iterates all CONTINENTS)
    for cont, zoom in [("kalimdor", 7), ("eastern-kingdoms", 7)]:
        zdir = tiles_root / cont / str(zoom)
        zdir.mkdir(parents=True)
        for x, y in [(0, 0), (1, 0)]:
            (zdir / f"{y}_{x}.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBP")

    # Create all data files — need a unique zone for each landmark-zone check pair
    # Each landmark has distinct name + coordinates; zones are deduplicated by name.
    clean_places = json.dumps({
        "zones": [{"n": z, "ll": [0.15, 0.25]} for z in sorted(set(LANDMARK_ZONE_CHECKS.values()))],
        "landmarks": [{"n": n, "ll": [round(0.15 + i * 0.001, 3), round(0.25 + i * 0.001, 3)]} for i, n in enumerate(LANDMARK_ZONE_CHECKS)]
    })
    (data_dir / "places.js").write_text(f"window.WH_PLACES = {clean_places};\n")

    clean_pois = json.dumps([{"n": f"poi{i}", "ll": [0.1, 0.2]} for i in range(5)])
    (data_dir / "pois.js").write_text(f"window.WH_POIS = {clean_pois};\n")

    clean_nodes = json.dumps({"node1": {"n": "A", "pts": [[0.1, 0.2]]}})
    (data_dir / "nodes.js").write_text(f"window.WH_NODES = {clean_nodes};\n")

    exit_code = __import__("audit").run_audit(Path(tmp))
    assert exit_code == 0


def test_run_audit_with_duplicates():
    tmp = tempfile.mkdtemp()
    data_dir = Path(tmp) / "data"
    tiles_root = Path(tmp) / "tiles"
    data_dir.mkdir(parents=True)

    for cont, zoom in [("kalimdor", 7), ("eastern-kingdoms", 7)]:
        zdir = tiles_root / cont / str(zoom)
        zdir.mkdir(parents=True)
        for x, y in [(0, 0), (1, 0)]:
            (zdir / f"{y}_{x}.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBP")

    dup_places = json.dumps({
        "zones": [
            {"n": "Mulgore", "ll": [0.1, 0.2]},
            {"n": "Mulgore", "ll": [0.1, 0.2]}
        ],
        "landmarks": [{"n": name, "ll": [0.15, 0.25]} for name in LANDMARK_ZONE_CHECKS]
    })
    (data_dir / "places.js").write_text(f"window.WH_PLACES = {dup_places};\n")

    clean_pois = json.dumps([{"n": f"poi{i}", "ll": [0.1, 0.2]} for i in range(5)])
    (data_dir / "pois.js").write_text(f"window.WH_POIS = {clean_pois};\n")

    clean_nodes = json.dumps({"node1": {"n": "A", "pts": [[0.1, 0.2]]}})
    (data_dir / "nodes.js").write_text(f"window.WH_NODES = {clean_nodes};\n")

    exit_code = __import__("audit").run_audit(Path(tmp))
    assert exit_code == 1
