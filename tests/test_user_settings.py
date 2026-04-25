import unittest

import pandas as pd

from utils import user_settings


class UserSettingsTest(unittest.TestCase):
    def test_build_signup_metadata_normalizes_codes_and_default_currency(self):
        payload = user_settings.build_signup_metadata(
            first_name=" Hideaki ",
            last_name="Morita",
            display_name=" hide ",
            nationality_country_code="jp",
            current_country_code="vn",
            base_currency_code="jpy",
            enabled_currency_codes=["vnd", " usd ", "VND"],
            default_currency_code="usd",
        )

        self.assertEqual(payload["first_name"], "Hideaki")
        self.assertEqual(payload["display_name"], "hide")
        self.assertEqual(payload["nationality_country_code"], "JP")
        self.assertEqual(payload["current_country_code"], "VN")
        self.assertEqual(payload["base_currency_code"], "JPY")
        self.assertEqual(payload["enabled_currency_codes"], ["VND", "USD"])
        self.assertEqual(payload["default_currency_code"], "USD")

    def test_build_user_currency_payloads_marks_default_and_sort_order(self):
        rows = user_settings.build_user_currency_payloads(
            auth_user_id="user-1",
            enabled_currency_codes=["USD", "VND"],
            default_currency_code="VND",
            now="2026/04/24 12:00:00",
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["sort_order"], 1)
        self.assertFalse(rows[0]["is_default"])
        self.assertTrue(rows[1]["is_default"])

    def test_resolve_user_expense_preferences_uses_user_defaults(self):
        settings = {"base_currency_code": "usd"}
        user_currencies = pd.DataFrame(
            [
                {"currency_code": "VND", "is_enabled": True, "is_default": False},
                {"currency_code": "THB", "is_enabled": True, "is_default": True},
            ]
        )

        preference = user_settings.resolve_user_expense_preferences(settings, user_currencies)

        self.assertEqual(preference["base_currency_code"], "USD")
        self.assertEqual(preference["payment_currency_code"], "THB")

    def test_resolve_user_expense_preferences_falls_back_when_no_rows_exist(self):
        preference = user_settings.resolve_user_expense_preferences({}, pd.DataFrame())

        self.assertEqual(preference["base_currency_code"], user_settings.DEFAULT_BASE_CURRENCY)
        self.assertEqual(preference["payment_currency_code"], user_settings.DEFAULT_PAYMENT_CURRENCY)

    def test_normalize_currency_selection_keeps_default_enabled(self):
        enabled_codes, default_code = user_settings.normalize_currency_selection(
            ["USD"],
            "THB",
            available_currency_codes=["USD", "THB", "JPY"],
        )

        self.assertEqual(enabled_codes, ["USD", "THB"])
        self.assertEqual(default_code, "THB")


if __name__ == "__main__":
    unittest.main()
