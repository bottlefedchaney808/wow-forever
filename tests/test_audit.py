import unittest

from audit import (
    audit_dataset,
    expected_grid_dimensions,
    parse_js_assignment,
    spot_check_landmarks,
)


class AuditTests(unittest.TestCase):
    def test_expected_grid_dimensions_scale_from_z7(self):
        self.assertEqual(expected_grid_dimensions("kalimdor", 7), (100, 112))
        self.assertEqual(expected_grid_dimensions("eastern-kingdoms", 7), (46, 84))
        self.assertEqual(expected_grid_dimensions("kalimdor", 6), (50, 56))

    def test_parse_js_assignment_reads_json_payload(self):
        self.assertEqual(parse_js_assignment('window.WH_POIS=[{"n":"A"}];', "WH_POIS"), [{"n": "A"}])

    def test_dataset_audit_counts_records_and_flags_duplicate_and_bounds(self):
        records = [
            {"n": "first", "ll": [0.5, 0.5]},
            {"n": "first", "ll": [0.5, 0.5]},
            {"n": "outside", "ll": [1.1, 0.5]},
        ]
        count, issues = audit_dataset(records, "places")
        self.assertEqual(count, 3)
        self.assertTrue(any("duplicate" in issue.lower() for issue in issues))
        self.assertTrue(any("out of bounds" in issue.lower() for issue in issues))

    def test_landmark_spot_check_catches_landmark_outside_its_zone_box(self):
        places = {
            "zones": [{"n": "Durotar", "ll": [0.45, 0.46]}],
            "landmarks": [{"n": "Razor Hill", "ll": [0.9, 0.9]}],
        }
        checked, issues = spot_check_landmarks(places)
        self.assertGreaterEqual(checked, 1)
        self.assertTrue(any("Razor Hill" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
