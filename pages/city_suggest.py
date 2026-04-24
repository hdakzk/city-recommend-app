from pathlib import Path
import sys
import math
import time
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import folium
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from utils.city_suggest_support import (
    build_country_option_records,
    build_selection_debug_snapshot,
    build_selection_warning,
    get_missing_search_state_keys,
    is_debug_mode_enabled,
)
from utils.db import (
    load_cities_by_country_ids,
    load_climate_by_city_ids_and_month,
    load_countries,
    prepare_cities_for_selection,
)

st.set_page_config(page_title="近隣都市レコメンド", layout="wide")
st.title("近隣都市レコメンド")

DEBUG_MODE = is_debug_mode_enabled(st.query_params)


def measure(debug_rows: list[dict[str, Any]], label: str, func):
    t0 = time.perf_counter()
    result = func()
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)
    debug_rows.append({"process": label, "ms": elapsed_ms})
    return result


def safe_text(v) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    s = str(v).strip()
    return "" if s.lower() in {"nan", "none"} else s


def clean_options(series: pd.Series) -> list[str]:
    return sorted(
        [
            x
            for x in series.dropna().astype(str).str.strip().unique().tolist()
            if x and x.lower() != "nan"
        ]
    )


def ensure_required_columns(df: pd.DataFrame, required_cols: set[str], table_name: str) -> None:
    missing = required_cols - set(df.columns)
    if missing:
        st.error(f"{table_name} に必要な列がありません: {sorted(missing)}")
        st.stop()


@st.cache_data(ttl=1800, show_spinner=False)
def load_country_master() -> pd.DataFrame:
    countries = load_countries().copy()
    if countries.empty:
        return countries

    ensure_required_columns(countries, {"country_id", "country", "area1", "area2", "flag"}, "countries")

    countries = countries[countries["flag"] == 1].copy()
    if countries.empty:
        return countries

    countries["country_id"] = pd.to_numeric(countries["country_id"], errors="coerce")
    countries = countries.dropna(subset=["country_id", "country"]).copy()
    countries["country_id"] = countries["country_id"].astype(int)
    countries["country"] = countries["country"].astype(str).str.strip()

    countries = countries.sort_values(by=["country", "country_id"], ascending=[True, True]).copy()
    return countries


@st.cache_data(ttl=1800, show_spinner=False)
def load_city_master_by_country_id(country_id: int, country_name: str) -> pd.DataFrame:
    city_master = prepare_cities_for_selection(load_cities_by_country_ids((int(country_id),)).copy())
    if city_master.empty:
        return pd.DataFrame()

    city_master["city_jp"] = city_master["city_jp"].apply(safe_text)
    city_master["city_en"] = city_master["city_en"].apply(safe_text)
    city_master["country"] = safe_text(country_name)

    city_master = city_master.sort_values(
        by=["city_jp", "city_en", "city_id"],
        ascending=[True, True, True],
    ).copy()

    city_master["city_search_label"] = city_master.apply(
        lambda row: (
            f"{safe_text(row.get('city_jp'))} / {safe_text(row.get('city_en'))} "
            f"｜{country_name}｜ID:{int(row.get('city_id'))}"
        ),
        axis=1,
    )

    return city_master


def get_area2_values(countries_df: pd.DataFrame, selected_area1: list[str]) -> list[str]:
    df = countries_df.copy()
    if selected_area1:
        df = df[df["area1"].isin(selected_area1)]
    return clean_options(df["area2"])


def get_country_df(
    countries_df: pd.DataFrame,
    selected_area1: list[str],
    selected_area2: list[str],
) -> pd.DataFrame:
    df = countries_df.copy()
    if selected_area1:
        df = df[df["area1"].isin(selected_area1)]
    if selected_area2:
        df = df[df["area2"].isin(selected_area2)]
    df = df.sort_values(by=["country", "country_id"], ascending=[True, True]).copy()
    return df[["country_id", "country"]].drop_duplicates(subset=["country_id"]).copy()


def sync_multiselect_values(selected_values: list[str], valid_values: list[str]) -> list[str]:
    valid_selected = [x for x in selected_values if x in valid_values]
    if valid_selected:
        return valid_selected
    return valid_values.copy()


def sync_single_select_value(selected_value: int | None, valid_values: list[int]) -> int | None:
    if selected_value in valid_values:
        return selected_value
    return None


def build_city_option_records(city_master: pd.DataFrame) -> list[dict[str, Any]]:
    if city_master.empty:
        return []

    work = city_master[["city_id", "city_search_label"]].drop_duplicates(subset=["city_id"]).copy()
    work["city_id"] = pd.to_numeric(work["city_id"], errors="coerce")
    work = work.dropna(subset=["city_id"]).copy()
    work["city_id"] = work["city_id"].astype(int)

    return [
        {"city_id": int(row["city_id"]), "label": safe_text(row["city_search_label"])}
        for _, row in work.iterrows()
    ]


def get_city_label_map(city_option_records: list[dict[str, Any]]) -> dict[int, str]:
    return {int(x["city_id"]): safe_text(x["label"]) for x in city_option_records}


def haversine_km(lat1: float, lon1: float, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    r = 6371.0088

    lat1_rad = np.radians(lat1)
    lon1_rad = np.radians(lon1)
    lat2_rad = np.radians(lat2)
    lon2_rad = np.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2.0) ** 2
    c = 2 * np.arcsin(np.sqrt(a))
    return r * c


def calc_bbox(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    lat_delta = radius_km / 111.32

    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-6:
        lon_delta = 180.0
    else:
        lon_delta = radius_km / (111.32 * cos_lat)

    return (
        lat - lat_delta,
        lat + lat_delta,
        lon - lon_delta,
        lon + lon_delta,
    )


def build_result_map(reference_row: pd.Series, result_df: pd.DataFrame):
    ref_lat = float(reference_row["lat"])
    ref_lon = float(reference_row["lon"])

    fmap = folium.Map(
        location=[ref_lat, ref_lon],
        zoom_start=7,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    reference_city_jp = safe_text(reference_row.get("city_jp"))
    reference_city_en = safe_text(reference_row.get("city_en"))

    reference_popup = f"""
    <b>{reference_city_jp} / {reference_city_en}</b><br>
    {safe_text(reference_row.get('country'))}<br>
    基準都市
    """

    folium.Marker(
        location=[ref_lat, ref_lon],
        tooltip=reference_city_jp or reference_city_en or str(int(reference_row["city_id"])),
        popup=folium.Popup(reference_popup, max_width=280),
        icon=folium.Icon(color="red", icon="home"),
    ).add_to(fmap)

    bounds = [[ref_lat, ref_lon]]

    for _, row in result_df.iterrows():
        lat = float(row["lat"])
        lon = float(row["lon"])
        bounds.append([lat, lon])

        city_jp = safe_text(row.get("city_jp"))
        city_en = safe_text(row.get("city_en"))

        popup_html = f"""
        <b>{city_jp} / {city_en}</b><br>
        {safe_text(row.get('country'))}<br>
        距離: {float(row.get('distance_km', 0)):.1f} km<br>
        最低/平均/最高: {row.get('min_temp', '-')}/{row.get('avg_temp', '-')}/{row.get('max_temp', '-')} ℃
        """

        folium.Marker(
            location=[lat, lon],
            tooltip=city_jp or city_en or str(int(row["city_id"])),
            popup=folium.Popup(popup_html, max_width=320),
            icon=folium.Icon(color="blue"),
        ).add_to(fmap)

    if len(bounds) >= 2:
        fmap.fit_bounds(bounds, padding=(30, 30))

    return fmap


def resolve_clicked_city_id(clicked_point: dict, reference_city: pd.Series, merged: pd.DataFrame) -> int | None:
    if not isinstance(clicked_point, dict):
        return None

    clicked_lat = clicked_point.get("lat")
    clicked_lng = clicked_point.get("lng")

    if clicked_lat is None or clicked_lng is None:
        return None

    clicked_lat = float(clicked_lat)
    clicked_lng = float(clicked_lng)

    all_points = pd.concat(
        [
            pd.DataFrame(
                [
                    {
                        "city_id": int(reference_city["city_id"]),
                        "lat": float(reference_city["lat"]),
                        "lon": float(reference_city["lon"]),
                    }
                ]
            ),
            merged[["city_id", "lat", "lon"]].copy(),
        ],
        ignore_index=True,
    ).drop_duplicates(subset=["city_id"])

    tolerance = 1e-6
    exact_match = all_points[
        (all_points["lat"].sub(clicked_lat).abs() < tolerance)
        & (all_points["lon"].sub(clicked_lng).abs() < tolerance)
    ]

    if not exact_match.empty:
        return int(exact_match.iloc[0]["city_id"])

    diffs = (all_points["lat"] - clicked_lat) ** 2 + (all_points["lon"] - clicked_lng) ** 2
    nearest_idx = diffs.idxmin()
    if pd.notna(nearest_idx):
        return int(all_points.loc[nearest_idx, "city_id"])

    return None


countries = load_country_master()

if countries.empty:
    st.error("countries データの読み込みに失敗しました。")
    st.stop()

area1_values = clean_options(countries["area1"])

if "city_suggest_area1_live" not in st.session_state:
    st.session_state["city_suggest_area1_live"] = area1_values.copy()

if "city_suggest_area2_live" not in st.session_state:
    st.session_state["city_suggest_area2_live"] = get_area2_values(
        countries,
        st.session_state["city_suggest_area1_live"],
    )

if "city_suggest_country_id_live" not in st.session_state:
    st.session_state["city_suggest_country_id_live"] = None

if "city_suggest_city_id_live" not in st.session_state:
    st.session_state["city_suggest_city_id_live"] = None


def on_area1_change():
    new_area2_values = get_area2_values(
        countries,
        st.session_state.get("city_suggest_area1_live", []),
    )
    st.session_state["city_suggest_area2_live"] = sync_multiselect_values(
        st.session_state.get("city_suggest_area2_live", []),
        new_area2_values,
    )

    valid_country_df = get_country_df(
        countries,
        st.session_state.get("city_suggest_area1_live", []),
        st.session_state.get("city_suggest_area2_live", []),
    )
    valid_country_ids = valid_country_df["country_id"].astype(int).tolist()

    current_country_id = st.session_state.get("city_suggest_country_id_live")
    if current_country_id not in valid_country_ids:
        st.session_state["city_suggest_country_id_live"] = None
        st.session_state["city_suggest_city_id_live"] = None


def on_area2_change():
    valid_country_df = get_country_df(
        countries,
        st.session_state.get("city_suggest_area1_live", []),
        st.session_state.get("city_suggest_area2_live", []),
    )
    valid_country_ids = valid_country_df["country_id"].astype(int).tolist()

    current_country_id = st.session_state.get("city_suggest_country_id_live")
    if current_country_id not in valid_country_ids:
        st.session_state["city_suggest_country_id_live"] = None
        st.session_state["city_suggest_city_id_live"] = None


def on_country_change():
    st.session_state["city_suggest_city_id_live"] = None


st.subheader("都市選択")

st.multiselect(
    "対象エリア1",
    options=area1_values,
    key="city_suggest_area1_live",
    on_change=on_area1_change,
)

area2_values = get_area2_values(countries, st.session_state["city_suggest_area1_live"])
st.session_state["city_suggest_area2_live"] = sync_multiselect_values(
    st.session_state["city_suggest_area2_live"],
    area2_values,
)

st.multiselect(
    "対象エリア2",
    options=area2_values,
    key="city_suggest_area2_live",
    on_change=on_area2_change,
)

country_df = get_country_df(
    countries,
    st.session_state["city_suggest_area1_live"],
    st.session_state["city_suggest_area2_live"],
)
country_ids = country_df["country_id"].astype(int).tolist()
country_option_records = build_country_option_records(country_df.to_dict("records"))
country_label_map = {int(x["country_id"]): safe_text(x["label"]) for x in country_option_records}
country_name_map = {
    int(row["country_id"]): safe_text(row["country"])
    for _, row in country_df.drop_duplicates(subset=["country_id"]).iterrows()
}

st.session_state["city_suggest_country_id_live"] = sync_single_select_value(
    st.session_state["city_suggest_country_id_live"],
    country_ids,
)

st.selectbox(
    "対象国",
    options=[None] + country_ids,
    key="city_suggest_country_id_live",
    format_func=lambda x: "対象国を選択" if x is None else country_label_map.get(int(x), ""),
    on_change=on_country_change,
)

selected_country_id = st.session_state["city_suggest_country_id_live"]
selected_country_name = country_name_map.get(int(selected_country_id), "") if selected_country_id is not None else ""

city_master = pd.DataFrame()
city_option_records: list[dict[str, Any]] = []

if selected_country_id is not None:
    with st.spinner("対象国の都市一覧を読み込み中..."):
        city_master = load_city_master_by_country_id(int(selected_country_id), selected_country_name)

    if not city_master.empty:
        city_option_records = build_city_option_records(city_master)

city_label_map = get_city_label_map(city_option_records)
city_ids = [int(x["city_id"]) for x in city_option_records]

st.session_state["city_suggest_city_id_live"] = sync_single_select_value(
    st.session_state["city_suggest_city_id_live"],
    city_ids,
)

st.selectbox(
    "基準都市",
    options=[None] + city_ids,
    key="city_suggest_city_id_live",
    format_func=lambda x: "基準都市を選択" if x is None else city_label_map.get(int(x), ""),
    disabled=(len(city_ids) == 0),
)

selected_city_id = st.session_state["city_suggest_city_id_live"]
selected_city_label = city_label_map.get(int(selected_city_id), "") if selected_city_id is not None else ""

selection_debug_snapshot = build_selection_debug_snapshot(
    selected_country_name=selected_country_name,
    selected_country_id=selected_country_id,
    country_option_records=country_option_records,
    city_option_records=city_option_records,
    selected_city_id=selected_city_id,
    selected_city_label=selected_city_label,
)
selection_warning = build_selection_warning(selection_debug_snapshot)

if selected_country_id is not None and not city_option_records:
    st.info("選択した国には選択可能な都市がありません。都市データの有無を確認してください。")

if selection_warning and DEBUG_MODE:
    st.caption(f"デバッグ: {selection_warning}")

month_map = {
    1: "1月",
    2: "2月",
    3: "3月",
    4: "4月",
    5: "5月",
    6: "6月",
    7: "7月",
    8: "8月",
    9: "9月",
    10: "10月",
    11: "11月",
    12: "12月",
}

with st.form("nearby_city_search_form"):
    st.subheader("検索条件")

    selected_month = st.selectbox(
        "特定の月",
        options=list(month_map.keys()),
        format_func=lambda x: month_map[x],
        index=0,
    )

    min_temp = st.slider("最低気温（下限）", -10, 35, 15)
    max_temp = st.slider("最高気温（上限）", 10, 45, 30)

    elevation_range = st.slider(
        "標高（m）",
        min_value=-100,
        max_value=5000,
        value=(-100, 5000),
        step=100,
    )

    max_distance_km = st.slider(
        "基準都市からの距離（km）",
        min_value=10,
        max_value=300,
        value=50,
        step=10,
    )

    city_count = st.slider("各月の表示都市数", 1, 30, 5)

    submitted = st.form_submit_button(
        "検索",
        disabled=(selected_country_id is None or selected_city_id is None),
    )

if submitted:
    st.session_state["city_suggest_last_search"] = {
        "selected_country_id": selected_country_id,
        "selected_country_name": selected_country_name,
        "selected_city_id": selected_city_id,
        "selected_month": selected_month,
        "min_temp": min_temp,
        "max_temp": max_temp,
        "elevation_range": elevation_range,
        "max_distance_km": max_distance_km,
        "city_count": city_count,
    }

search_state = st.session_state.get("city_suggest_last_search")

if search_state:
    missing_search_state_keys = get_missing_search_state_keys(search_state)
    if missing_search_state_keys:
        st.warning("前回の検索条件が不完全です。条件を選び直して再実行してください。")
        if DEBUG_MODE:
            st.json(
                {
                    "page": "city_suggest",
                    "issue": "missing_search_state_keys",
                    "missing_keys": missing_search_state_keys,
                    "search_state_keys": sorted(search_state.keys()),
                }
            )
        st.stop()

    debug_rows: list[dict[str, Any]] = []
    page_t0 = time.perf_counter()

    selected_country_id = search_state["selected_country_id"]
    selected_country_name = search_state["selected_country_name"]
    selected_city_id = search_state["selected_city_id"]
    selected_month = search_state["selected_month"]
    min_temp = search_state["min_temp"]
    max_temp = search_state["max_temp"]
    elevation_range = tuple(search_state["elevation_range"])
    max_distance_km = search_state["max_distance_km"]
    city_count = search_state["city_count"]

    if selected_country_id is None:
        st.warning("対象国を選択してください。")
        st.stop()

    if selected_city_id is None:
        st.warning("基準都市を選択してください。")
        st.stop()

    with st.spinner("対象国の都市データを読み込み中..."):
        city_master = measure(
            debug_rows,
            "load_city_master_by_country_id",
            lambda: load_city_master_by_country_id(int(selected_country_id), selected_country_name).copy(),
        )

    if city_master.empty:
        st.warning("対象国の都市データがありません。")
        st.stop()

    t0 = time.perf_counter()
    reference_city = city_master[city_master["city_id"] == int(selected_city_id)].copy()
    debug_rows.append({"process": "extract_reference_city", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    if reference_city.empty:
        st.warning("基準都市が見つかりません。")
        st.stop()

    reference_city = reference_city.iloc[0]
    if pd.isna(reference_city.get("lat")) or pd.isna(reference_city.get("lon")):
        st.warning("選択した基準都市には位置情報がないため、近隣都市検索を実行できません。")
        st.stop()

    reference_city_id = int(reference_city["city_id"])
    reference_lat = float(reference_city["lat"])
    reference_lon = float(reference_city["lon"])

    t0 = time.perf_counter()
    candidates = city_master[city_master["city_id"] != reference_city_id].copy()
    candidates = candidates.dropna(subset=["lat", "lon"]).copy()
    debug_rows.append({"process": "exclude_reference_city", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    if candidates.empty:
        st.info("同一国内に候補都市がありません。")
        st.stop()

    t0 = time.perf_counter()
    candidates["elevation"] = pd.to_numeric(candidates["elevation"], errors="coerce")
    candidates = candidates[
        (candidates["elevation"] >= elevation_range[0])
        & (candidates["elevation"] <= elevation_range[1])
    ].copy()
    debug_rows.append({"process": "filter_by_elevation", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    if candidates.empty:
        st.info("標高条件に合う都市がありません。")
        st.stop()

    t0 = time.perf_counter()
    min_lat, max_lat, min_lon, max_lon = calc_bbox(reference_lat, reference_lon, max_distance_km)
    candidates = candidates[
        (candidates["lat"] >= min_lat)
        & (candidates["lat"] <= max_lat)
        & (candidates["lon"] >= min_lon)
        & (candidates["lon"] <= max_lon)
    ].copy()
    debug_rows.append({"process": "filter_bbox_candidates", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    if candidates.empty:
        st.info("距離条件に合う候補都市がありません。")
        st.stop()

    t0 = time.perf_counter()
    candidate_city_ids = tuple(sorted(candidates["city_id"].dropna().astype(int).unique().tolist()))
    debug_rows.append({"process": "build_candidate_city_ids", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    with st.spinner("対象月の気候データを読み込み中..."):
        climate_month = measure(
            debug_rows,
            "load_climate_by_city_ids_and_month",
            lambda: load_climate_by_city_ids_and_month(candidate_city_ids, int(selected_month)).copy(),
        )

    if climate_month.empty:
        st.info("対象月の気候データがある候補都市がありません。")
        st.stop()

    t0 = time.perf_counter()
    merged = candidates.merge(climate_month, on="city_id", how="inner")
    debug_rows.append({"process": "merge_candidates_climate", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    if merged.empty:
        st.info("対象月の気候データがある候補都市がありません。")
        st.stop()

    t0 = time.perf_counter()
    for col in ["min_temp", "avg_temp", "max_temp"]:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")

    merged = merged[(merged["min_temp"] >= min_temp) & (merged["max_temp"] <= max_temp)].copy()
    debug_rows.append({"process": "filter_by_temperature", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    if merged.empty:
        st.info("気温条件に合う都市がありません。")
        st.stop()

    t0 = time.perf_counter()
    merged["distance_km"] = haversine_km(
        reference_lat,
        reference_lon,
        merged["lat"].to_numpy(dtype=float),
        merged["lon"].to_numpy(dtype=float),
    )
    debug_rows.append({"process": "calc_haversine", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    t0 = time.perf_counter()
    merged = merged[merged["distance_km"] <= max_distance_km].copy()
    debug_rows.append({"process": "filter_by_distance", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    if merged.empty:
        st.info("距離条件に合う都市がありません。")
        st.stop()

    t0 = time.perf_counter()
    ideal_avg_temp = (min_temp + max_temp) / 2
    merged["temp_gap"] = (merged["avg_temp"] - ideal_avg_temp).abs()

    merged = merged.sort_values(
        by=["distance_km", "temp_gap", "city_jp", "city_en"],
        ascending=[True, True, True, True],
    ).head(city_count)
    debug_rows.append({"process": "sort_and_limit_results", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    st.markdown("---")
    st.subheader("検索結果")

    st.caption(
        f"基準都市: {safe_text(reference_city.get('city_jp'))} / {safe_text(reference_city.get('city_en'))} "
        f"｜{safe_text(reference_city.get('country'))}"
    )
    st.caption(
        f"対象月: {month_map[selected_month]} ｜ 距離上限: {max_distance_km}km "
        f"｜ 気温: 最低 {min_temp}℃以上 / 最高 {max_temp}℃以下 "
        f"｜ 標高: {elevation_range[0]}m ～ {elevation_range[1]}m"
    )

    t0 = time.perf_counter()
    display_cols = [
        "city_id",
        "country",
        "city_jp",
        "city_en",
        "distance_km",
        "min_temp",
        "avg_temp",
        "max_temp",
        "elevation",
    ]
    result_table = merged[display_cols].copy()
    result_table["distance_km"] = result_table["distance_km"].round(1)
    debug_rows.append({"process": "build_result_table", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    def render_result_table():
        st.dataframe(result_table, width="stretch", hide_index=True)

    measure(debug_rows, "render_result_table", render_result_table)

    st.markdown("### 地図")
    st.caption("ピンをクリックすると都市詳細ページへ遷移します。")

    fmap = measure(debug_rows, "build_result_map", lambda: build_result_map(reference_city, merged))

    map_data = measure(
        debug_rows,
        "render_st_folium",
        lambda: st_folium(
            fmap,
            key="nearby_city_map",
            height=560,
            use_container_width=True,
            returned_objects=["last_object_clicked"],
        ),
    )

    clicked_point = None
    if isinstance(map_data, dict):
        clicked_point = map_data.get("last_object_clicked")

    t0 = time.perf_counter()
    clicked_city_id = resolve_clicked_city_id(clicked_point, reference_city, merged)
    debug_rows.append({"process": "resolve_clicked_city_id", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    if clicked_city_id is not None:
        st.session_state["selected_city_id"] = int(clicked_city_id)
        st.switch_page("pages/city_detail.py")

    page_total_ms = round((time.perf_counter() - page_t0) * 1000, 3)
    debug_rows.append({"process": "page_total", "ms": page_total_ms})

    if DEBUG_MODE:
        with st.expander("パフォーマンスデバッグ", expanded=True):
            st.json(
                {
                    "page": "city_suggest",
                    "selection_debug_snapshot": selection_debug_snapshot,
                    "selected_country_id": int(selected_country_id),
                    "selected_city_id": int(selected_city_id),
                    "city_master_rows": int(len(city_master)),
                    "candidate_city_ids": int(len(candidate_city_ids)),
                    "climate_rows": int(len(climate_month)),
                    "result_rows": int(len(result_table)),
                    "page_total_ms": page_total_ms,
                }
            )
            st.dataframe(pd.DataFrame(debug_rows), width="stretch", hide_index=True)
