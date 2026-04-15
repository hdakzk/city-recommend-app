from datetime import date

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from utils.auth import require_authenticated_user
from utils.expense_db import (
    build_category_options,
    insert_expense_records,
    load_expense_manage_data,
    update_expense_record,
)
from utils.expense_manage_support import (
    build_expense_update_payload,
    build_wechat_expense_records,
    find_category_label_by_id,
    get_expense_row_by_id,
    get_selected_expense_id,
)

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


def normalize_numeric(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in [
        "amount",
        "exchange_rate",
        "amount_base",
        "usage_categories_id",
        "tax_categories_id",
        "sort_order",
        "id",
    ]:
        if col in out.columns:
            out[col] = (
                out[col]
                .replace("", np.nan)
                .replace(" ", np.nan)
                .pipe(pd.to_numeric, errors="coerce")
            )
    return out


def parse_mixed_datetime(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    s = s.replace({"": np.nan, "nan": np.nan, "NaT": np.nan, "None": np.nan})

    # まず標準系を試す
    try:
        parsed = pd.to_datetime(s, errors="coerce", format="mixed")
    except TypeError:
        parsed = pd.to_datetime(s, errors="coerce")

    # まだ取れないものは、"2026/03/24/14:00" のような文字列も補正して再試行
    unresolved = parsed.isna() & s.notna()
    if unresolved.any():
        s2 = s.copy()
        s2.loc[unresolved] = (
            s2.loc[unresolved]
            .str.replace(r"^(\d{4})/(\d{2})/(\d{2})/(\d{2}:\d{2})$", r"\1-\2-\3 \4", regex=True)
        )
        reparsed = pd.to_datetime(s2, errors="coerce")
        parsed.loc[unresolved] = reparsed.loc[unresolved]

    return parsed


def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    if "payment_date" in out.columns:
        out["payment_date"] = parse_mixed_datetime(out["payment_date"])

    if "created_at" in out.columns:
        out["created_at"] = parse_mixed_datetime(out["created_at"])

    if "updated_at" in out.columns:
        out["updated_at"] = parse_mixed_datetime(out["updated_at"])

    return out


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


def render_selectable_raw_data_table(
    df: pd.DataFrame,
    non_numeric_cols: list[str],
    table_version: int,
    float_format_cols: dict[str, str] | None = None,
) -> int | None:
    table_event = st.dataframe(
        df,
        column_config=build_column_config(df, non_numeric_cols, float_format_cols),
        hide_index=True,
        width="stretch",
        key=f"expense_raw_table_{table_version}",
        on_select="rerun",
        selection_mode="single-row",
    )

    selected_rows = getattr(getattr(table_event, "selection", None), "rows", [])
    return get_selected_expense_id(df, selected_rows)


def create_pivot(df: pd.DataFrame, index_col: str, category_col: str, category_order: list[str]) -> pd.DataFrame:
    if df.empty or index_col not in df.columns or category_col not in df.columns:
        return pd.DataFrame(columns=[index_col, "合計"])

    working = df.copy()
    working = working[
        working[index_col].notna()
        & working[category_col].notna()
        & (working[category_col].astype(str).str.strip() != "")
    ].copy()

    if working.empty:
        return pd.DataFrame(columns=[index_col, "合計"])

    pivot = pd.pivot_table(
        working,
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

    if category_col not in chart_source.columns:
        st.info("グラフ用カテゴリ列が存在しません。")
        return

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


def resolve_category_name_column(df: pd.DataFrame, table_label: str) -> str:
    candidates = ["category_name", "name_ja", "name", "display_name", "label"]
    for col in candidates:
        if col in df.columns:
            return col
    raise ValueError(
        f"{table_label} にカテゴリ名列が見つかりません。列一覧: {df.columns.tolist()}"
    )


def prepare_category_master(df: pd.DataFrame, table_label: str) -> pd.DataFrame:
    if df.empty:
        raise ValueError(f"{table_label} テーブルが空です。")

    out = normalize_numeric(df)
    out.columns = [str(c).strip() for c in out.columns]

    if "sort_order" in out.columns:
        out = out.sort_values("sort_order", ascending=True, na_position="last")
    else:
        out["sort_order"] = range(1, len(out) + 1)

    name_col = resolve_category_name_column(out, table_label)
    if name_col != "category_name":
        out = out.rename(columns={name_col: "category_name"})

    out["category_name"] = out["category_name"].astype(str).str.strip()
    out = out[out["category_name"] != ""].copy()

    if out.empty:
        raise ValueError(f"{table_label} に有効なカテゴリ名データがありません。")

    return out


def to_editable_payment_date(value: object) -> date:
    if pd.isna(value):
        return date.today()

    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return date.today()

    return parsed.date()


def to_editable_float(value: object) -> float:
    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return 0.0
    return float(parsed)


def reset_expense_edit_state() -> None:
    st.session_state["editing_expense_id"] = None
    st.session_state["expense_raw_table_version"] = (
        int(st.session_state.get("expense_raw_table_version", 0)) + 1
    )


def reset_wechat_import_state() -> None:
    st.session_state["wechat_import_dialog_open"] = False


@st.dialog("Wechat登録")
def render_wechat_import_dialog(user_id: str, existing_expenses_df: pd.DataFrame) -> None:
    uploaded_file = st.file_uploader(
        "WechatのExcelファイル",
        type=["xlsx"],
        accept_multiple_files=False,
        key="wechat_expense_file",
    )

    col_import, col_cancel = st.columns(2)
    with col_import:
        import_clicked = st.button(
            "取り込む",
            type="primary",
            use_container_width=True,
            disabled=uploaded_file is None,
        )
    with col_cancel:
        cancel_clicked = st.button("閉じる", use_container_width=True)

    if cancel_clicked:
        reset_wechat_import_state()
        st.rerun()

    if not import_clicked or uploaded_file is None:
        return

    try:
        records = build_wechat_expense_records(
            uploaded_file.getvalue(),
            user_id,
            existing_expenses_df=existing_expenses_df,
        )
        if not records:
            st.warning("現在状態が「支付成功」の明細が見つかりませんでした。")
            return

        insert_expense_records(records)
        st.success(f"Wechat明細を {len(records)} 件取り込みました。")
        reset_wechat_import_state()
        st.rerun()
    except Exception as e:
        st.error(f"Wechat明細の取り込みに失敗しました: {e}")


@st.dialog("経費データを編集")
def render_expense_edit_dialog(
    *,
    current_row: dict,
    usage_options: dict,
    tax_options: dict,
    user_id: str,
) -> None:
    expense_id = int(float(current_row["id"]))
    st.caption(f"ID: {expense_id}")

    payment_date_value = to_editable_payment_date(current_row.get("payment_date"))
    amount_value = to_editable_float(current_row.get("amount"))
    exchange_rate_value = to_editable_float(current_row.get("exchange_rate"))
    payment_method_options = ["現金", "クレジットカード", "電子決済", "WISE"]
    payment_method_value = str(current_row.get("payment_method") or "").strip()
    if payment_method_value and payment_method_value not in payment_method_options:
        payment_method_options = [payment_method_value] + payment_method_options
    if not payment_method_value:
        payment_method_value = payment_method_options[0]

    usage_labels = list(usage_options.keys())
    tax_labels = list(tax_options.keys())
    usage_label = find_category_label_by_id(usage_options, current_row.get("usage_categories_id"))
    tax_label = find_category_label_by_id(tax_options, current_row.get("tax_categories_id"))
    usage_index = usage_labels.index(usage_label) if usage_label in usage_labels else 0
    tax_index = tax_labels.index(tax_label) if tax_label in tax_labels else 0

    with st.form(f"expense_edit_form_{expense_id}"):
        col_date, col_amount = st.columns(2)
        with col_date:
            edited_payment_date = st.date_input(
                "支払日",
                value=payment_date_value,
                format="YYYY/MM/DD",
            )
        with col_amount:
            edited_amount = st.number_input(
                "金額",
                min_value=0.0,
                step=1.0,
                format="%.0f",
                value=amount_value,
            )

        col_rate, col_method = st.columns(2)
        with col_rate:
            edited_exchange_rate = st.number_input(
                "為替レート",
                min_value=0.0,
                step=0.001,
                format="%.6f",
                value=exchange_rate_value,
            )
        with col_method:
            edited_payment_method = st.selectbox(
                "決済方法",
                payment_method_options,
                index=payment_method_options.index(payment_method_value),
            )

        col_usage, col_tax = st.columns(2)
        with col_usage:
            edited_usage_label = st.selectbox(
                "用途カテゴリ",
                usage_labels,
                index=usage_index,
            )
        with col_tax:
            edited_tax_label = st.selectbox(
                "税務カテゴリ",
                tax_labels,
                index=tax_index,
            )

        edited_description = st.text_area(
            "内容",
            value=str(current_row.get("description") or ""),
            height=120,
        )

        col_save, col_close = st.columns(2)
        with col_save:
            save_clicked = st.form_submit_button("保存", type="primary", use_container_width=True)
        with col_close:
            close_clicked = st.form_submit_button("閉じる", use_container_width=True)

    if close_clicked:
        reset_expense_edit_state()
        st.rerun()

    if not save_clicked:
        return

    try:
        normalized_expense_id, payload = build_expense_update_payload(
            expense_id=expense_id,
            payment_date_value=edited_payment_date,
            amount=edited_amount,
            exchange_rate=edited_exchange_rate,
            payment_method=edited_payment_method,
            description=edited_description,
            usage_category_id=usage_options[edited_usage_label],
            tax_category_id=tax_options[edited_tax_label],
        )
        update_expense_record(normalized_expense_id, user_id, payload)
        st.success("経費データを更新しました。")
        reset_expense_edit_state()
        st.rerun()
    except Exception as e:
        st.error(f"更新に失敗しました: {e}")


def main():
    user = require_authenticated_user()
    user_id = str(getattr(user, "id"))

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

    try:
        df, usage_df, tax_df = load_expense_manage_data(user_id)
    except TypeError:
        # 旧版 expense_db.py 互換
        df, usage_df, tax_df = load_expense_manage_data()
    except Exception as e:
        st.error(f"経費データの読み込みに失敗しました: {e}")
        st.stop()

    if st.button("Wechat登録", type="secondary"):
        st.session_state["wechat_import_dialog_open"] = True

    if st.session_state.get("wechat_import_dialog_open", False):
        render_wechat_import_dialog(user_id, df)

    if df.empty:
        st.info("経費データがありません。")
        st.stop()

    df = normalize_numeric(df)
    df = parse_dates(df)

    try:
        usage_df = prepare_category_master(usage_df, "usage_categories")
        tax_df = prepare_category_master(tax_df, "tax_categories")
    except Exception as e:
        st.error(str(e))
        with st.expander("カテゴリテーブルの列一覧"):
            st.write("usage_categories:", usage_df.columns.tolist())
            st.write("tax_categories:", tax_df.columns.tolist())
        st.stop()

    usage_order = usage_df["category_name"].dropna().astype(str).tolist()
    tax_order = tax_df["category_name"].dropna().astype(str).tolist()
    usage_options = build_category_options(usage_df)
    tax_options = build_category_options(tax_df)

    if "usage_category_name" not in df.columns and "usage_categories_id" in df.columns:
        usage_map = usage_df.rename(
            columns={
                "id": "usage_categories_id",
                "category_name": "usage_category_name",
            }
        )
        df = df.merge(
            usage_map[["usage_categories_id", "usage_category_name"]],
            on="usage_categories_id",
            how="left",
        )

    if "tax_category_name" not in df.columns and "tax_categories_id" in df.columns:
        tax_map = tax_df.rename(
            columns={
                "id": "tax_categories_id",
                "category_name": "tax_category_name",
            }
        )
        df = df.merge(
            tax_map[["tax_categories_id", "tax_category_name"]],
            on="tax_categories_id",
            how="left",
        )

    filtered_df = filter_by_date_range(df, start_date, end_date)

    if filtered_df.empty:
        st.info("指定期間のデータがありません。")
        st.stop()

    st.subheader("日次集計")

    category_type = st.radio("カテゴリ選択", ["用途別", "税務別"], horizontal=True)
    category_col = "usage_category_name" if category_type == "用途別" else "tax_category_name"
    category_order = usage_order if category_type == "用途別" else tax_order

    daily = create_pivot(filtered_df, "payment_date", category_col, category_order)

    if daily.empty:
        st.info("集計対象データがありません。")
    else:
        if "payment_date" in daily.columns:
            daily["payment_date"] = pd.to_datetime(daily["payment_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        daily = daily.rename(columns={"payment_date": "支払日"})
        daily = daily.sort_values("支払日", ascending=False)
        daily = format_numeric_values(daily, exclude_cols=["支払日"])
        display_table(daily, non_numeric_cols=["支払日"])

    st.subheader("月次集計")

    monthly_source = filtered_df.copy()
    if "payment_date" in monthly_source.columns:
        monthly_source = monthly_source[monthly_source["payment_date"].notna()].copy()
        monthly_source["month"] = monthly_source["payment_date"].dt.strftime("%Y-%m")

    monthly = create_pivot(monthly_source, "month", category_col, category_order)

    if monthly.empty:
        st.info("月次集計対象データがありません。")
    else:
        monthly = monthly.rename(columns={"month": "支払月"})
        monthly = monthly.sort_values("支払月", ascending=False)
        monthly = format_numeric_values(monthly, exclude_cols=["支払月"])
        display_table(monthly, non_numeric_cols=["支払月"])

    st.subheader("月次推移グラフ")
    render_monthly_stacked_chart(filtered_df, category_col, category_order)

    st.subheader("元データ")
    st.caption("IDの行をタップ/クリックすると編集画面が開きます。")

    raw_cols = [
        c
        for c in [
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

    if "created_at" in raw_df.columns:
        raw_df["created_at"] = pd.to_datetime(raw_df["created_at"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")

    if "updated_at" in raw_df.columns:
        raw_df["updated_at"] = pd.to_datetime(raw_df["updated_at"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")

    raw_df = raw_df.rename(
        columns={
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
        }
    )

    if "ID" in raw_df.columns:
        raw_df = raw_df.sort_values("ID", ascending=False)

    raw_df = format_numeric_values_keep_float(
        raw_df,
        exclude_cols=["支払日", "通貨", "決済方法", "内容", "用途カテゴリ", "税務カテゴリ", "作成日時", "更新日時"],
        float_cols=["為替レート"],
    )

    table_version = int(st.session_state.get("expense_raw_table_version", 0))
    selected_expense_id = render_selectable_raw_data_table(
        raw_df,
        non_numeric_cols=["支払日", "通貨", "決済方法", "内容", "用途カテゴリ", "税務カテゴリ", "作成日時", "更新日時"],
        table_version=table_version,
        float_format_cols={"為替レート": "%.6f"},
    )

    if selected_expense_id is not None:
        st.session_state["editing_expense_id"] = selected_expense_id

    editing_expense_id = st.session_state.get("editing_expense_id")
    if editing_expense_id is None:
        return

    current_row = get_expense_row_by_id(df, editing_expense_id)
    if current_row is None:
        reset_expense_edit_state()
        st.warning("編集対象の経費データが見つかりませんでした。")
        st.rerun()

    render_expense_edit_dialog(
        current_row=current_row,
        usage_options=usage_options,
        tax_options=tax_options,
        user_id=user_id,
    )


if __name__ == "__main__":
    main()
