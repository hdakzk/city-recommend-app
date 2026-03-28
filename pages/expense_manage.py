import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from datetime import date

st.set_page_config(
    page_title="経費管理",
    layout="wide",
)

# 画面全体を広く使う + テーブルを見やすくするCSS
st.markdown(
    """
    <style>
    .block-container {
        max-width: 100% !important;
        padding-top: 1.2rem;
        padding-left: 2rem;
        padding-right: 2rem;
        padding-bottom: 2rem;
    }

    h3 {
        text-align: center;
    }

    div[data-testid="stDataFrame"] {
        width: 100% !important;
    }

    div[data-testid="stDataEditor"] {
        width: 100% !important;
    }

    div[data-testid="stDataFrame"] div[role="table"] {
        font-size: 0.92rem;
    }

    div[data-testid="stDataEditor"] div[role="table"] {
        font-size: 0.92rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=60)
def load_sheet_csv(sheet_url: str) -> pd.DataFrame:
    if "export?format=csv" not in sheet_url:
        if "/edit?gid=" in sheet_url:
            sheet_url = sheet_url.replace("/edit?gid=", "/export?format=csv&gid=")
        elif "/edit#gid=" in sheet_url:
            sheet_url = sheet_url.replace("/edit#gid=", "/export?format=csv&gid=")
    return pd.read_csv(sheet_url)


def normalize_numeric(df: pd.DataFrame) -> pd.DataFrame:
    for col in [
        "amount",
        "exchange_rate",
        "amount_base",
        "usage_categories_id",
        "tax_categories_id",
        "sort_order",
        "id",
    ]:
        if col in df.columns:
            df[col] = (
                df[col]
                .replace("", np.nan)
                .replace(" ", np.nan)
                .pipe(pd.to_numeric, errors="coerce")
            )
    return df


def parse_mixed_datetime(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    s = s.replace({"": np.nan, "nan": np.nan, "NaT": np.nan})
    try:
        return pd.to_datetime(s, errors="coerce", format="mixed")
    except TypeError:
        return pd.to_datetime(s, errors="coerce")


def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    if "payment_date" in df.columns:
        df["payment_date"] = parse_mixed_datetime(df["payment_date"])

    if "created_at" in df.columns:
        df["created_at"] = parse_mixed_datetime(df["created_at"])

    if "updated_at" in df.columns:
        df["updated_at"] = parse_mixed_datetime(df["updated_at"])

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


def format_numeric_values_keep_float(
    df: pd.DataFrame,
    exclude_cols: list[str],
    float_cols: list[str],
) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if col in exclude_cols:
            continue
        if col in float_cols:
            out[col] = pd.to_numeric(out[col], errors="coerce")
        else:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).round(0).astype("Int64")
    return out


def build_column_config(
    df: pd.DataFrame,
    non_numeric_cols: list[str],
    float_format_cols: dict[str, str] | None = None,
) -> dict:
    config = {}
    float_format_cols = float_format_cols or {}

    for col in df.columns:
        if col in non_numeric_cols:
            continue

        if col in float_format_cols:
            config[col] = st.column_config.NumberColumn(col, format=float_format_cols[col])
        else:
            config[col] = st.column_config.NumberColumn(col, format="%,d")

    return config


def display_table(
    df: pd.DataFrame,
    non_numeric_cols: list[str],
    float_format_cols: dict[str, str] | None = None,
) -> None:
    st.data_editor(
        df,
        column_config=build_column_config(df, non_numeric_cols, float_format_cols),
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


def filter_by_date_range(df: pd.DataFrame, start_date: date, end_date: date) -> pd.DataFrame:
    if "payment_date" not in df.columns:
        return df.copy()

    out = df.copy()
    payment_date_only = out["payment_date"].dt.date
    mask = payment_date_only.between(start_date, end_date)
    return out.loc[mask].copy()


def get_selected_categories(category_order: list[str]) -> list[str]:
    if hasattr(st, "pills"):
        selected = st.pills(
            "表示カテゴリ",
            options=category_order,
            default=category_order,
            selection_mode="multi",
        )
        return list(selected) if selected else []
    return st.multiselect(
        "表示カテゴリ",
        options=category_order,
        default=category_order,
    )


def render_monthly_stacked_chart(
    df: pd.DataFrame,
    category_col: str,
    category_order: list[str],
) -> None:
    chart_source = df.copy()

    chart_source = chart_source[
        chart_source["payment_date"].notna()
        & chart_source[category_col].notna()
        & (chart_source[category_col].astype(str).str.strip() != "")
    ].copy()

    if chart_source.empty:
        st.info("グラフ表示対象のデータがありません。")
        return

    chart_source["支払月"] = chart_source["payment_date"].dt.strftime("%Y-%m")

    grouped = (
        chart_source.groupby(["支払月", category_col], as_index=False)["amount_base"]
        .sum()
        .rename(columns={category_col: "カテゴリ", "amount_base": "金額"})
    )

    if grouped.empty:
        st.info("グラフ表示対象のデータがありません。")
        return

    month_order = sorted(grouped["支払月"].dropna().unique().tolist())

    selected_categories = get_selected_categories(category_order)
    if not selected_categories:
        st.info("表示カテゴリを1つ以上選択してください。")
        return

    filtered_grouped = grouped[grouped["カテゴリ"].isin(selected_categories)].copy()

    if filtered_grouped.empty:
        st.info("選択中のカテゴリにデータがありません。")
        return

    monthly_totals = (
        filtered_grouped.groupby("支払月", as_index=False)["金額"]
        .sum()
        .rename(columns={"金額": "月合計"})
    )

    max_total = float(monthly_totals["月合計"].max()) if not monthly_totals.empty else 0.0
    offset = max(max_total * 0.05, 1000.0)
    monthly_totals["表示位置"] = monthly_totals["月合計"] + offset
    y_max = float(monthly_totals["表示位置"].max()) if not monthly_totals.empty else 0.0

    color_scale = alt.Scale(
        domain=category_order,
        range=[
            "#2F5597",
            "#4472C4",
            "#5B9BD5",
            "#70AD47",
            "#A9D18E",
            "#FFD966",
            "#FFC000",
            "#F4B183",
            "#ED7D31",
            "#C55A11",
        ],
    )

    is_single = len(selected_categories) == 1
    stack_mode = None if is_single else "zero"

    bars = (
        alt.Chart(filtered_grouped)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X(
                "支払月:N",
                sort=month_order,
                title="支払月",
                axis=alt.Axis(labelAngle=0),
            ),
            y=alt.Y(
                "金額:Q",
                title="金額",
                stack=stack_mode,
                scale=alt.Scale(zero=True, domain=[0, y_max]),
            ),
            color=alt.Color(
                "カテゴリ:N",
                sort=selected_categories,
                scale=color_scale,
                legend=alt.Legend(title="カテゴリ", orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("支払月:N", title="支払月"),
                alt.Tooltip("カテゴリ:N", title="カテゴリ"),
                alt.Tooltip("金額:Q", title="金額", format=",.0f"),
            ],
        )
    )

    total_labels = (
        alt.Chart(monthly_totals)
        .mark_text(
            dy=0,
            fontSize=12,
            fontWeight="bold",
            color="black",
        )
        .encode(
            x=alt.X(
                "支払月:N",
                sort=month_order,
                axis=alt.Axis(labelAngle=0),
            ),
            y=alt.Y(
                "表示位置:Q",
                scale=alt.Scale(zero=True, domain=[0, y_max]),
            ),
            text=alt.Text("月合計:Q", format=",.0f"),
            tooltip=[
                alt.Tooltip("支払月:N", title="支払月"),
                alt.Tooltip("月合計:Q", title="合計金額", format=",.0f"),
            ],
        )
    )

    chart = (
        alt.layer(bars, total_labels)
        .resolve_scale(y="shared")
        .properties(height=420)
        .configure_axis(grid=True)
        .configure_view(strokeWidth=0)
    )

    st.altair_chart(chart, use_container_width=True)


def main():
    st.title("経費管理")

    today = date.today()
    default_start_date = date(today.year, 1, 1)
    default_end_date = today

    col_start, col_end = st.columns(2)
    with col_start:
        start_date = st.date_input("集計開始日", value=default_start_date)
    with col_end:
        end_date = st.date_input("集計終了日", value=default_end_date)

    if start_date > end_date:
        st.error("集計開始日は集計終了日以前にしてください。")
        st.stop()

    expenses_url = st.secrets["sheets"]["expenses_url"]
    usage_url = st.secrets["sheets"]["usage_categories_url"]
    tax_url = st.secrets["sheets"]["tax_categories_url"]

    df = load_sheet_csv(expenses_url)
    df = normalize_numeric(df)
    df = parse_dates(df)

    usage_df, _ = load_categories(usage_url, "用途カテゴリ")
    tax_df, _ = load_categories(tax_url, "税務カテゴリ")

    usage_order = usage_df.sort_values("sort_order")["category_name"].tolist()
    tax_order = tax_df.sort_values("sort_order")["category_name"].tolist()

    if "usage_category_name" not in df.columns and "usage_categories_id" in df.columns:
        usage_map = usage_df.rename(columns={"id": "usage_categories_id", "category_name": "usage_category_name"})
        df = df.merge(
            usage_map[["usage_categories_id", "usage_category_name"]],
            on="usage_categories_id",
            how="left",
        )

    if "tax_category_name" not in df.columns and "tax_categories_id" in df.columns:
        tax_map = tax_df.rename(columns={"id": "tax_categories_id", "category_name": "tax_category_name"})
        df = df.merge(
            tax_map[["tax_categories_id", "tax_category_name"]],
            on="tax_categories_id",
            how="left",
        )

    filtered_df = filter_by_date_range(df, start_date, end_date)

    st.subheader("日次集計")

    category_type = st.radio("カテゴリ選択", ["用途別", "税務別"], horizontal=True)

    category_col = "usage_category_name" if category_type == "用途別" else "tax_category_name"
    category_order = usage_order if category_type == "用途別" else tax_order

    daily = create_pivot(filtered_df, "payment_date", category_col, category_order)

    if "payment_date" in daily.columns:
        daily["payment_date"] = pd.to_datetime(daily["payment_date"], errors="coerce").dt.strftime("%Y-%m-%d")

    daily = daily.rename(columns={"payment_date": "支払日"})
    daily = daily.sort_values("支払日", ascending=False)
    daily = format_numeric_values(daily, exclude_cols=["支払日"])

    display_table(daily, non_numeric_cols=["支払日"])

    st.subheader("月次集計")

    monthly_source = filtered_df.copy()
    monthly_source["month"] = monthly_source["payment_date"].dt.strftime("%Y-%m")
    monthly = create_pivot(monthly_source, "month", category_col, category_order)

    monthly = monthly.rename(columns={"month": "支払月"})
    monthly = monthly.sort_values("支払月", ascending=False)
    monthly = format_numeric_values(monthly, exclude_cols=["支払月"])

    display_table(monthly, non_numeric_cols=["支払月"])

    st.subheader("月次推移グラフ")
    render_monthly_stacked_chart(filtered_df, category_col, category_order)

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
        if c in filtered_df.columns
    ]

    raw_df = filtered_df[raw_cols].copy()

    if "payment_date" in raw_df.columns:
        raw_df["payment_date"] = raw_df["payment_date"].dt.strftime("%Y-%m-%d")

    raw_df = raw_df.rename(columns={
        "id": "ID",
        "payment_date": "支払日",
        "currency_code": "通貨",
        "amount": "金額",
        "exchange_rate": "為替レート",
        "amount_base": "円換算額",
        "payment_method": "決済方法",
        "description": "内容",
        "usage_category_name": "用途カテゴリ",
        "tax_category_name": "税務カテゴリ",
        "created_at": "作成日時",
        "updated_at": "更新日時",
    })

    if "ID" in raw_df.columns:
        raw_df = raw_df.sort_values("ID", ascending=False)

    raw_df = format_numeric_values_keep_float(
        raw_df,
        exclude_cols=["支払日", "通貨", "決済方法", "内容", "用途カテゴリ", "税務カテゴリ", "作成日時", "更新日時"],
        float_cols=["為替レート"],
    )

    display_table(
        raw_df,
        non_numeric_cols=["支払日", "通貨", "決済方法", "内容", "用途カテゴリ", "税務カテゴリ", "作成日時", "更新日時"],
        float_format_cols={"為替レート": "%.6f"},
    )


if __name__ == "__main__":
    main()