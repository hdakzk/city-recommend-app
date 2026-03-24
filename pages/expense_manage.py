import streamlit as st
import pandas as pd
import numpy as np


@st.cache_data(ttl=60)
def load_sheet_csv(sheet_url: str) -> pd.DataFrame:
    if "export?format=csv" not in sheet_url:
        if "/edit?gid=" in sheet_url:
            sheet_url = sheet_url.replace("/edit?gid=", "/export?format=csv&gid=")
        elif "/edit#gid=" in sheet_url:
            sheet_url = sheet_url.replace("/edit#gid=", "/export?format=csv&gid=")
    return pd.read_csv(sheet_url)


def normalize_numeric(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["amount", "exchange_rate", "amount_base", "usage_categories_id", "tax_categories_id", "sort_order", "id"]:
        if col in df.columns:
            df[col] = (
                df[col]
                .replace("", np.nan)
                .replace(" ", np.nan)
                .pipe(pd.to_numeric, errors="coerce")
            )
    return df


def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    if "payment_date" in df.columns:
        df["payment_date"] = pd.to_datetime(df["payment_date"], errors="coerce")
    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    if "updated_at" in df.columns:
        df["updated_at"] = pd.to_datetime(df["updated_at"], errors="coerce")
    return df


def pick_first_existing_column(df: pd.DataFrame, candidates: list[str], label: str) -> str:
    for col in candidates:
        if col in df.columns:
            return col
    raise KeyError(f"{label} に使える列が見つかりません。columns={df.columns.tolist()}")


def load_categories(sheet_url: str, kind: str) -> tuple[pd.DataFrame, str]:
    df = load_sheet_csv(sheet_url)
    df = normalize_numeric(df)

    id_col = pick_first_existing_column(df, ["id"], f"{kind} ID列")
    name_col = pick_first_existing_column(
        df,
        ["name_ja", "name", "category_name", "usage_category_name", "tax_category_name"],
        f"{kind} 名称列",
    )

    if "sort_order" in df.columns:
        df = df.sort_values("sort_order", ascending=True, na_position="last")
    else:
        df["sort_order"] = range(1, len(df) + 1)

    df = df[[id_col, name_col, "sort_order"]].copy()
    df.columns = ["id", "category_name", "sort_order"]
    df["id"] = pd.to_numeric(df["id"], errors="coerce")
    df["sort_order"] = pd.to_numeric(df["sort_order"], errors="coerce")

    return df, "category_name"


def format_numeric_values(df: pd.DataFrame, exclude_cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if col not in exclude_cols:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).round(0).astype("Int64")
    return out


def build_column_config(df: pd.DataFrame, non_numeric_cols: list[str]) -> dict:
    config = {}
    for col in df.columns:
        if col not in non_numeric_cols:
            config[col] = st.column_config.NumberColumn(col, format="%,d")
    return config


def display_table(df: pd.DataFrame, non_numeric_cols: list[str]) -> None:
    st.data_editor(
        df,
        column_config=build_column_config(df, non_numeric_cols),
        disabled=True,
        hide_index=True,
        width="stretch",
    )


def create_pivot(df: pd.DataFrame, index_col: str, category_col: str, category_order: list[str]) -> pd.DataFrame:
    pivot = pd.pivot_table(
        df,
        index=index_col,
        columns=category_col,
        values="amount_base",
        aggfunc="sum",
        fill_value=0,
    )

    pivot = pivot.reindex(columns=category_order, fill_value=0)
    pivot.insert(0, "合計", pivot.sum(axis=1))
    pivot = pivot.reset_index()

    return pivot


def main():
    st.title("経費管理")

    expenses_url = st.secrets["sheets"]["expenses_url"]
    usage_url = st.secrets["sheets"]["usage_categories_url"]
    tax_url = st.secrets["sheets"]["tax_categories_url"]

    # 元データ
    df = load_sheet_csv(expenses_url)
    df = normalize_numeric(df)
    df = parse_dates(df)

    # カテゴリマスタ
    usage_df, _ = load_categories(usage_url, "用途カテゴリ")
    tax_df, _ = load_categories(tax_url, "税務カテゴリ")

    usage_order = usage_df.sort_values("sort_order")["category_name"].tolist()
    tax_order = tax_df.sort_values("sort_order")["category_name"].tolist()

    # Expensesにカテゴリ名が無ければID結合で補完
    if "usage_category_name" not in df.columns and "usage_categories_id" in df.columns:
        usage_map = usage_df.rename(columns={"id": "usage_categories_id", "category_name": "usage_category_name"})
        df = df.merge(usage_map[["usage_categories_id", "usage_category_name"]], on="usage_categories_id", how="left")

    if "tax_category_name" not in df.columns and "tax_categories_id" in df.columns:
        tax_map = tax_df.rename(columns={"id": "tax_categories_id", "category_name": "tax_category_name"})
        df = df.merge(tax_map[["tax_categories_id", "tax_category_name"]], on="tax_categories_id", how="left")

    

    st.subheader("日次集計")

    category_type = st.radio("カテゴリ選択", ["用途別", "税務別"], horizontal=True)

    if category_type == "用途別":
        category_col = "usage_category_name"
        category_order = usage_order
    else:
        category_col = "tax_category_name"
        category_order = tax_order

    daily_source = df.copy()
    if "created_at" in daily_source.columns:
        daily_source = daily_source.sort_values("created_at", ascending=False, na_position="last")

    daily = create_pivot(daily_source, "payment_date", category_col, category_order)
    daily = daily.sort_values("payment_date", ascending=False, na_position="last")
    daily = format_numeric_values(daily, exclude_cols=["payment_date"])

    display_table(daily, non_numeric_cols=["payment_date"])

    st.subheader("月次集計")

    monthly_source = df.copy()
    monthly_source["month"] = monthly_source["payment_date"].dt.strftime("%Y-%m")
    monthly = create_pivot(monthly_source, "month", category_col, category_order)
    monthly = monthly.sort_values("month", ascending=False, na_position="last")
    monthly = format_numeric_values(monthly, exclude_cols=["month"])

    display_table(monthly, non_numeric_cols=["month"])

    st.subheader("元データ")

    raw_cols = [
        c for c in [
            "id",
            "payment_date",
            "currency_code",
            "amount",
            "exchange_rate",
            "amount_base",
            "payment_method",
            "description",
            "usage_category_name",
            "tax_category_name",
            "created_at",
            "updated_at",
        ]
        if c in df.columns
    ]

    raw_df = df[raw_cols].copy()
    if "created_at" in raw_df.columns:
        raw_df = raw_df.sort_values("created_at", ascending=False, na_position="last")

    raw_df = format_numeric_values(
        raw_df,
        exclude_cols=["payment_date", "currency_code", "payment_method", "description", "usage_category_name", "tax_category_name", "created_at", "updated_at"],
    )

    display_table(
        raw_df,
        non_numeric_cols=["payment_date", "currency_code", "payment_method", "description", "usage_category_name", "tax_category_name", "created_at", "updated_at"],
    )


if __name__ == "__main__":
    main()
