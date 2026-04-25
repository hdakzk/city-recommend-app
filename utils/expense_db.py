from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple
from uuid import uuid4

import pandas as pd
import streamlit as st

from utils.supabase_client import get_supabase_client

EXPENSE_RECEIPT_BUCKET = "expense-receipts"


def _to_df(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df.columns = df.columns.str.strip()
    return df


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _fetch_all_rows(
    table_name: str,
    page_size: int = 1000,
    user_id: str | None = None,
) -> pd.DataFrame:
    client = get_supabase_client(use_session=True)
    all_rows: List[Dict[str, Any]] = []
    start = 0

    while True:
        end = start + page_size - 1

        query = client.table(table_name).select("*")

        if table_name in {"expenses", "monthly_budgets"} and user_id:
            # RLS が本命だが、明示フィルタも追加して安全側に寄せる
            query = query.eq("auth_user_id", user_id)

        response = query.range(start, end).execute()
        rows = response.data or []

        if not rows:
            break

        all_rows.extend(rows)

        if len(rows) < page_size:
            break

        start += page_size

    return _to_df(all_rows)


@st.cache_data(ttl=300, show_spinner=False)
def load_category_master_data() -> Tuple[pd.DataFrame, pd.DataFrame]:
    usage_df = _normalize_columns(_fetch_all_rows("usage_categories"))
    tax_df = _normalize_columns(_fetch_all_rows("tax_categories"))
    return usage_df, tax_df


@st.cache_data(ttl=120, show_spinner=False)
def load_expense_master_data(user_id: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    expenses_df = _normalize_columns(_fetch_all_rows("expenses", user_id=user_id))
    usage_df, tax_df = load_category_master_data()
    return expenses_df, usage_df.copy(), tax_df.copy()


@st.cache_data(ttl=60, show_spinner=False)
def load_expense_manage_data(user_id: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    expenses_df = _normalize_columns(_fetch_all_rows("expenses", user_id=user_id))
    usage_df, tax_df = load_category_master_data()
    return expenses_df, usage_df.copy(), tax_df.copy()


def build_category_options(df: pd.DataFrame) -> Dict[str, Any]:
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

        try:
            normalized_id = int(float(raw_id))
        except Exception:
            normalized_id = raw_id

        options[str(raw_name).strip()] = normalized_id

    return options


def build_expense_record(
    payment_date_value: date,
    currency_code: str,
    amount: float,
    exchange_rate: float,
    amount_base: int,
    payment_method: str,
    description: str,
    usage_category_id: Any,
    tax_category_id: Any,
    auth_user_id: str,
    receipt_storage_path: str | None = None,
) -> Dict[str, Any]:
    record = {
        "payment_date": payment_date_value.isoformat(),
        "currency_code": currency_code,
        "amount": amount,
        "exchange_rate": exchange_rate,
        "amount_base": amount_base,
        "payment_method": payment_method,
        "description": description,
        "usage_categories_id": usage_category_id,
        "tax_categories_id": tax_category_id,
        "auth_user_id": auth_user_id,
    }

    if receipt_storage_path:
        record["receipt_storage_path"] = receipt_storage_path

    return record


def build_receipt_storage_path(
    *,
    auth_user_id: str,
    payment_date_value: date,
    original_file_name: str,
    unique_token: str | None = None,
) -> str:
    normalized_user_id = str(auth_user_id or "").strip()
    if not normalized_user_id:
        raise ValueError("ユーザーIDが不正です。")

    suffix = Path(str(original_file_name or "").strip()).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png"}:
        suffix = ".jpg"

    token = str(unique_token or uuid4().hex).strip()
    if not token:
        raise ValueError("レシート画像の保存トークンが不正です。")

    return (
        f"{normalized_user_id}/"
        f"{payment_date_value.strftime('%Y/%m')}/"
        f"{payment_date_value.strftime('%Y%m%d')}_{token}{suffix}"
    )


def upload_expense_receipt(
    *,
    file_content: bytes,
    original_file_name: str,
    content_type: str,
    payment_date_value: date,
    auth_user_id: str,
) -> str:
    if not file_content:
        raise ValueError("レシート画像が空です。")

    storage_path = build_receipt_storage_path(
        auth_user_id=auth_user_id,
        payment_date_value=payment_date_value,
        original_file_name=original_file_name,
    )

    normalized_content_type = str(content_type or "").strip() or "image/jpeg"

    client = get_supabase_client(use_session=True)
    client.storage.from_(EXPENSE_RECEIPT_BUCKET).upload(
        storage_path,
        file_content,
        {"content-type": normalized_content_type},
    )
    return storage_path


def insert_expense_record(record: Dict[str, Any]) -> None:
    client = get_supabase_client(use_session=True)
    client.table("expenses").insert(record).execute()
    st.cache_data.clear()


def insert_expense_records(records: List[Dict[str, Any]]) -> None:
    if not records:
        return

    client = get_supabase_client(use_session=True)
    client.table("expenses").insert(records).execute()
    st.cache_data.clear()


def update_expense_record(expense_id: int, user_id: str, payload: Dict[str, Any]) -> None:
    client = get_supabase_client(use_session=True)
    client.table("expenses").update(payload).eq("id", expense_id).eq("auth_user_id", user_id).execute()
    st.cache_data.clear()
