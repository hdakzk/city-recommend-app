from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st

SHEET_ID = "1L4qsWHhucIORTjSC9MF5YtuOYk0NMQKFiI_Kzt1anWE"
PAYMENT_METHODS = ["現金", "クレジットカード", "電子決済", "WISE"]
FRANKFURTER_BASE_URL = "https://api.frankfurter.dev/v2"
JST = "Asia/Tokyo"


class SheetsWriteError(RuntimeError):
    pass


@dataclass
class AppData:
    countries: pd.DataFrame
    cities: pd.DataFrame
    climate: pd.DataFrame
    expenses: pd.DataFrame
    usage_categories: pd.DataFrame
    tax_categories: pd.DataFrame


def _normalize_text_columns(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    for col in columns:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
            df.loc[df[col].isin(["nan", "None"]), col] = ""
    return df


def _normalize_numeric_column(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_public_sheet(sheet_name: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    return pd.read_csv(url)


@st.cache_data(ttl=300)
def load_data() -> AppData:
    countries = load_public_sheet("Countries")
    cities = load_public_sheet("Cities")
    climate = load_public_sheet("Climate")
    expenses = load_public_sheet("Expenses")
    usage_categories = load_public_sheet("Usage_categories")
    tax_categories = load_public_sheet("Tax_categories")

    for df in [countries, cities, climate, expenses, usage_categories, tax_categories]:
        df.columns = df.columns.str.strip()

    countries = _normalize_text_columns(countries, ["country", "country_en", "area1", "area2", "currency_code"])
    cities = _normalize_text_columns(cities, ["city_jp", "city_en"])
    climate = _normalize_text_columns(climate, [])
    expenses = _normalize_text_columns(expenses, ["payment_date", "currency_code", "payment_method", "description", "created_at", "updated_at"])
    usage_categories = _normalize_text_columns(usage_categories, ["name_ja", "name_en"])
    tax_categories = _normalize_text_columns(tax_categories, ["name_ja", "name_en"])

    for col in ["country_id", "flag"]:
        countries = _normalize_numeric_column(countries, col)

    for col in ["country_id", "city_id"]:
        cities = _normalize_numeric_column(cities, col)

    for col in ["city_id", "month", "min_temp", "avg_temp", "max_temp", "humidity", "precip_mm", "rain_days"]:
        climate = _normalize_numeric_column(climate, col)

    for col in ["id", "amount", "exchange_rate", "amount_base", "usage_categories_id", "tax_categories_id"]:
        expenses = _normalize_numeric_column(expenses, col)

    for col in ["id", "sort_order", "is_enabled"]:
        usage_categories = _normalize_numeric_column(usage_categories, col)
        tax_categories = _normalize_numeric_column(tax_categories, col)

    return AppData(
        countries=countries,
        cities=cities,
        climate=climate,
        expenses=expenses,
        usage_categories=usage_categories,
        tax_categories=tax_categories,
    )


def categories_enabled(df: pd.DataFrame) -> pd.DataFrame:
    if "is_enabled" in df.columns:
        df = df[df["is_enabled"] == 1].copy()
    if "sort_order" in df.columns:
        df = df.sort_values(["sort_order", "id"], ascending=[True, True])
    return df


def get_enabled_currency_codes(countries: pd.DataFrame) -> List[str]:
    base = countries.copy()
    if "flag" in base.columns:
        base = base[base["flag"] == 1]
    if "currency_code" not in base.columns:
        return []
    values = base["currency_code"].dropna().astype(str).str.strip()
    return sorted([x for x in values.unique().tolist() if x])


@st.cache_data(ttl=43200, show_spinner=False)
def get_exchange_rate(payment_date: str, from_currency: str, to_currency: str = "JPY") -> float:
    from_currency = from_currency.upper().strip()
    to_currency = to_currency.upper().strip()
    if from_currency == to_currency:
        return 1.0

    response = requests.get(
        f"{FRANKFURTER_BASE_URL}/rates",
        params={"date": payment_date, "base": from_currency, "quotes": to_currency},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()

    if not payload:
        raise ValueError("為替データが取得できませんでした。")

    rate = payload[0].get("rate")
    if rate is None:
        raise ValueError("為替レートが見つかりませんでした。")
    return float(rate)


def format_date(dt_value: datetime) -> str:
    return dt_value.strftime("%Y/%m/%d")


def format_datetime(dt_value: datetime) -> str:
    return dt_value.strftime("%Y/%m/%d %H:%M:%S")


@st.cache_resource(show_spinner=False)
def get_gspread_client():
    import gspread
    from google.oauth2.service_account import Credentials

    service_account_info = None
    if "gcp_service_account" in st.secrets:
        service_account_info = dict(st.secrets["gcp_service_account"])
    elif "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
        service_account_info = dict(st.secrets["connections"]["gsheets"])

    if service_account_info is None:
        return None

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
    return gspread.authorize(credentials)



def append_expense_row(expense_row: Dict[str, Any], sheet_name: str = "Expenses") -> None:
    client = get_gspread_client()
    if client is None:
        raise SheetsWriteError(
            "Google Sheets の書き込み認証が未設定です。.streamlit/secrets.toml に service account を設定してください。"
        )

    spreadsheet = client.open_by_key(SHEET_ID)
    worksheet = spreadsheet.worksheet(sheet_name)

    headers = worksheet.row_values(1)
    if not headers:
        raise SheetsWriteError("Expenses シートのヘッダーが取得できませんでした。")

    ordered_values = [expense_row.get(header, "") for header in headers]
    worksheet.append_row(ordered_values, value_input_option="USER_ENTERED")
    load_data.clear()



def build_expense_row(
    expenses_df: pd.DataFrame,
    payment_date: datetime,
    currency_code: str,
    amount: float,
    exchange_rate: float,
    payment_method: str,
    description: str,
    usage_category_id: int,
    tax_category_id: int,
) -> Dict[str, Any]:
    now = pd.Timestamp.now(tz=JST).to_pydatetime()

    existing_ids = pd.to_numeric(expenses_df.get("id", pd.Series(dtype=float)), errors="coerce").dropna()
    next_id = int(existing_ids.max()) + 1 if not existing_ids.empty else 1
    amount_base = round(float(amount) * float(exchange_rate))

    return {
        "id": next_id,
        "payment_date": format_date(payment_date),
        "currency_code": currency_code,
        "amount": float(amount),
        "exchange_rate": float(exchange_rate),
        "amount_base": int(amount_base),
        "payment_method": payment_method,
        "description": description.strip(),
        "usage_categories_id": int(usage_category_id),
        "tax_categories_id": int(tax_category_id),
        "created_at": format_datetime(now),
        "updated_at": format_datetime(now),
    }



def enrich_expenses(expenses: pd.DataFrame, usage_categories: pd.DataFrame, tax_categories: pd.DataFrame) -> pd.DataFrame:
    df = expenses.copy()
    if df.empty:
        return df

    usage_map = categories_enabled(usage_categories)[["id", "name_ja", "name_en"]].rename(
        columns={"id": "usage_categories_id", "name_ja": "usage_category_name_ja", "name_en": "usage_category_name_en"}
    )
    tax_map = categories_enabled(tax_categories)[["id", "name_ja", "name_en"]].rename(
        columns={"id": "tax_categories_id", "name_ja": "tax_category_name_ja", "name_en": "tax_category_name_en"}
    )

    df = df.merge(usage_map, on="usage_categories_id", how="left")
    df = df.merge(tax_map, on="tax_categories_id", how="left")

    df["payment_date_dt"] = pd.to_datetime(df["payment_date"], format="%Y/%m/%d", errors="coerce")
    df["month"] = df["payment_date_dt"].dt.to_period("M").astype(str)
    df["day"] = df["payment_date_dt"].dt.strftime("%Y/%m/%d")
    df["amount_base"] = pd.to_numeric(df["amount_base"], errors="coerce").fillna(0)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    return df



def build_pivot_table(expenses: pd.DataFrame, category_basis: str, period_basis: str) -> pd.DataFrame:
    if expenses.empty:
        return pd.DataFrame()

    if category_basis == "用途別":
        category_col = "usage_category_name_ja"
    else:
        category_col = "tax_category_name_ja"

    index_col = "day" if period_basis == "日次" else "month"

    pivot = pd.pivot_table(
        expenses,
        index=index_col,
        columns=category_col,
        values="amount_base",
        aggfunc="sum",
        fill_value=0,
    )

    pivot["合計"] = pivot.sum(axis=1)
    ordered_cols = [col for col in pivot.columns if col != "合計"] + ["合計"]
    pivot = pivot[ordered_cols].sort_index()
    return pivot.reset_index().rename(columns={index_col: period_basis})
