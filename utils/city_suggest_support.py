from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any


REQUIRED_SEARCH_STATE_KEYS = (
    "selected_country_id",
    "selected_country_name",
    "selected_city_id",
    "selected_month",
    "min_temp",
    "max_temp",
    "elevation_range",
    "max_distance_km",
    "city_count",
)

DEBUG_TRUE_VALUES = {"1", "true", "yes", "on"}


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none"}:
        return ""
    return text


def is_debug_mode_enabled(query_params: Mapping[str, Any] | None) -> bool:
    if not query_params:
        return False

    raw_value = query_params.get("debug_city_suggest", "0")
    if isinstance(raw_value, list):
        raw_value = raw_value[0] if raw_value else "0"

    return str(raw_value).strip().lower() in DEBUG_TRUE_VALUES


def get_missing_search_state_keys(search_state: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(search_state, Mapping):
        return list(REQUIRED_SEARCH_STATE_KEYS)

    return [key for key in REQUIRED_SEARCH_STATE_KEYS if key not in search_state]


def build_selection_debug_snapshot(
    *,
    selected_country_name: str,
    selected_country_id: int | None,
    country_option_records: Sequence[Mapping[str, Any]],
    city_option_records: Sequence[Mapping[str, Any]],
    selected_city_id: int | None,
    selected_city_label: str | None,
) -> dict[str, Any]:
    return {
        "selected_country_name": _safe_text(selected_country_name),
        "selected_country_id": selected_country_id,
        "country_options_rows": len(country_option_records),
        "city_options_rows": len(city_option_records),
        "selected_city_id": selected_city_id,
        "selected_city_label": _safe_text(selected_city_label),
    }


def build_country_option_records(country_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in country_rows:
        country_id = row.get("country_id")
        if country_id is None:
            continue

        try:
            normalized_country_id = int(country_id)
        except (TypeError, ValueError):
            continue

        normalized_rows.append(
            {
                "country_id": normalized_country_id,
                "country": _safe_text(row.get("country")),
            }
        )

    name_counts = Counter(row["country"] for row in normalized_rows)

    return [
        {
            "country_id": row["country_id"],
            "label": (
                f"{row['country']}｜ID:{row['country_id']}"
                if name_counts[row["country"]] > 1
                else row["country"]
            ),
        }
        for row in normalized_rows
    ]


def build_selection_warning(snapshot: Mapping[str, Any]) -> str | None:
    selected_country_id = snapshot.get("selected_country_id")
    selected_city_id = snapshot.get("selected_city_id")
    selected_city_label = _safe_text(snapshot.get("selected_city_label"))
    city_options_rows = int(snapshot.get("city_options_rows", 0) or 0)

    if selected_country_id is not None and city_options_rows == 0:
        return "選択中の国に対して都市候補がありません。都市マスタ欠損または抽出条件を確認してください。"

    if selected_city_label and selected_city_id is None:
        return "表示中の都市ラベルと内部 city_id の対応が取れていません。選択状態を再確認してください。"

    return None
