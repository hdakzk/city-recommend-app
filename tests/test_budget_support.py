import unittest
from datetime import date

import pandas as pd

from utils.budget_support import (
    build_budget_month_options,
    build_budget_record,
    build_budget_summary,
    calculate_monthly_expense_total,
    calculate_remaining_days_in_month,
    normalize_budget_month,
)


class BudgetSupportTest(unittest.TestCase):
    def test_normalize_budget_month_accepts_year_month_text(self):
        self.assertEqual(normalize_budget_month("2026-04"), "2026-04")
        self.assertEqual(normalize_budget_month(date(2026, 4, 20)), "2026-04")

    def test_normalize_budget_month_rejects_invalid_text(self):
        with self.assertRaises(ValueError):
            normalize_budget_month("2026/04")

    def test_build_budget_record_normalizes_valid_payload(self):
        self.assertEqual(
            build_budget_record("2026-04", 120000.4, " user-1 "),
            {
                "budget_month": "2026-04",
                "budget_amount": 120000,
                "auth_user_id": "user-1",
            },
        )

    def test_build_budget_record_rejects_zero_amount_boundary(self):
        with self.assertRaises(ValueError):
            build_budget_record("2026-04", 0, "user-1")

    def test_calculate_monthly_expense_total_sums_only_target_month(self):
        expenses_df = pd.DataFrame(
            [
                {"payment_date": "2026/04/01", "amount_base": 1000},
                {"payment_date": "2026-04-15", "amount_base": "2500"},
                {"payment_date": "2026/05/01", "amount_base": 9999},
                {"payment_date": "invalid", "amount_base": 500},
            ]
        )

        self.assertEqual(calculate_monthly_expense_total(expenses_df, "2026-04"), 3500)

    def test_calculate_monthly_expense_total_returns_zero_when_columns_missing(self):
        self.assertEqual(calculate_monthly_expense_total(pd.DataFrame([{"x": 1}]), "2026-04"), 0)

    def test_calculate_remaining_days_in_month_handles_current_future_past_months(self):
        self.assertEqual(calculate_remaining_days_in_month("2026-04", date(2026, 4, 30)), 1)
        self.assertEqual(calculate_remaining_days_in_month("2026-05", date(2026, 4, 4)), 31)
        self.assertEqual(calculate_remaining_days_in_month("2026-03", date(2026, 4, 4)), 0)

    def test_build_budget_summary_calculates_remaining_amount_and_daily_budget(self):
        expenses_df = pd.DataFrame(
            [
                {"payment_date": "2026/04/01", "amount_base": 3000},
                {"payment_date": "2026/04/03", "amount_base": 2000},
            ]
        )

        summary = build_budget_summary(
            budget_month="2026-04",
            budget_amount=20000,
            expenses_df=expenses_df,
            reference_date=date(2026, 4, 21),
        )

        self.assertEqual(
            summary,
            {
                "budget_month": "2026-04",
                "budget_amount": 20000,
                "used_amount": 5000,
                "remaining_amount": 15000,
                "remaining_days": 10,
                "daily_remaining_amount": 1500,
            },
        )

    def test_build_budget_summary_returns_none_daily_amount_when_remaining_days_zero(self):
        summary = build_budget_summary(
            budget_month="2026-03",
            budget_amount=20000,
            expenses_df=pd.DataFrame(),
            reference_date=date(2026, 4, 1),
        )

        self.assertEqual(summary["remaining_days"], 0)
        self.assertIsNone(summary["daily_remaining_amount"])

    def test_build_budget_month_options_merges_budget_expense_and_current_month(self):
        budgets_df = pd.DataFrame(
            [
                {"budget_month": "2026-02"},
                {"budget_month": "invalid"},
            ]
        )
        expenses_df = pd.DataFrame(
            [
                {"payment_date": "2026/03/10"},
                {"payment_date": "bad-date"},
            ]
        )

        self.assertEqual(
            build_budget_month_options(
                budgets_df,
                expenses_df,
                reference_date=date(2026, 4, 4),
            ),
            ["2026-04", "2026-03", "2026-02"],
        )

    def test_build_budget_month_options_returns_current_month_for_empty_data_boundary(self):
        self.assertEqual(
            build_budget_month_options(
                pd.DataFrame(),
                pd.DataFrame(),
                reference_date=date(2026, 4, 4),
            ),
            ["2026-04"],
        )


if __name__ == "__main__":
    unittest.main()
