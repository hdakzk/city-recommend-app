import math

import folium
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from utils.sheets import load_data

st.title("近隣都市レコメンド")


@st.cache_data(show_spinner=False)
def prepare_search_data():
    data = load_data()

    countries = data.countries.copy()
    cities = data.cities.copy()
    climate = data.climate.copy()

    countries = countries[countries["flag"] == 1].copy()

    countries = countries[
        [
            "country_id",
            "country",
            "country_en",
            "area1",
            "area2",
            "flag",
        ]
    ].copy()

    cities = cities[
        [
            "city_id",
            "country_id",
            "city_jp",
            "city_en",
            "lat",
            "lon",
            "population",
            "elevation",
            "cost_index",
        ]
    ].copy()

    climate = climate[
        [
            "city_id",
            "month",
            "min_temp",
            "avg_temp",
            "max_temp",
            "precip_mm",
        ]
    ].copy()

    city_master = cities.merge(
        countries,
        on="country_id",
        how="inner",
        suffixes=("", "_country"),
    )

    city_master = city_master.dropna(subset=["city_id", "country_id", "lat", "lon"]).copy()
    city_master["city_id"] = city_master["city_id"].astype(int)
    city_master["country_id"] = city_master["country_id"].astype(int)
    city_master["lat"] = pd.to_numeric(city_master["lat"], errors="coerce")
    city_master["lon"] = pd.to_numeric(city_master["lon"], errors="coerce")
    city_master = city_master.dropna(subset=["lat", "lon"]).copy()

    climate["city_id"] = pd.to_numeric(climate["city_id"], errors="coerce")
    climate["month"] = pd.to_numeric(climate["month"], errors="coerce")
    climate = climate.dropna(subset=["city_id", "month"]).copy()
    climate["city_id"] = climate["city_id"].astype(int)
    climate["month"] = climate["month"].astype(int)

    return city_master, climate


def safe_text(v) -> str:
    if pd.isna(v):
        return ""
    s = str(v).strip()
    return "" if s.lower() in {"nan", "none"} else s


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


city_master, climate = prepare_search_data()

city_base = city_master.sort_values(
    by=["city_jp", "city_en", "country", "city_id"],
    ascending=[True, True, True, True],
).copy()

city_base["city_search_label"] = city_base.apply(
    lambda row: (
        f"{safe_text(row.get('city_jp'))} / {safe_text(row.get('city_en'))} "
        f"｜{safe_text(row.get('country'))}｜ID:{int(row.get('city_id'))}"
    ),
    axis=1,
)

city_options_df = city_base[
    ["city_id", "city_search_label"]
].drop_duplicates(subset=["city_id"]).copy()

selected_city_label = st.selectbox(
    "基準都市",
    options=city_options_df["city_search_label"].tolist(),
    index=None,
    placeholder="都市名で検索して選択してください",
)

selected_city_id = None
if selected_city_label:
    matched_city = city_options_df[city_options_df["city_search_label"] == selected_city_label]
    if not matched_city.empty:
        selected_city_id = int(matched_city.iloc[0]["city_id"])

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

    submitted = st.form_submit_button("検索")

if submitted:
    st.session_state["city_suggest_last_search"] = {
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
    selected_city_id = search_state["selected_city_id"]
    selected_month = search_state["selected_month"]
    min_temp = search_state["min_temp"]
    max_temp = search_state["max_temp"]
    elevation_range = tuple(search_state["elevation_range"])
    max_distance_km = search_state["max_distance_km"]
    city_count = search_state["city_count"]

    if selected_city_id is None:
        st.warning("基準都市を選択してください。")
        st.stop()

    reference_city = city_master[city_master["city_id"] == int(selected_city_id)].copy()
    if reference_city.empty:
        st.warning("基準都市が見つかりません。")
        st.stop()

    reference_city = reference_city.iloc[0]
    reference_city_id = int(reference_city["city_id"])
    reference_country_id = int(reference_city["country_id"])
    reference_lat = float(reference_city["lat"])
    reference_lon = float(reference_city["lon"])

    candidates = city_master[
        (city_master["country_id"] == reference_country_id)
        & (city_master["city_id"] != reference_city_id)
    ].copy()

    if candidates.empty:
        st.info("同一国内に候補都市がありません。")
        st.stop()

    candidates["elevation"] = pd.to_numeric(candidates["elevation"], errors="coerce")
    candidates = candidates[
        (candidates["elevation"] >= elevation_range[0])
        & (candidates["elevation"] <= elevation_range[1])
    ].copy()

    if candidates.empty:
        st.info("標高条件に合う都市がありません。")
        st.stop()

    min_lat, max_lat, min_lon, max_lon = calc_bbox(reference_lat, reference_lon, max_distance_km)
    candidates = candidates[
        (candidates["lat"] >= min_lat)
        & (candidates["lat"] <= max_lat)
        & (candidates["lon"] >= min_lon)
        & (candidates["lon"] <= max_lon)
    ].copy()

    if candidates.empty:
        st.info("距離条件に合う候補都市がありません。")
        st.stop()

    climate_month = climate[climate["month"] == int(selected_month)].copy()
    merged = candidates.merge(climate_month, on="city_id", how="inner")

    if merged.empty:
        st.info("対象月の気候データがある候補都市がありません。")
        st.stop()

    merged = merged[
        (merged["min_temp"] >= min_temp)
        & (merged["max_temp"] <= max_temp)
    ].copy()

    if merged.empty:
        st.info("気温条件に合う都市がありません。")
        st.stop()

    merged["distance_km"] = haversine_km(
        reference_lat,
        reference_lon,
        merged["lat"].to_numpy(dtype=float),
        merged["lon"].to_numpy(dtype=float),
    )

    merged = merged[merged["distance_km"] <= max_distance_km].copy()

    if merged.empty:
        st.info("距離条件に合う都市がありません。")
        st.stop()

    ideal_avg_temp = (min_temp + max_temp) / 2
    merged["temp_gap"] = (merged["avg_temp"] - ideal_avg_temp).abs()

    merged = merged.sort_values(
        by=["distance_km", "temp_gap", "city_jp", "city_en"],
        ascending=[True, True, True, True],
    ).head(city_count)

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

    st.dataframe(
        result_table,
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("### 地図")
    st.caption("ピンをクリックすると都市詳細ページへ遷移します。")

    fmap = build_result_map(reference_city, merged)

    map_data = st_folium(
        fmap,
        key="nearby_city_map",
        height=560,
        use_container_width=True,
        returned_objects=["last_object_clicked"],
    )

    clicked_point = None
    if isinstance(map_data, dict):
        clicked_point = map_data.get("last_object_clicked")

    clicked_city_id = resolve_clicked_city_id(clicked_point, reference_city, merged)

    if clicked_city_id is not None:
        st.session_state["selected_city_id"] = int(clicked_city_id)
        st.switch_page("pages/city_detail.py")