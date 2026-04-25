from __future__ import annotations

import posixpath
import re
import zipfile
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any, Callable, Mapping, Sequence
from xml.etree import ElementTree as ET

import pandas as pd

WECHAT_SUCCESS_STATUS = "支付成功"
WECHAT_CURRENCY_CODE = "CNY"
WECHAT_FIXED_RATE_TO_JPY = 21.0
WECHAT_CARD_PAYMENT_METHOD = "クレジットカード"
WECHAT_REQUIRED_COLUMNS = [
    "交易时间",
    "交易类型",
    "交易对方",
    "商品",
    "金额(元)",
    "支付方式",
    "当前状态",
]

_XLSX_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _coerce_positive_int(value: Any, field_label: str) -> int:
    try:
        normalized_value = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_label} が不正です。") from exc

    if normalized_value <= 0:
        raise ValueError(f"{field_label} が不正です。")

    return normalized_value


def get_selected_expense_id(table_df: pd.DataFrame, selected_rows: Sequence[int]) -> int | None:
    if table_df.empty or "ID" not in table_df.columns or not selected_rows:
        return None

    selected_row_index = selected_rows[0]
    if selected_row_index < 0 or selected_row_index >= len(table_df):
        return None

    selected_id = table_df.iloc[selected_row_index].get("ID")
    if pd.isna(selected_id):
        return None

    try:
        return int(float(selected_id))
    except (TypeError, ValueError):
        return None


def get_selected_expense_ids(table_df: pd.DataFrame, selected_rows: Sequence[int]) -> list[int]:
    if table_df.empty or "ID" not in table_df.columns or not selected_rows:
        return []

    selected_ids: list[int] = []
    for selected_row_index in selected_rows:
        if selected_row_index < 0 or selected_row_index >= len(table_df):
            continue

        selected_id = table_df.iloc[selected_row_index].get("ID")
        if pd.isna(selected_id):
            continue

        try:
            normalized_id = int(float(selected_id))
        except (TypeError, ValueError):
            continue

        if normalized_id not in selected_ids:
            selected_ids.append(normalized_id)

    return selected_ids


def get_expense_row_by_id(expenses_df: pd.DataFrame, expense_id: Any) -> dict[str, Any] | None:
    if expenses_df.empty or "id" not in expenses_df.columns:
        return None

    try:
        normalized_expense_id = int(float(expense_id))
    except (TypeError, ValueError):
        return None

    matched_rows = expenses_df[pd.to_numeric(expenses_df["id"], errors="coerce") == normalized_expense_id]
    if matched_rows.empty:
        return None

    return matched_rows.iloc[0].to_dict()


def find_category_label_by_id(category_options: Mapping[str, Any], category_id: Any) -> str:
    try:
        normalized_category_id = int(float(category_id))
    except (TypeError, ValueError):
        return next(iter(category_options.keys()), "")

    for label, option_id in category_options.items():
        try:
            if int(float(option_id)) == normalized_category_id:
                return label
        except (TypeError, ValueError):
            continue

    return next(iter(category_options.keys()), "")


def build_expense_update_payload(
    *,
    expense_id: Any,
    payment_date_value: date,
    amount: float,
    exchange_rate: float,
    payment_method: str,
    description: str,
    usage_category_id: Any,
    tax_category_id: Any,
) -> tuple[int, dict[str, Any]]:
    normalized_expense_id = _coerce_positive_int(expense_id, "更新対象ID")

    if amount <= 0:
        raise ValueError("金額は 0 より大きい値を入力してください。")

    if exchange_rate <= 0:
        raise ValueError("為替レートは 0 より大きい値を入力してください。")

    normalized_usage_category_id = _coerce_positive_int(usage_category_id, "用途カテゴリ")
    normalized_tax_category_id = _coerce_positive_int(tax_category_id, "税務カテゴリ")

    return normalized_expense_id, {
        "payment_date": payment_date_value.strftime("%Y/%m/%d"),
        "amount": float(amount),
        "exchange_rate": float(exchange_rate),
        "amount_base": int(round(float(amount) * float(exchange_rate))),
        "payment_method": str(payment_method).strip(),
        "description": str(description).strip(),
        "usage_categories_id": normalized_usage_category_id,
        "tax_categories_id": normalized_tax_category_id,
    }


def build_bulk_expense_update_plan(
    original_expenses_df: pd.DataFrame,
    edited_expenses_df: pd.DataFrame,
    usage_options: Mapping[str, Any],
    tax_options: Mapping[str, Any],
) -> tuple[list[tuple[int, dict[str, Any]]], pd.DataFrame]:
    if original_expenses_df.empty:
        raise ValueError("更新対象の経費データを1件以上選択してください。")

    if edited_expenses_df.empty:
        raise ValueError("編集対象の経費データがありません。")

    original_rows: dict[int, dict[str, Any]] = {}
    for _, row in original_expenses_df.iterrows():
        expense_id = _coerce_positive_int(row.get("id"), "更新対象ID")
        original_rows[expense_id] = row.to_dict()

    usage_labels = set(usage_options.keys())
    tax_labels = set(tax_options.keys())

    update_plan: list[tuple[int, dict[str, Any]]] = []
    preview_rows: list[dict[str, Any]] = []

    for _, edited_row in edited_expenses_df.iterrows():
        normalized_expense_id = _coerce_positive_int(edited_row.get("ID"), "更新対象ID")
        original_row = original_rows.get(normalized_expense_id)
        if original_row is None:
            raise ValueError(f"ID {normalized_expense_id} の元データが見つかりません。")

        payload: dict[str, Any] = {}
        preview_row: dict[str, Any] = {"ID": normalized_expense_id}

        original_payment_date = pd.to_datetime(original_row.get("payment_date"), errors="coerce")
        edited_payment_date = pd.to_datetime(edited_row.get("支払日"), errors="coerce")
        if pd.isna(edited_payment_date):
            raise ValueError(f"ID {normalized_expense_id} の支払日が不正です。")
        if pd.isna(original_payment_date) or edited_payment_date.date() != original_payment_date.date():
            payload["payment_date"] = edited_payment_date.strftime("%Y/%m/%d")
            preview_row["支払日(変更前)"] = (
                original_payment_date.strftime("%Y-%m-%d") if not pd.isna(original_payment_date) else ""
            )
            preview_row["支払日(変更後)"] = edited_payment_date.strftime("%Y-%m-%d")

        edited_payment_method = str(edited_row.get("決済方法") or "").strip()
        original_payment_method = str(original_row.get("payment_method") or "").strip()
        if edited_payment_method != original_payment_method:
            payload["payment_method"] = edited_payment_method
            preview_row["決済方法(変更前)"] = original_payment_method
            preview_row["決済方法(変更後)"] = edited_payment_method

        edited_description = str(edited_row.get("内容") or "").strip()
        original_description = str(original_row.get("description") or "").strip()
        if edited_description != original_description:
            payload["description"] = edited_description
            preview_row["内容(変更前)"] = original_description
            preview_row["内容(変更後)"] = edited_description

        edited_usage_label = str(edited_row.get("用途カテゴリ") or "").strip()
        if edited_usage_label not in usage_labels:
            raise ValueError(f"ID {normalized_expense_id} の用途カテゴリが不正です。")
        edited_usage_id = _coerce_positive_int(usage_options[edited_usage_label], "用途カテゴリ")
        original_usage_id = _to_positive_int_or_none(original_row.get("usage_categories_id"))
        if edited_usage_id != original_usage_id:
            payload["usage_categories_id"] = edited_usage_id
            preview_row["用途カテゴリ(変更前)"] = find_category_label_by_id(
                usage_options,
                original_row.get("usage_categories_id"),
            )
            preview_row["用途カテゴリ(変更後)"] = edited_usage_label

        edited_tax_label = str(edited_row.get("税務カテゴリ") or "").strip()
        if edited_tax_label not in tax_labels:
            raise ValueError(f"ID {normalized_expense_id} の税務カテゴリが不正です。")
        edited_tax_id = _coerce_positive_int(tax_options[edited_tax_label], "税務カテゴリ")
        original_tax_id = _to_positive_int_or_none(original_row.get("tax_categories_id"))
        if edited_tax_id != original_tax_id:
            payload["tax_categories_id"] = edited_tax_id
            preview_row["税務カテゴリ(変更前)"] = find_category_label_by_id(
                tax_options,
                original_row.get("tax_categories_id"),
            )
            preview_row["税務カテゴリ(変更後)"] = edited_tax_label

        edited_amount = pd.to_numeric(edited_row.get("金額"), errors="coerce")
        if pd.isna(edited_amount) or float(edited_amount) <= 0:
            raise ValueError(f"ID {normalized_expense_id} の金額は 0 より大きい値を入力してください。")
        original_amount = pd.to_numeric(original_row.get("amount"), errors="coerce")
        if pd.isna(original_amount) or float(edited_amount) != float(original_amount):
            exchange_rate_value = pd.to_numeric(original_row.get("exchange_rate"), errors="coerce")
            if pd.isna(exchange_rate_value) or float(exchange_rate_value) <= 0:
                raise ValueError(
                    f"ID {normalized_expense_id} の為替レートが不正なため、金額を一括変更できません。"
                )

            original_amount_base = pd.to_numeric(original_row.get("amount_base"), errors="coerce")
            amount_base = int(round(float(edited_amount) * float(exchange_rate_value)))

            preview_row["金額(変更前)"] = float(original_amount) if not pd.isna(original_amount) else None
            preview_row["金額(変更後)"] = float(edited_amount)
            preview_row["円換算額(変更前)"] = (
                int(round(float(original_amount_base))) if not pd.isna(original_amount_base) else None
            )
            preview_row["円換算額(変更後)"] = amount_base

            payload["amount"] = float(edited_amount)
            payload["amount_base"] = amount_base

        if payload:
            update_plan.append((normalized_expense_id, payload))
            preview_rows.append(preview_row)

    if not update_plan:
        raise ValueError("変更内容がありません。")

    return update_plan, pd.DataFrame(preview_rows)


def build_bulk_expense_edit_frame(
    selected_expenses_df: pd.DataFrame,
    usage_options: Mapping[str, Any],
    tax_options: Mapping[str, Any],
) -> pd.DataFrame:
    if selected_expenses_df.empty:
        return pd.DataFrame(columns=["ID", "支払日", "決済方法", "用途カテゴリ", "税務カテゴリ", "内容", "金額"])

    editable_rows: list[dict[str, Any]] = []
    for _, row in selected_expenses_df.iterrows():
        expense_id = _coerce_positive_int(row.get("id"), "更新対象ID")
        payment_date_value = pd.to_datetime(row.get("payment_date"), errors="coerce")
        editable_rows.append(
            {
                "ID": expense_id,
                "支払日": payment_date_value.date() if not pd.isna(payment_date_value) else None,
                "決済方法": str(row.get("payment_method") or "").strip(),
                "用途カテゴリ": find_category_label_by_id(usage_options, row.get("usage_categories_id")),
                "税務カテゴリ": find_category_label_by_id(tax_options, row.get("tax_categories_id")),
                "内容": str(row.get("description") or "").strip(),
                "金額": pd.to_numeric(row.get("amount"), errors="coerce"),
            }
        )

    return pd.DataFrame(editable_rows)


def _column_letters_to_index(cell_ref: str) -> int:
    match = re.match(r"^([A-Z]+)", str(cell_ref).upper())
    if not match:
        raise ValueError(f"セル参照が不正です: {cell_ref}")

    col_index = 0
    for char in match.group(1):
        col_index = col_index * 26 + ord(char) - ord("A") + 1
    return col_index - 1


def _read_xlsx_shared_strings(zip_file: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zip_file.namelist():
        return []

    root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
    shared_strings: list[str] = []
    for item in root.findall("main:si", _XLSX_NS):
        shared_strings.append(
            "".join(text_node.text or "" for text_node in item.findall(".//main:t", _XLSX_NS))
        )
    return shared_strings


def _resolve_first_sheet_path(zip_file: zipfile.ZipFile) -> str:
    workbook_root = ET.fromstring(zip_file.read("xl/workbook.xml"))
    first_sheet = workbook_root.find("main:sheets/main:sheet", _XLSX_NS)
    if first_sheet is None:
        raise ValueError("Excelファイルにシートが見つかりません。")

    relation_id = first_sheet.attrib.get(f"{{{_XLSX_NS['rel']}}}id")
    if not relation_id:
        raise ValueError("Excelシート参照の読み取りに失敗しました。")

    rels_root = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
    for relation in rels_root.findall("pkg:Relationship", _XLSX_NS):
        if relation.attrib.get("Id") == relation_id:
            target_path = relation.attrib.get("Target", "")
            if not target_path:
                break
            return posixpath.normpath(posixpath.join("xl", target_path))

    raise ValueError("Excelシート実体の読み取りに失敗しました。")


def _read_xlsx_first_sheet_rows(file_content: bytes) -> list[list[str]]:
    try:
        zip_file = zipfile.ZipFile(BytesIO(file_content))
    except zipfile.BadZipFile as exc:
        raise ValueError("WechatのExcelファイル形式が不正です。") from exc

    with zip_file:
        shared_strings = _read_xlsx_shared_strings(zip_file)
        sheet_path = _resolve_first_sheet_path(zip_file)
        sheet_root = ET.fromstring(zip_file.read(sheet_path))

        rows: list[list[str]] = []
        for row in sheet_root.findall("main:sheetData/main:row", _XLSX_NS):
            values_by_col: dict[int, str] = {}
            for cell in row.findall("main:c", _XLSX_NS):
                cell_ref = cell.attrib.get("r", "")
                col_index = _column_letters_to_index(cell_ref)
                cell_type = cell.attrib.get("t")

                if cell_type == "inlineStr":
                    cell_value = "".join(
                        text_node.text or ""
                        for text_node in cell.findall("main:is/main:t", _XLSX_NS)
                    )
                else:
                    raw_value = (cell.findtext("main:v", default="", namespaces=_XLSX_NS) or "").strip()
                    if cell_type == "s" and raw_value:
                        try:
                            cell_value = shared_strings[int(raw_value)]
                        except (IndexError, ValueError) as exc:
                            raise ValueError("Excel共有文字列の読み取りに失敗しました。") from exc
                    else:
                        cell_value = raw_value

                values_by_col[col_index] = cell_value

            if not values_by_col:
                rows.append([])
                continue

            rows.append(
                [values_by_col.get(col_index, "") for col_index in range(max(values_by_col) + 1)]
            )

        return rows


def _normalize_wechat_text(value: Any) -> str:
    normalized = str(value or "").strip()
    return "" if normalized in {"", "/"} else normalized


def _normalize_wechat_payment_method(value: Any) -> str:
    normalized = _normalize_wechat_text(value)
    if "MASTERCARD" in normalized.upper():
        return WECHAT_CARD_PAYMENT_METHOD
    return normalized


def _parse_wechat_payment_date(raw_value: Any) -> date:
    normalized = str(raw_value or "").strip()
    if not normalized:
        raise ValueError("交易时间 が空です。")

    if re.fullmatch(r"\d+(?:\.\d+)?", normalized):
        return (datetime(1899, 12, 30) + timedelta(days=float(normalized))).date()

    parsed_value = pd.to_datetime(normalized, errors="coerce")
    if pd.isna(parsed_value):
        raise ValueError(f"交易时间 の形式が不正です: {raw_value}")

    return parsed_value.date()


def _parse_wechat_amount(raw_value: Any) -> float:
    normalized = str(raw_value or "").strip().replace(",", "").replace("¥", "").replace("￥", "")
    try:
        amount = float(normalized)
    except ValueError as exc:
        raise ValueError(f"金额(元) の形式が不正です: {raw_value}") from exc

    if amount <= 0:
        raise ValueError(f"金额(元) は 0 より大きい値が必要です: {raw_value}")

    return amount


def _build_wechat_description(row: Mapping[str, Any]) -> str:
    description_parts = [
        _normalize_wechat_text(row.get("交易对方")),
        _normalize_wechat_text(row.get("商品")),
        _normalize_wechat_text(row.get("交易类型")),
    ]
    return "/".join(part for part in description_parts if part)


def _normalize_description_for_category_match(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    normalized = re.sub(r"\d{4}[-/_年]\d{1,2}[-/_月]\d{1,2}(?:\s*\d{1,2}:\d{2}:\d{2})?", "", normalized)
    normalized = re.sub(r"\d{1,2}:\d{2}:\d{2}", "", normalized)
    normalized = re.sub(r"\d+", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"[\W_]+", "", normalized)
    return normalized


def _to_positive_int_or_none(value: Any) -> int | None:
    try:
        normalized_value = int(float(value))
    except (TypeError, ValueError):
        return None
    return normalized_value if normalized_value > 0 else None


def build_description_category_lookup(
    existing_expenses_df: pd.DataFrame,
) -> dict[str, tuple[int | None, int | None]]:
    if existing_expenses_df.empty or "description" not in existing_expenses_df.columns:
        return {}

    lookup: dict[str, tuple[int | None, int | None]] = {}
    for _, row in existing_expenses_df.iterrows():
        lookup_key = _normalize_description_for_category_match(row.get("description"))
        if not lookup_key or lookup_key in lookup:
            continue

        usage_category_id = _to_positive_int_or_none(row.get("usage_categories_id"))
        tax_category_id = _to_positive_int_or_none(row.get("tax_categories_id"))
        if usage_category_id is None and tax_category_id is None:
            continue

        lookup[lookup_key] = (usage_category_id, tax_category_id)

    return lookup


def _build_default_exchange_rate(_: date) -> float:
    return WECHAT_FIXED_RATE_TO_JPY


def build_wechat_expense_records(
    file_content: bytes,
    auth_user_id: str,
    existing_expenses_df: pd.DataFrame | None = None,
    exchange_rate_provider: Callable[[date], float] | None = None,
) -> list[dict[str, Any]]:
    rows = _read_xlsx_first_sheet_rows(file_content)

    header_index = next(
        (
            row_index
            for row_index, row_values in enumerate(rows)
            if any(str(value).strip() == "交易时间" for value in row_values)
        ),
        None,
    )
    if header_index is None:
        raise ValueError("Wechat明細のヘッダー行が見つかりません。")

    headers = [str(value).strip() for value in rows[header_index]]
    missing_columns = [col for col in WECHAT_REQUIRED_COLUMNS if col not in headers]
    if missing_columns:
        raise ValueError(f"Wechat明細に必要な列がありません: {', '.join(missing_columns)}")

    rate_provider = exchange_rate_provider or _build_default_exchange_rate
    category_source_df = existing_expenses_df if existing_expenses_df is not None else pd.DataFrame()
    category_lookup = build_description_category_lookup(category_source_df)
    expense_records: list[dict[str, Any]] = []

    for row_values in rows[header_index + 1 :]:
        if not any(str(value).strip() for value in row_values):
            continue

        row_data = {
            headers[col_index]: row_values[col_index] if col_index < len(row_values) else ""
            for col_index in range(len(headers))
        }

        if str(row_data.get("当前状态", "")).strip() != WECHAT_SUCCESS_STATUS:
            continue

        payment_date_value = _parse_wechat_payment_date(row_data.get("交易时间"))
        amount = _parse_wechat_amount(row_data.get("金额(元)"))
        exchange_rate = float(rate_provider(payment_date_value))
        if exchange_rate <= 0:
            raise ValueError("Wechat取込の為替レートは 0 より大きい値が必要です。")

        payment_method = _normalize_wechat_payment_method(row_data.get("支付方式"))
        description = _build_wechat_description(row_data)
        usage_category_id, tax_category_id = category_lookup.get(
            _normalize_description_for_category_match(description),
            (None, None),
        )

        expense_records.append(
            {
                "payment_date": payment_date_value.strftime("%Y/%m/%d"),
                "currency_code": WECHAT_CURRENCY_CODE,
                "amount": amount,
                "exchange_rate": exchange_rate,
                "amount_base": int(round(amount * exchange_rate)),
                "payment_method": payment_method,
                "description": description,
                "usage_categories_id": usage_category_id,
                "tax_categories_id": tax_category_id,
                "auth_user_id": auth_user_id,
            }
        )

    return expense_records
