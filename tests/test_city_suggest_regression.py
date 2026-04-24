from pathlib import Path
import importlib.util
import sys
import types
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CITY_SUGGEST = ROOT / "pages" / "city_suggest.py"
DB_MODULE = ROOT / "utils" / "db.py"
SUPPORT_MODULE = ROOT / "utils" / "city_suggest_support.py"
PYTEST_INI = ROOT / "pytest.ini"


def load_db_module():
    fake_supabase_client = types.ModuleType("utils.supabase_client")
    fake_supabase_client.create_public_supabase_client = lambda: object()

    sys.modules["utils.supabase_client"] = fake_supabase_client

    spec = importlib.util.spec_from_file_location("test_utils_db", DB_MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CitySuggestRegressionTest(unittest.TestCase):
    def test_city_options_debug_output_does_not_reference_removed_variable(self):
        source = CITY_SUGGEST.read_text(encoding="utf-8")

        self.assertIn("build_selection_debug_snapshot", source)
        self.assertIn("selection_debug_snapshot", source)
        self.assertNotIn("city_options_df", source)
        self.assertNotIn('st.write("city_options_rows =", len(city_option_records))', source)

    def test_city_selection_no_longer_requires_lat_lon_at_load_time(self):
        source = CITY_SUGGEST.read_text(encoding="utf-8")

        self.assertIn("prepare_cities_for_selection", source)
        self.assertNotIn('dropna(subset=["city_id", "lat", "lon"])', source)
        self.assertIn('candidates = candidates.dropna(subset=["lat", "lon"]).copy()', source)

    def test_country_and_city_selectboxes_use_id_state_with_formatters(self):
        source = CITY_SUGGEST.read_text(encoding="utf-8")

        self.assertIn('key="city_suggest_country_id_live"', source)
        self.assertIn('key="city_suggest_city_id_live"', source)
        self.assertIn("build_country_option_records", source)
        self.assertIn('format_func=lambda x: "対象国を選択"', source)
        self.assertIn('format_func=lambda x: "基準都市を選択"', source)
        self.assertIn("country_name_map", source)
        self.assertIn("city_label_map", source)
        self.assertIn("disabled=(selected_country_id is None or selected_city_id is None)", source)

    def test_db_helper_prepares_selection_without_dropping_missing_coordinates(self):
        source = DB_MODULE.read_text(encoding="utf-8")

        self.assertIn("def prepare_cities_for_selection", source)
        self.assertIn('out = out.dropna(subset=["city_id"]).copy()', source)
        self.assertNotIn('dropna(subset=["city_id", "lat", "lon"])', source)

    def test_pytest_config_limits_discovery_scope(self):
        source = PYTEST_INI.read_text(encoding="utf-8")

        self.assertIn("testpaths = tests", source)
        self.assertIn("norecursedirs =", source)
        self.assertIn(".venv", source)
        self.assertIn("venv", source)
        self.assertIn("venv313", source)

    def test_city_suggest_uses_defensive_search_state_guard(self):
        source = CITY_SUGGEST.read_text(encoding="utf-8")

        self.assertIn("get_missing_search_state_keys(search_state)", source)
        self.assertIn("前回の検索条件が不完全です。条件を選び直して再実行してください。", source)
        self.assertIn("is_debug_mode_enabled(st.query_params)", source)

    def test_support_module_contains_selection_diagnostics(self):
        source = SUPPORT_MODULE.read_text(encoding="utf-8")

        self.assertIn("def build_selection_debug_snapshot", source)
        self.assertIn("def build_selection_warning", source)
        self.assertIn("def get_missing_search_state_keys", source)

    def test_prepare_cities_for_selection_keeps_rows_without_coordinates(self):
        db_module = load_db_module()
        df = pd.DataFrame(
            [
                {"city_id": "1", "country_id": "10", "city_jp": " 東京 ", "city_en": " Tokyo ", "lat": None, "lon": None},
                {"city_id": "2", "country_id": "10", "city_jp": "Osaka", "city_en": None, "lat": "34.6", "lon": "135.5"},
            ]
        )

        out = db_module.prepare_cities_for_selection(df)

        self.assertEqual(out["city_id"].tolist(), [1, 2])
        self.assertEqual(out["country_id"].tolist(), [10, 10])
        self.assertTrue(pd.isna(out.loc[out["city_id"] == 1, "lat"]).all())
        self.assertTrue(pd.isna(out.loc[out["city_id"] == 1, "lon"]).all())
        self.assertEqual(out.loc[out["city_id"] == 1, "city_jp"].item(), "東京")
        self.assertEqual(out.loc[out["city_id"] == 1, "city_en"].item(), "Tokyo")
        self.assertEqual(out.loc[out["city_id"] == 2, "city_en"].item(), "")

    def test_prepare_cities_for_selection_returns_empty_when_required_columns_are_missing(self):
        db_module = load_db_module()
        df = pd.DataFrame([{"city_id": "1", "city_jp": "Tokyo"}])

        out = db_module.prepare_cities_for_selection(df)

        self.assertTrue(out.empty)

    def test_prepare_cities_for_selection_drops_rows_with_invalid_ids(self):
        db_module = load_db_module()
        df = pd.DataFrame(
            [
                {"city_id": None, "country_id": "10", "city_jp": "Tokyo"},
                {"city_id": "3", "country_id": "bad", "city_jp": "Nagoya"},
                {"city_id": "4", "country_id": "20", "city_jp": "Kyoto"},
            ]
        )

        out = db_module.prepare_cities_for_selection(df)

        self.assertEqual(out["city_id"].tolist(), [4])
        self.assertEqual(out["country_id"].tolist(), [20])
        self.assertEqual(out.loc[out.index[0], "city_jp"], "Kyoto")


if __name__ == "__main__":
    unittest.main()
