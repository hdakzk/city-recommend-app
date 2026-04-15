import math
from datetime import date
from typing import Any, Dict

import pandas as pd
import requests
import streamlit as st

from utils.auth import require_authenticated_user
from utils.expense_db import (
    build_category_options,
    build_expense_record,
    insert_expense_record,
    load_expense_master_data,
    upload_expense_receipt,
)

PAGE_TITLE = "経費登録"
BASE_CURRENCY = "JPY"
VND_FIXED_RATE_TO_JPY = 0.006
FIXED_PAYMENT_CURRENCY = "VND"
PAYMENT_METHODS = ["現金", "クレジットカード", "電子決済", "WISE"]
FRANKFURTER_URL = "https://api.frankfurter.dev/v2/rates"
RECEIPT_DIALOG_STATE_KEY = "expense_receipt_dialog_open"
RECEIPT_BYTES_STATE_KEY = "expense_receipt_file_bytes"
RECEIPT_NAME_STATE_KEY = "expense_receipt_file_name"
RECEIPT_TYPE_STATE_KEY = "expense_receipt_content_type"


# =========================
# Exchange-rate helpers
# =========================
def get_exchange_rate(
    payment_date: date,
    currency_code: str,
    base_currency: str = BASE_CURRENCY,
) -> float:
    currency_code = currency_code.upper().strip()
    base_currency = base_currency.upper().strip()

    if currency_code == base_currency:
        return 1.0

    if currency_code == "VND" and base_currency == "JPY":
        return VND_FIXED_RATE_TO_JPY

    params = {
        "date": payment_date.strftime("%Y-%m-%d"),
        "base": currency_code,
        "quotes": base_currency,
    }
    response = requests.get(FRANKFURTER_URL, params=params, timeout=15)
    response.raise_for_status()

    data = response.json()
    if not isinstance(data, list) or len(data) == 0:
        raise ValueError(f"Frankfurter API の応答が不正です: {data}")

    rate = float(data[0]["rate"])
    if math.isclose(rate, 0.0):
        raise ValueError(f"為替レートが 0 です: {currency_code} -> {base_currency}")
    return rate


def calculate_amount_base(amount: float, exchange_rate: float) -> int:
    return int(round(amount * exchange_rate))


# =========================
# UI
# =========================
def apply_form_css() -> None:
    st.markdown(
        """
        <style>
        div[data-testid="stDateInput"] input,
        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input {
            height: 52px !important;
            font-size: 16px !important;
        }

        div[data-baseweb="select"] > div {
            min-height: 52px !important;
            font-size: 16px !important;
        }

        textarea {
            font-size: 16px !important;
        }

        button[kind="primary"] {
            min-height: 52px !important;
            font-size: 16px !important;
        }

        div[data-testid="stDataFrame"] div[role="columnheader"] {
            justify-content: center !important;
            text-align: center !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_summary_preview(expenses_df: pd.DataFrame) -> None:
    st.subheader("直近の登録データ")

    if expenses_df.empty:
        st.info("まだ経費データがありません。")
        return

    preview_cols = [
        col
        for col in [
            "id",
            "payment_date",
            "currency_code",
            "amount",
            "exchange_rate",
            "amount_base",
            "payment_method",
            "description",
            "updated_at",
        ]
        if col in expenses_df.columns
    ]

    preview_df = expenses_df[preview_cols].copy()

    if "payment_date" in preview_df.columns:
        preview_df["payment_date_sort"] = pd.to_datetime(
            preview_df["payment_date"],
            format="%Y/%m/%d",
            errors="coerce",
        )
        preview_df = (
            preview_df.sort_values("payment_date_sort", ascending=False, na_position="last")
            .drop(columns=["payment_date_sort"])
            .head(10)
        )
    else:
        preview_df = preview_df.tail(10)

    rename_map = {
        "id": "ID",
        "payment_date": "決済日",
        "currency_code": "決済通貨",
        "amount": "金額",
        "exchange_rate": "換算レート",
        "amount_base": "円換算額",
        "payment_method": "決済方法",
        "description": "内容",
        "updated_at": "更新日時",
    }
    preview_df = preview_df.rename(columns=rename_map)

    if "金額" in preview_df.columns:
        preview_df["金額"] = pd.to_numeric(preview_df["金額"], errors="coerce").map(
            lambda x: f"{x:,.0f}" if pd.notna(x) else ""
        )

    if "円換算額" in preview_df.columns:
        preview_df["円換算額"] = pd.to_numeric(preview_df["円換算額"], errors="coerce").map(
            lambda x: f"{x:,.0f}" if pd.notna(x) else ""
        )

    st.dataframe(preview_df, width="content")


def clear_receipt_state() -> None:
    st.session_state[RECEIPT_DIALOG_STATE_KEY] = False
    st.session_state.pop(RECEIPT_BYTES_STATE_KEY, None)
    st.session_state.pop(RECEIPT_NAME_STATE_KEY, None)
    st.session_state.pop(RECEIPT_TYPE_STATE_KEY, None)


@st.dialog("レシート登録")
def render_receipt_capture_dialog() -> None:
    captured_file = st.camera_input("レシートを撮影", key="expense_receipt_camera")

    if captured_file is not None:
        st.session_state[RECEIPT_BYTES_STATE_KEY] = captured_file.getvalue()
        st.session_state[RECEIPT_NAME_STATE_KEY] = captured_file.name
        st.session_state[RECEIPT_TYPE_STATE_KEY] = captured_file.type
        st.image(captured_file, caption="撮影したレシート", use_container_width=True)
        st.success("レシート画像を保持しました。元の画面で「登録」を押すと保存します。")

    if st.button("閉じる", use_container_width=True):
        st.session_state[RECEIPT_DIALOG_STATE_KEY] = False
        st.rerun()


def main() -> None:
    apply_form_css()

    user = require_authenticated_user()
    user_id = str(getattr(user, "id"))

    st.title(PAGE_TITLE)
    st.caption("旅行・滞在中の支出を登録します。VND は固定レート 0.006 JPY で換算します。")

    try:
        expenses_df, usage_df, tax_df = load_expense_master_data(user_id)
    except Exception as e:
        st.error(f"初期データの読み込みに失敗しました: {e}")
        st.stop()

    usage_options: Dict[str, Any] = build_category_options(usage_df)
    tax_options: Dict[str, Any] = build_category_options(tax_df)

    if not usage_options:
        st.error("usage_categories テーブルの読み込みに失敗したか、カテゴリが存在しません。")
        st.stop()

    if not tax_options:
        st.error("tax_categories テーブルの読み込みに失敗したか、カテゴリが存在しません。")
        st.stop()

    with st.form("expense_register_form"):
        row1_col1, row1_col2 = st.columns(2)
        with row1_col1:
            payment_date_value = st.date_input("決済日", value=date.today(), format="YYYY/MM/DD")
        with row1_col2:
            st.text_input("決済通貨", value=FIXED_PAYMENT_CURRENCY, disabled=True)

        row2_col1, row2_col2 = st.columns(2)
        with row2_col1:
            amount = st.number_input("金額", min_value=0.0, step=1.0, format="%.0f")
        with row2_col2:
            payment_method = st.selectbox("決済方法", PAYMENT_METHODS, index=0)

        row3_col1, row3_col2 = st.columns(2)
        with row3_col1:
            usage_label = st.selectbox("用途別カテゴリ", list(usage_options.keys()), index=0)
        with row3_col2:
            tax_label = st.selectbox("税務別カテゴリ", list(tax_options.keys()), index=0)

        description = st.text_area(
            "内容",
            placeholder="例: ランチ、ホテル代、Grab など",
            height=110,
        )

        receipt_clicked = st.form_submit_button("レシート登録", width="content")
        submitted = st.form_submit_button("登録", width="content")

    if receipt_clicked:
        st.session_state[RECEIPT_DIALOG_STATE_KEY] = True

    if st.session_state.get(RECEIPT_DIALOG_STATE_KEY, False):
        render_receipt_capture_dialog()

    if st.session_state.get(RECEIPT_BYTES_STATE_KEY):
        st.caption(f"レシート撮影済み: {st.session_state.get(RECEIPT_NAME_STATE_KEY, '')}")

    if submitted:
        if amount <= 0:
            st.error("金額は 0 より大きい値を入力してください。")
            st.stop()

        try:
            currency_code = FIXED_PAYMENT_CURRENCY
            exchange_rate = get_exchange_rate(payment_date_value, currency_code, BASE_CURRENCY)
            amount_base = calculate_amount_base(amount, exchange_rate)

            st.info(
                f"換算結果: {amount:,.0f} {currency_code} × {exchange_rate:.6f} = {amount_base:,} {BASE_CURRENCY}"
            )

            receipt_storage_path = None
            receipt_file_bytes = st.session_state.get(RECEIPT_BYTES_STATE_KEY)
            if receipt_file_bytes:
                receipt_storage_path = upload_expense_receipt(
                    file_content=receipt_file_bytes,
                    original_file_name=str(st.session_state.get(RECEIPT_NAME_STATE_KEY, "receipt.jpg")),
                    content_type=str(st.session_state.get(RECEIPT_TYPE_STATE_KEY, "image/jpeg")),
                    payment_date_value=payment_date_value,
                    auth_user_id=user_id,
                )

            record = build_expense_record(
                payment_date_value=payment_date_value,
                currency_code=currency_code,
                amount=amount,
                exchange_rate=exchange_rate,
                amount_base=amount_base,
                payment_method=payment_method,
                description=description.strip(),
                usage_category_id=usage_options[usage_label],
                tax_category_id=tax_options[tax_label],
                auth_user_id=user_id,
                receipt_storage_path=receipt_storage_path,
            )

            insert_expense_record(record)
            clear_receipt_state()
            st.success("経費を登録しました。")
            st.rerun()

        except Exception as e:
            st.error(f"登録に失敗しました: {e}")

    render_summary_preview(expenses_df)


if __name__ == "__main__":
    main()
