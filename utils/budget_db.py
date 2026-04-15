from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from utils.budget_support import build_budget_record, normalize_budget_month
from utils.expense_db import _fetch_all_rows, _normalize_columns
from utils.supabase_client import get_supabase_client


@st.cache_data(ttl=60, show_spinner=False)
def load_monthly_budget_data(user_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    budgets_df = _normalize_columns(_fetch_all_rows("monthly_budgets", user_id=user_id))
    expenses_df = _normalize_columns(_fetch_all_rows("expenses", user_id=user_id))
    return budgets_df, expenses_df


def get_budget_amount_for_month(budgets_df: pd.DataFrame, budget_month: str) -> int:
    if budgets_df.empty or "budget_month" not in budgets_df.columns or "budget_amount" not in budgets_df.columns:
        return 0

    normalized_month = normalize_budget_month(budget_month)
    matched_rows = budgets_df[budgets_df["budget_month"].astype(str).str.strip() == normalized_month]
    if matched_rows.empty:
        return 0

    budget_amount = pd.to_numeric(matched_rows.iloc[-1]["budget_amount"], errors="coerce")
    if pd.isna(budget_amount):
        return 0
    return int(round(float(budget_amount)))


def upsert_monthly_budget(month_value: Any, budget_amount: Any, user_id: str) -> dict[str, Any]:
    record = build_budget_record(month_value, budget_amount, user_id)
    client = get_supabase_client(use_session=True)

    response = (
        client.table("monthly_budgets")
        .select("id")
        .eq("auth_user_id", record["auth_user_id"])
        .eq("budget_month", record["budget_month"])
        .limit(1)
        .execute()
    )
    rows = response.data or []

    if rows:
        budget_id = int(float(rows[0]["id"]))
        client.table("monthly_budgets").update(
            {"budget_amount": record["budget_amount"]}
        ).eq("id", budget_id).eq("auth_user_id", record["auth_user_id"]).execute()
    else:
        client.table("monthly_budgets").insert(record).execute()

    st.cache_data.clear()
    return record
