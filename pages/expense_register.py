import math
from datetime import datetime, date
from typing import Any, Dict, List, Tuple

import gspread
import pandas as pd
import requests
import streamlit as st
from google.oauth2.service_account import Credentials


PAGE_TITLE = "経費登録"
BASE_CURRENCY = "JPY"
VND_FIXED_RATE_TO_JPY = 0.006
PAYMENT_METHODS = ["現金", "クレジットカード", "電子決済", "WISE"]
FRANKFURTER_URL = "https://api.frankfurter.dev/v2/rates"


# =========================
# Google Sheets helpers
# =========================

def _get_spreadsheet_id() -> str:
    """st.secrets から spreadsheet_id を柔軟に取得する。"""
    candidate_paths = [
        ("sheets", "spreadsheet_id"),
        ("google_sheets", "spreadsheet_id"),
        ("google_sheet", "sheet_id"),
        ("google_sheet", "spreadsheet_id"),
    ]
    for section, key in candidate_paths:
        if section in st.secrets and key in st.secrets[section]:
            return st.secrets[section][key]
    raise KeyError(
        "spreadsheet_id が secrets.toml に見つかりません。"
        "[sheets] spreadsheet_id = \"...\" の形式で設定してください。"
    )


@st.cache_resource(show_spinner=False)
def get_gspread_client() -> gspread.Client:
    if "gcp_service_account" not in st.secrets:
        raise KeyError(
            "gcp_service_account が secrets.toml に見つかりません。"
            "サービスアカウント情報を設定してください。"
        )

    credentials_info = dict(st.secrets["gcp_service_account"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = Credentials.from_service_account_info(credentials_info, scopes=scopes)
    return gspread.authorize(credentials)


@st.cache_resource(show_spinner=False)
def get_workbook() -> gspread.Spreadsheet:
    client = get_gspread_client()
    spreadsheet_id = _get_spreadsheet_id()
    return client.open_by_key(spreadsheet_id)


@st.cache_data(ttl=120, show_spinner=False)
def read_sheet(sheet_name: str) -> pd.DataFrame:
    ws = get_workbook().worksheet(sheet_name)
    records = ws.get_all_records()
    return pd.DataFrame(records)


@st.cache_data(ttl=120, show_spinner=False)
def get_sheet_headers(sheet_name: str) -> List[str]:
    ws = get_workbook().worksheet(sheet_name)
    return ws.row_values(1)


# =========================
# Data preparation helpers
# =========================

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


@st.cache_data(ttl=120, show_spinner=False)
def load_master_data() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    expenses_df = normalize_columns(read_sheet("Expenses"))
    countries_df = normalize_columns(read_sheet("Countries"))
    usage_df = normalize_columns(read_sheet("Usage_categories"))
    tax_df = normalize_columns(read_sheet("Tax_categories"))
    return expenses_df, countries_df, usage_df, tax_df


def clean_flag_value(value: Any) -> int:
    try:
        if value == "":
            return 0
        return int(float(value))
    except Exception:
        return 0



def build_currency_options(countries_df: pd.DataFrame) -> List[str]:
    if countries_df.empty or "currency_code" not in countries_df.columns:
        return [BASE_CURRENCY]

    tmp = countries_df.copy()
    if "flag" in tmp.columns:
        tmp = tmp[tmp["flag"].apply(clean_flag_value) == 1]

    currencies = (
        tmp["currency_code"]
        .dropna()
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .drop_duplicates()
        .tolist()
    )

    if BASE_CURRENCY not in currencies:
        currencies.append(BASE_CURRENCY)

    return sorted(currencies)



def build_category_options(df: pd.DataFrame) -> Dict[str, Any]:
    """
    表示名 -> id の辞書を作る。
    name / name_ja / category_name / display_name を順に探す。
    """
    if df.empty:
        return {}

    id_col = "id" if "id" in df.columns else df.columns[0]
    name_candidates = ["name", "name_ja", "category_name", "display_name"]
    name_col = next((c for c in name_candidates if c in df.columns), None)
    if name_col is None:
        name_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]

    options: Dict[str, Any] = {}
    for _, row in df.iterrows():
        raw_name = row.get(name_col, "")
        raw_id = row.get(id_col, "")
        if pd.isna(raw_name) or str(raw_name).strip() == "":
            continue
        label = str(raw_name).strip()
        options[label] = raw_id
    return options


# =========================
# Exchange-rate helpers
# =========================

def get_exchange_rate(payment_date: date, currency_code: str, base_currency: str = BASE_CURRENCY) -> float:
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
# Expenses sheet append helper
# =========================

def _parse_existing_ids(expenses_df: pd.DataFrame) -> List[int]:
    if expenses_df.empty or "id" not in expenses_df.columns:
        return []

    ids: List[int] = []
    for value in expenses_df["id"].tolist():
        try:
            ids.append(int(float(value)))
        except Exception:
            continue
    return ids



def _build_expense_record(
    expenses_df: pd.DataFrame,
    payment_date_value: date,
    currency_code: str,
    amount: float,
    exchange_rate: float,
    amount_base: int,
    payment_method: str,
    description: str,
    usage_category_id: Any,
    tax_category_id: Any,
) -> Dict[str, Any]:
    now_str = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    existing_ids = _parse_existing_ids(expenses_df)
    new_id = (max(existing_ids) + 1) if existing_ids else 1

    return {
        "id": new_id,
        "payment_date": payment_date_value.strftime("%Y/%m/%d"),
        "currency_code": currency_code,
        "amount": amount,
        "exchange_rate": exchange_rate,
        "amount_base": amount_base,
        "payment_method": payment_method,
        "description": description,
        #"usage_categories_id": usage_category_id,
        #"tax_categories_id": tax_category_id,
        #"created_at": now_str,
        "updated_at": now_str,
        # 万一シート側が create_at なら値を入れられるよう保険で持つ
        #"create_at": now_str,
        #"update_at": now_str,
    }



def append_expense_record(record: Dict[str, Any]) -> None:
    ws = get_workbook().worksheet("Expenses")
    headers = get_sheet_headers("Expenses")
    row = [record.get(col, "") for col in headers]
    ws.append_row(row, value_input_option="USER_ENTERED")
    read_sheet.clear()
    get_sheet_headers.clear()
    load_master_data.clear()


# =========================
# UI
# =========================

def render_summary_preview(expenses_df: pd.DataFrame) -> None:
    st.subheader("直近の登録データ")
    if expenses_df.empty:
        st.info("まだ経費データがありません。")
        return

    preview_cols = [
        col for col in [
            "id",
            "payment_date",
            "currency_code",
            "amount",
            "exchange_rate",
            "amount_base",
            "payment_method",
            "description",
            #"usage_categories_id",
            #"tax_categories_id",
            "updated_at",
        ]
        if col in expenses_df.columns
    ]
    st.dataframe(expenses_df[preview_cols].tail(10), width='content')



def main() -> None:
    st.title(PAGE_TITLE)
    st.caption("旅行・滞在中の支出を登録します。VND は固定レート 0.006 JPY で換算します。")

    try:
        expenses_df, countries_df, usage_df, tax_df = load_master_data()
    except Exception as e:
        st.error(f"初期データの読み込みに失敗しました: {e}")
        st.stop()

    currency_options = build_currency_options(countries_df)
    usage_options = build_category_options(usage_df)
    tax_options = build_category_options(tax_df)

    if not usage_options:
        st.error("Usage_categories シートの読み込みに失敗したか、カテゴリが存在しません。")
        st.stop()
    if not tax_options:
        st.error("Tax_categories シートの読み込みに失敗したか、カテゴリが存在しません。")
        st.stop()

    with st.form("expense_register_form"):
        col1, col2 = st.columns(2)
        with col1:
            payment_date_value = st.date_input("決済日", value=date.today(), format="YYYY/MM/DD")
            currency_code = st.selectbox("通貨", currency_options, index=0)
            amount = st.number_input("金額", min_value=0.0, step=1.0, format="%.0f")
            payment_method = st.selectbox("決済方法", PAYMENT_METHODS, index=0)

        with col2:
            usage_label = st.selectbox("用途別カテゴリ", list(usage_options.keys()), index=0)
            tax_label = st.selectbox("税務別カテゴリ", list(tax_options.keys()), index=0)
            description = st.text_area("内容", placeholder="例: ランチ、ホテル代、Grab など")

        submitted = st.form_submit_button("登録", width='content')

    if submitted:
        if amount <= 0:
            st.error("金額は 0 より大きい値を入力してください。")
            st.stop()

        try:
            exchange_rate = get_exchange_rate(payment_date_value, currency_code, BASE_CURRENCY)
            amount_base = calculate_amount_base(amount, exchange_rate)

            st.info(
                f"換算結果: {amount:,.0f} {currency_code} × {exchange_rate:.6f} = {amount_base:,} {BASE_CURRENCY}"
            )

            record = _build_expense_record(
                expenses_df=expenses_df,
                payment_date_value=payment_date_value,
                currency_code=currency_code,
                amount=amount,
                exchange_rate=exchange_rate,
                amount_base=amount_base,
                payment_method=payment_method,
                description=description.strip(),
                usage_category_id=usage_options[usage_label],
                tax_category_id=tax_options[tax_label],
            )
            append_expense_record(record)
            st.success("経費を登録しました。")
            st.rerun()
        except Exception as e:
            st.error(f"登録に失敗しました: {e}")

    render_summary_preview(expenses_df)


if __name__ == "__main__":
    main()
