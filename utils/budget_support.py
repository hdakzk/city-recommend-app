from __future__ import annotations

import calendar
from datetime import date
from typing import Any

import pandas as pd


def normalize_budget_month(month_value: Any) -> str:
    if isinstance(month_value, date):
        return month_value.strftime("%Y-%m")

    normalized_text = str(month_value or "").strip()
    parsed = pd.to_datetime(normalized_text, format="%Y-%m", errors="coerce")
    if pd.isna(parsed):
        raise ValueError("対象月は YYYY-MM 形式で入力してください。")

    return parsed.strftime("%Y-%m")


def build_budget_record(month_value: Any, budget_amount: Any, auth_user_id: str) -> dict[str, Any]:
    normalized_month = normalize_budget_month(month_value)

    try:
        normalized_budget_amount = int(round(float(budget_amount)))
    except (TypeError, ValueError):
        raise ValueError("予算金額は数値で入力してください。") from None

    if normalized_budget_amount <= 0:
        raise ValueError("予算金額は 0 より大きい値を入力してください。")

    normalized_user_id = str(auth_user_id or "").strip()
    if not normalized_user_id:
        raise ValueError("ログインユーザーIDを取得できませんでした。")

    return {
        "budget_month": normalized_month,
        "budget_amount": normalized_budget_amount,
        "auth_user_id": normalized_user_id,
    }


def calculate_monthly_expense_total(expenses_df: pd.DataFrame, budget_month: str) -> int:
    if expenses_df.empty or "payment_date" not in expenses_df.columns or "amount_base" not in expenses_df.columns:
        return 0

    normalized_month = normalize_budget_month(budget_month)
    out = expenses_df[["payment_date", "amount_base"]].copy()
    out["payment_date"] = pd.to_datetime(out["payment_date"], format="mixed", errors="coerce")
    out["amount_base"] = pd.to_numeric(out["amount_base"], errors="coerce").fillna(0)
    month_mask = out["payment_date"].dt.strftime("%Y-%m") == normalized_month
    return int(round(float(out.loc[month_mask, "amount_base"].sum())))


def calculate_remaining_days_in_month(budget_month: str, reference_date: date | None = None) -> int:
    normalized_month = normalize_budget_month(budget_month)
    year, month = map(int, normalized_month.split("-"))
    reference = reference_date or date.today()
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    if reference.year == year and reference.month == month:
        return max((last_day - reference).days + 1, 0)

    month_first_day = date(year, month, 1)
    if reference < month_first_day:
        return last_day.day

    return 0


def build_budget_summary(
    *,
    budget_month: str,
    budget_amount: Any,
    expenses_df: pd.DataFrame,
    reference_date: date | None = None,
) -> dict[str, int | str | None]:
    normalized_month = normalize_budget_month(budget_month)

    try:
        normalized_budget_amount = int(round(float(budget_amount)))
    except (TypeError, ValueError):
        normalized_budget_amount = 0

    used_amount = calculate_monthly_expense_total(expenses_df, normalized_month)
    remaining_amount = normalized_budget_amount - used_amount
    remaining_days = calculate_remaining_days_in_month(normalized_month, reference_date)
    daily_remaining_amount = (
        int(remaining_amount // remaining_days)
        if remaining_days > 0
        else None
    )

    return {
        "budget_month": normalized_month,
        "budget_amount": normalized_budget_amount,
        "used_amount": used_amount,
        "remaining_amount": remaining_amount,
        "remaining_days": remaining_days,
        "daily_remaining_amount": daily_remaining_amount,
    }


def build_budget_month_options(
    budgets_df: pd.DataFrame,
    expenses_df: pd.DataFrame,
    reference_date: date | None = None,
) -> list[str]:
    month_values = {normalize_budget_month(reference_date or date.today())}

    if not budgets_df.empty and "budget_month" in budgets_df.columns:
        for raw_month in budgets_df["budget_month"].dropna().tolist():
            try:
                month_values.add(normalize_budget_month(raw_month))
            except ValueError:
                continue

    if not expenses_df.empty and "payment_date" in expenses_df.columns:
        payment_months = pd.to_datetime(
            expenses_df["payment_date"],
            format="mixed",
            errors="coerce",
        ).dropna().dt.strftime("%Y-%m")
        month_values.update(payment_months.tolist())

    return sorted(month_values, reverse=True)
