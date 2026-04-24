from pathlib import Path
import sys
import time
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from utils.db import (
    load_airports_by_city_id,
    load_city_detail_by_id,
    load_climate_by_city_ids,
    load_youtube_videos_by_city_id,
)

st.set_page_config(page_title="都市詳細", layout="wide")


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "" or pd.isna(value):
            return default
        return int(float(value))
    except Exception:
        return default


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "" or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _safe_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    s = str(value).strip()
    if s.lower() in {"nan", "none", ""}:
        return default
    return s


def _format_number(value: Any) -> str:
    try:
        if value is None or value == "" or pd.isna(value):
            return "-"
        return f"{int(float(value)):,}"
    except Exception:
        return str(value)


def _format_temp(value: Any) -> str:
    try:
        if value is None or value == "" or pd.isna(value):
            return "-"
        return f"{float(value):.1f}℃"
    except Exception:
        return str(value)


def _format_mm(value: Any) -> str:
    try:
        if value is None or value == "" or pd.isna(value):
            return "-"
        return f"{float(value):.1f} mm"
    except Exception:
        return str(value)


def _measure(debug_rows: list[dict[str, Any]], label: str, func):
    t0 = time.perf_counter()
    result = func()
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)
    debug_rows.append({"process": label, "ms": elapsed_ms})
    return result


def _build_monthly_climate_table(climate_df: pd.DataFrame) -> pd.DataFrame:
    if climate_df.empty:
        return pd.DataFrame(columns=["月", "最低気温", "平均気温", "最高気温", "降水量"])

    df = climate_df.copy()
    for col in ["month", "min_temp", "avg_temp", "max_temp", "precip_mm"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.sort_values("month", ascending=True).copy()

    return pd.DataFrame(
        {
            "月": df["month"].apply(lambda x: f"{_to_int(x)}月" if pd.notna(x) else "-"),
            "最低気温": df["min_temp"].apply(_format_temp),
            "平均気温": df["avg_temp"].apply(_format_temp),
            "最高気温": df["max_temp"].apply(_format_temp),
            "降水量": df["precip_mm"].apply(_format_mm),
        }
    )


def _format_airports_text(airports_df: pd.DataFrame) -> str:
    if airports_df.empty:
        return "-"

    lines: list[str] = []
    for _, row in airports_df.iterrows():
        airport_name = _safe_text(row.get("name_ja")) or _safe_text(row.get("name")) or "名称未設定"
        place_parts = [x for x in [_safe_text(row.get("city_ja")) or _safe_text(row.get("city")), _safe_text(row.get("country_ja"))] if x]
        codes = [x for x in [_safe_text(row.get("iata_code")), _safe_text(row.get("icao_code"))] if x]
        tz = _safe_text(row.get("timezone_name"))

        detail_parts = []
        if place_parts:
            detail_parts.append(" / ".join(place_parts))
        if codes:
            detail_parts.append("・".join(codes))
        if tz:
            detail_parts.append(f"TZ: {tz}")

        lines.append(f"- {airport_name}" + (f"（{' / '.join(detail_parts)}）" if detail_parts else ""))

    return "\n".join(lines) if lines else "-"


def _render_kv_box(label: str, value: str) -> None:
    st.markdown(
        f"""
        <div style="
            border:1px solid rgba(128,128,128,0.25);
            border-radius:12px;
            padding:14px 16px;
            margin-bottom:10px;
            min-height:88px;
        ">
            <div style="font-size:0.88rem;color:rgba(120,120,120,1);margin-bottom:8px;">{label}</div>
            <div style="font-size:1.02rem;font-weight:600;line-height:1.5;word-break:break-word;overflow-wrap:anywhere;">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_basic_info(detail: pd.Series, airport_text: str) -> None:
    country = _safe_text(detail.get("country"), "-")
    country_en = _safe_text(detail.get("country_en"), "")
    city_jp = _safe_text(detail.get("city_jp"), "-")
    city_en = _safe_text(detail.get("city_en"), "")
    population = _format_number(detail.get("population")) + "人" if _safe_text(detail.get("population")) else "-"
    elevation = f"{_format_number(detail.get('elevation'))}m" if _safe_text(detail.get("elevation")) else "-"
    cost_index = _format_number(detail.get("cost_index")) if _safe_text(detail.get("cost_index")) else "-"
    currency_code = _safe_text(detail.get("currency_code"), "-")
    religion = _safe_text(detail.get("religion"), "-")
    lat = _to_float(detail.get("lat"))
    lon = _to_float(detail.get("lon"))
    latlon = f"{lat:.4f}, {lon:.4f}" if lat is not None and lon is not None else "-"

    c1, c2, c3 = st.columns(3)
    with c1:
        _render_kv_box("都市名", f"{city_jp} / {city_en}" if city_en else city_jp)
        _render_kv_box("国名", f"{country} / {country_en}" if country_en else country)
        _render_kv_box("空港", airport_text)
    with c2:
        _render_kv_box("人口", population)
        _render_kv_box("標高", elevation)
        _render_kv_box("生活コスト指数", cost_index)
    with c3:
        _render_kv_box("通貨", currency_code)
        _render_kv_box("宗教", religion)
        _render_kv_box("緯度・経度", latlon)


def _render_map(detail: pd.Series) -> None:
    lat = _to_float(detail.get("lat"))
    lon = _to_float(detail.get("lon"))
    if lat is None or lon is None:
        st.info("位置情報がないため地図は表示できません。")
        return

    st.map(pd.DataFrame([{"lat": lat, "lon": lon}]), latitude="lat", longitude="lon", zoom=6)


def _render_youtube(videos_df: pd.DataFrame) -> None:
    if videos_df.empty:
        st.write("保存済み動画はありません。")
        return

    preferred_cols = ["title", "url", "channel_title", "published_at", "view_count", "like_count", "comment_count", "duration_sec"]
    existing_cols = [c for c in preferred_cols if c in videos_df.columns]
    view_df = videos_df[existing_cols].copy() if existing_cols else videos_df.copy()

    rename_map = {
        "title": "タイトル",
        "url": "URL",
        "channel_title": "チャンネル",
        "published_at": "公開日",
        "view_count": "再生数",
        "like_count": "高評価",
        "comment_count": "コメント",
        "duration_sec": "秒数",
    }
    view_df = view_df.rename(columns=rename_map)
    st.dataframe(view_df, width="stretch", hide_index=True)


st.title("都市詳細")

selected_city_id = st.session_state.get("selected_city_id")
if not selected_city_id:
    st.warning("都市が選択されていません。候補都市一覧から選択してください。")
    if st.button("候補都市一覧へ戻る"):
        st.switch_page("pages/city_recommend.py")
    st.stop()

debug_rows: list[dict[str, Any]] = []
page_t0 = time.perf_counter()

try:
    detail_df = _measure(debug_rows, "load_city_detail_by_id", lambda: load_city_detail_by_id(int(selected_city_id)))
    climate_df = _measure(debug_rows, "load_climate_by_city_ids", lambda: load_climate_by_city_ids((int(selected_city_id),)))
    airports_df = _measure(debug_rows, "load_airports_by_city_id", lambda: load_airports_by_city_id(int(selected_city_id)))
    youtube_df = _measure(debug_rows, "load_youtube_videos_by_city_id", lambda: load_youtube_videos_by_city_id(int(selected_city_id)))
except Exception as e:
    st.error(f"都市詳細の取得に失敗しました: {e}")
    if st.button("候補都市一覧へ戻る"):
        st.switch_page("pages/city_recommend.py")
    st.stop()

if detail_df.empty:
    st.warning("対象の都市が見つかりませんでした。")
    st.stop()

detail = detail_df.iloc[0]

monthly_climate_df = _measure(debug_rows, "build_monthly_climate_table", lambda: _build_monthly_climate_table(climate_df))
airport_text = _measure(debug_rows, "format_airports_text", lambda: _format_airports_text(airports_df))

city_jp = _safe_text(detail.get("city_jp"), "")
city_en = _safe_text(detail.get("city_en"), "")
country = _safe_text(detail.get("country"), "")
title_parts = [x for x in [city_jp or city_en, country] if x]
if title_parts:
    st.subheader(" / ".join(title_parts))

tab1, tab2, tab3, tab4 = st.tabs(["基本情報", "気候", "地図", "動画"])

with tab1:
    _measure(debug_rows, "render_basic_info", lambda: _render_basic_info(detail, airport_text))

with tab2:
    def _render_climate():
        if monthly_climate_df.empty:
            st.info("気候データがありません。")
        else:
            st.dataframe(monthly_climate_df, width="stretch", hide_index=True)
    _measure(debug_rows, "render_climate", _render_climate)

with tab3:
    _measure(debug_rows, "render_map", lambda: _render_map(detail))

with tab4:
    _measure(debug_rows, "render_videos", lambda: _render_youtube(youtube_df))

page_total_ms = round((time.perf_counter() - page_t0) * 1000, 3)
debug_rows.append({"process": "page_total", "ms": page_total_ms})

with st.expander("パフォーマンスデバッグ", expanded=True):
    st.json(
        {
            "city_id": int(selected_city_id),
            "detail_found": True,
            "climate_rows": int(len(climate_df)),
            "airport_rows": int(len(airports_df)),
            "youtube_rows_raw": int(len(youtube_df)),
            "youtube_rows_displayable": int(len(youtube_df)),
            "page_total_ms": page_total_ms,
        }
    )
    st.dataframe(pd.DataFrame(debug_rows), width="stretch", hide_index=True)
