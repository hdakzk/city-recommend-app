import unittest

from utils.city_suggest_support import (
    REQUIRED_SEARCH_STATE_KEYS,
    build_country_option_records,
    build_selection_debug_snapshot,
    build_selection_warning,
    get_missing_search_state_keys,
    is_debug_mode_enabled,
)


class CitySuggestSupportTest(unittest.TestCase):
    def test_build_country_option_records_keeps_unique_country_names_unchanged(self):
        records = build_country_option_records(
            [
                {"country_id": 81, "country": "Japan"},
                {"country_id": 1, "country": "Canada"},
            ]
        )

        self.assertEqual(
            records,
            [
                {"country_id": 81, "label": "Japan"},
                {"country_id": 1, "label": "Canada"},
            ],
        )

    def test_build_country_option_records_disambiguates_duplicate_country_names(self):
        records = build_country_option_records(
            [
                {"country_id": 1, "country": "Congo"},
                {"country_id": 2, "country": "Congo"},
            ]
        )

        self.assertEqual(
            records,
            [
                {"country_id": 1, "label": "Congo｜ID:1"},
                {"country_id": 2, "label": "Congo｜ID:2"},
            ],
        )

        label_to_id = {row["label"]: row["country_id"] for row in records}
        self.assertEqual(label_to_id["Congo｜ID:1"], 1)
        self.assertEqual(label_to_id["Congo｜ID:2"], 2)

    def test_build_country_option_records_skips_invalid_boundary_rows(self):
        records = build_country_option_records(
            [
                {"country_id": None, "country": "Japan"},
                {"country_id": "bad", "country": "Canada"},
            ]
        )

        self.assertEqual(records, [])

    def test_is_debug_mode_enabled_accepts_true_like_values(self):
        self.assertTrue(is_debug_mode_enabled({"debug_city_suggest": "1"}))
        self.assertTrue(is_debug_mode_enabled({"debug_city_suggest": "true"}))
        self.assertTrue(is_debug_mode_enabled({"debug_city_suggest": ["on"]}))
        self.assertFalse(is_debug_mode_enabled({"debug_city_suggest": "0"}))
        self.assertFalse(is_debug_mode_enabled({}))

    def test_get_missing_search_state_keys_detects_incomplete_state(self):
        search_state = {
            "selected_country_id": 1,
            "selected_country_name": "Japan",
            "selected_city_id": 10,
        }

        missing = get_missing_search_state_keys(search_state)

        self.assertEqual(
            missing,
            [key for key in REQUIRED_SEARCH_STATE_KEYS if key not in search_state],
        )

    def test_build_selection_debug_snapshot_counts_options(self):
        snapshot = build_selection_debug_snapshot(
            selected_country_name="Japan",
            selected_country_id=81,
            country_option_records=[{"country_id": 81, "label": "Japan"}],
            city_option_records=[
                {"city_id": 1, "label": "Tokyo"},
                {"city_id": 2, "label": "Osaka"},
            ],
            selected_city_id=1,
            selected_city_label="Tokyo",
        )

        self.assertEqual(snapshot["selected_country_name"], "Japan")
        self.assertEqual(snapshot["selected_country_id"], 81)
        self.assertEqual(snapshot["country_options_rows"], 1)
        self.assertEqual(snapshot["city_options_rows"], 2)
        self.assertEqual(snapshot["selected_city_id"], 1)
        self.assertEqual(snapshot["selected_city_label"], "Tokyo")

    def test_build_selection_warning_reports_empty_city_options(self):
        warning = build_selection_warning(
            {
                "selected_country_id": 81,
                "city_options_rows": 0,
                "selected_city_id": None,
                "selected_city_label": "",
            }
        )

        self.assertIn("都市候補がありません", warning)

    def test_build_selection_warning_reports_label_id_mismatch(self):
        warning = build_selection_warning(
            {
                "selected_country_id": 81,
                "city_options_rows": 3,
                "selected_city_id": None,
                "selected_city_label": "Tokyo / Tokyo",
            }
        )

        self.assertIn("対応が取れていません", warning)

    def test_build_selection_warning_is_none_for_valid_snapshot(self):
        warning = build_selection_warning(
            {
                "selected_country_id": 81,
                "city_options_rows": 3,
                "selected_city_id": 1,
                "selected_city_label": "Tokyo / Tokyo",
            }
        )

        self.assertIsNone(warning)


if __name__ == "__main__":
    unittest.main()
