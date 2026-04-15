from datetime import date

import pandas as pd
import streamlit as st

from utils.auth import require_authenticated_user
from utils.budget_db import get_budget_amount_for_month, load_monthly_budget_data, upsert_monthly_budget
from utils.budget_support import build_budget_month_options, build_budget_summary

st.set_page_config(
    page_title="予算管理",
    layout="wide",
)


def render_budget_metrics(summary: dict[str, int | str | None]) -> None:
    col_budget, col_used, col_remaining, col_daily = st.columns(4)

    with col_budget:
        st.metric("予算金額", f"{int(summary['budget_amount']):,} 円")
    with col_used:
        st.metric("当月使用額", f"{int(summary['used_amount']):,} 円")
    with col_remaining:
        st.metric("予算の残額", f"{int(summary['remaining_amount']):,} 円")
    with col_daily:
        daily_remaining_amount = summary["daily_remaining_amount"]
        if daily_remaining_amount is None:
            st.metric("一日あたりの残額", "算出不可")
        else:
            st.metric("一日あたりの残額", f"{int(daily_remaining_amount):,} 円")


def render_budget_history(budgets_df: pd.DataFrame) -> None:
    st.subheader("登録済み予算")

    if budgets_df.empty:
        st.info("まだ予算データがありません。")
        return

    history_cols = [col for col in ["budget_month", "budget_amount", "updated_at", "created_at"] if col in budgets_df.columns]
    history_df = budgets_df[history_cols].copy()

    if "budget_month" in history_df.columns:
        history_df = history_df.sort_values("budget_month", ascending=False)

    history_df = history_df.rename(
        columns={
            "budget_month": "対象月",
            "budget_amount": "予算金額",
            "updated_at": "更新日時",
            "created_at": "作成日時",
        }
    )

    if "予算金額" in history_df.columns:
        history_df["予算金額"] = pd.to_numeric(history_df["予算金額"], errors="coerce").fillna(0).round(0).astype("Int64")

    st.dataframe(
        history_df,
        hide_index=True,
        width="stretch",
        column_config={"予算金額": st.column_config.NumberColumn("予算金額", format="%,d")},
    )


def main() -> None:
    user = require_authenticated_user()
    user_id = str(getattr(user, "id"))

    st.title("予算管理")
    st.caption("月次予算を登録し、当月使用額と残額を確認します。")

    today = date.today()
    default_month = today.strftime("%Y-%m")

    try:
        budgets_df, expenses_df = load_monthly_budget_data(user_id)
    except Exception as e:
        st.error(f"予算データの読み込みに失敗しました: {e}")
        st.stop()

    month_options = build_budget_month_options(
        budgets_df,
        expenses_df,
        reference_date=today,
    )
    default_month_index = month_options.index(default_month) if default_month in month_options else 0
    budget_month = st.selectbox("対象月", options=month_options, index=default_month_index)

    current_budget_amount = get_budget_amount_for_month(budgets_df, budget_month)
    summary = build_budget_summary(
        budget_month=budget_month,
        budget_amount=current_budget_amount,
        expenses_df=expenses_df,
        reference_date=today,
    )

    render_budget_metrics(summary)

    st.subheader("予算登録 / 更新")
    with st.form("monthly_budget_form"):
        budget_amount = st.number_input(
            "予算金額",
            min_value=0,
            step=1000,
            value=int(current_budget_amount),
        )
        submitted = st.form_submit_button("登録", use_container_width=True)

    if submitted:
        try:
            upsert_monthly_budget(budget_month, budget_amount, user_id)
            st.success(f"{budget_month} の予算を登録しました。")
            st.rerun()
        except Exception as e:
            st.error(f"予算登録に失敗しました: {e}")

    render_budget_history(budgets_df)


if __name__ == "__main__":
    main()
