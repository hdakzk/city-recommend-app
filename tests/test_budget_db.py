import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from utils import budget_db
from utils.expense_db import _fetch_all_rows


class _FakeQuery:
    def __init__(self, response_rows=None):
        self.response_rows = [] if response_rows is None else list(response_rows)
        self.selected_columns = None
        self.filters = []
        self.limit_count = None
        self.insert_payload = None
        self.update_payload = None
        self.range_args = []

    def select(self, columns):
        self.selected_columns = columns
        return self

    def eq(self, column_name, value):
        self.filters.append((column_name, value))
        return self

    def limit(self, count):
        self.limit_count = count
        return self

    def range(self, start, end):
        self.range_args.append((start, end))
        return self

    def insert(self, payload):
        self.insert_payload = payload
        return self

    def update(self, payload):
        self.update_payload = payload
        return self

    def execute(self):
        return SimpleNamespace(data=self.response_rows)


class _FakeClient:
    def __init__(self, queries):
        self.queries = queries
        self.table_names = []

    def table(self, table_name):
        self.table_names.append(table_name)
        return self.queries[len(self.table_names) - 1]


class _FakeCacheData:
    def __init__(self):
        self.clear_call_count = 0

    def clear(self):
        self.clear_call_count += 1


class _FakeStreamlit:
    def __init__(self):
        self.cache_data = _FakeCacheData()


class BudgetDbTest(unittest.TestCase):
    def test_get_budget_amount_for_month_returns_latest_matching_amount(self):
        budgets_df = pd.DataFrame(
            [
                {"budget_month": "2026-04", "budget_amount": "100000"},
                {"budget_month": "2026-05", "budget_amount": 200000},
            ]
        )

        self.assertEqual(budget_db.get_budget_amount_for_month(budgets_df, "2026-04"), 100000)
        self.assertEqual(budget_db.get_budget_amount_for_month(budgets_df, "2026-06"), 0)

    def test_upsert_monthly_budget_inserts_when_month_record_does_not_exist(self):
        select_query = _FakeQuery(response_rows=[])
        insert_query = _FakeQuery()
        fake_client = _FakeClient([select_query, insert_query])
        fake_st = _FakeStreamlit()

        with patch.object(budget_db, "get_supabase_client", return_value=fake_client), patch.object(budget_db, "st", fake_st):
            record = budget_db.upsert_monthly_budget("2026-04", 120000, "user-1")

        self.assertEqual(record["budget_month"], "2026-04")
        self.assertEqual(fake_client.table_names, ["monthly_budgets", "monthly_budgets"])
        self.assertEqual(
            select_query.filters,
            [("auth_user_id", "user-1"), ("budget_month", "2026-04")],
        )
        self.assertEqual(insert_query.insert_payload, record)
        self.assertEqual(fake_st.cache_data.clear_call_count, 1)

    def test_upsert_monthly_budget_updates_when_month_record_exists(self):
        select_query = _FakeQuery(response_rows=[{"id": 9}])
        update_query = _FakeQuery()
        fake_client = _FakeClient([select_query, update_query])
        fake_st = _FakeStreamlit()

        with patch.object(budget_db, "get_supabase_client", return_value=fake_client), patch.object(budget_db, "st", fake_st):
            budget_db.upsert_monthly_budget("2026-04", 130000, "user-1")

        self.assertEqual(update_query.update_payload, {"budget_amount": 130000})
        self.assertEqual(update_query.filters, [("id", 9), ("auth_user_id", "user-1")])
        self.assertEqual(fake_st.cache_data.clear_call_count, 1)

    def test_fetch_all_rows_filters_monthly_budgets_by_user_id(self):
        query = _FakeQuery(response_rows=[])
        fake_client = _FakeClient([query])

        with patch("utils.expense_db.get_supabase_client", return_value=fake_client):
            out = _fetch_all_rows("monthly_budgets", user_id="user-1")

        self.assertTrue(out.empty)
        self.assertEqual(query.filters, [("auth_user_id", "user-1")])
        self.assertEqual(query.range_args, [(0, 999)])


if __name__ == "__main__":
    unittest.main()
