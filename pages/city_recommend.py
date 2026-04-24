from pathlib import Path
import sys
import time
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from utils.db import load_cities_by_country_ids, load_climate_by_city_ids, load_countries

st.set_page_config(layout="wide")
st.title("年間居住都市レコメンド")

DEBUG_MODE = True


def measure(debug_rows: list[dict[str, Any]], label: str, func):
    t0 = time.perf_counter()
    result = func()
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)
    debug_rows.append({"process": label, "ms": elapsed_ms})
    return result


@st.cache_data(ttl=1800, show_spinner=False)
def load_country_master() -> pd.DataFrame:
    return load_countries().copy()


countries = load_country_master()

if countries.empty:
    st.error("countries データの読み込みに失敗しました。")
    st.stop()

required_country_cols = {"country_id", "country", "area1", "area2", "flag"}
missing_country_cols = required_country_cols - set(countries.columns)
if missing_country_cols:
    st.error(f"countries テーブルに必要な列がありません: {sorted(missing_country_cols)}")
    st.stop()

countries_flag1 = countries[countries["flag"] == 1].copy()


def clean_options(series):
    return sorted(
        [
            x
            for x in series.dropna().astype(str).str.strip().unique().tolist()
            if x and x.lower() != "nan"
        ]
    )


def format_temp(val):
    if pd.isna(val):
        return "-"
    return f"{float(val):.1f}℃"


def format_population(val):
    if pd.isna(val) or val == "":
        return "-"
    try:
        return f"{int(float(val)):,}人"
    except Exception:
        return f"{val}人"


def format_precip(val):
    if pd.isna(val) or val == "":
        return "-"
    try:
        return f"{float(val):.1f} mm"
    except Exception:
        return str(val)


def format_text(val):
    if pd.isna(val) or str(val).strip() == "":
        return "-"
    return str(val).strip()


def render_label_value(label, value):
    st.markdown(
        f"""
        <div style="
            display:flex;
            justify-content:space-between;
            align-items:flex-start;
            gap:12px;
            width:100%;
            margin:0 0 6px 0;
            line-height:1.5;
        ">
            <span style="
                white-space:nowrap;
                font-weight:600;
                flex-shrink:0;
            ">{label}</span>
            <span style="
                text-align:right;
                word-break:break-word;
                overflow-wrap:anywhere;
                flex:1;
            ">{value}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def get_area2_values(selected_area1):
    df = countries_flag1.copy()
    if selected_area1:
        df = df[df["area1"].isin(selected_area1)]
    return clean_options(df["area2"])


def get_country_values(selected_area1, selected_area2):
    df = countries_flag1.copy()
    if selected_area1:
        df = df[df["area1"].isin(selected_area1)]
    if selected_area2:
        df = df[df["area2"].isin(selected_area2)]
    return clean_options(df["country"])


def on_area1_change():
    selected_area1 = st.session_state.get("selected_area1_live", [])

    new_area2_values = get_area2_values(selected_area1)
    st.session_state["selected_area2_live"] = new_area2_values

    new_country_values = get_country_values(
        st.session_state["selected_area1_live"],
        st.session_state["selected_area2_live"],
    )
    st.session_state["selected_country_live"] = new_country_values


def on_area2_change():
    selected_area1 = st.session_state.get("selected_area1_live", [])
    selected_area2 = st.session_state.get("selected_area2_live", [])

    new_country_values = get_country_values(selected_area1, selected_area2)
    st.session_state["selected_country_live"] = new_country_values


area1_values = clean_options(countries_flag1["area1"])

if "selected_area1_live" not in st.session_state:
    st.session_state["selected_area1_live"] = area1_values.copy()

if "selected_area2_live" not in st.session_state:
    st.session_state["selected_area2_live"] = get_area2_values(
        st.session_state["selected_area1_live"]
    )

if "selected_country_live" not in st.session_state:
    st.session_state["selected_country_live"] = get_country_values(
        st.session_state["selected_area1_live"],
        st.session_state["selected_area2_live"],
    )

if "temp_range_live" not in st.session_state:
    st.session_state["temp_range_live"] = (15, 30)

if "elevation_range_live" not in st.session_state:
    st.session_state["elevation_range_live"] = (-100, 2000)

if "city_count_live" not in st.session_state:
    st.session_state["city_count_live"] = 5

area2_values = get_area2_values(st.session_state["selected_area1_live"])
valid_area2 = [x for x in st.session_state["selected_area2_live"] if x in area2_values]
if not valid_area2:
    valid_area2 = area2_values
st.session_state["selected_area2_live"] = valid_area2

country_values = get_country_values(
    st.session_state["selected_area1_live"],
    st.session_state["selected_area2_live"],
)
valid_country = [x for x in st.session_state["selected_country_live"] if x in country_values]
if not valid_country:
    valid_country = country_values
st.session_state["selected_country_live"] = valid_country

st.subheader("検索条件")

selected_area1 = st.multiselect(
    "対象エリア1",
    options=area1_values,
    placeholder="対象エリア1を選択",
    key="selected_area1_live",
    on_change=on_area1_change,
)

area2_values = get_area2_values(st.session_state["selected_area1_live"])

selected_area2 = st.multiselect(
    "対象エリア2",
    options=area2_values,
    placeholder="対象エリア2を選択",
    key="selected_area2_live",
    on_change=on_area2_change,
)

country_values = get_country_values(
    st.session_state["selected_area1_live"],
    st.session_state["selected_area2_live"],
)

selected_country = st.multiselect(
    "対象国",
    options=country_values,
    placeholder="対象国を選択",
    key="selected_country_live",
)

with st.form("search_form"):
    temp_range = st.slider("気温", min_value=-10, max_value=45, value=st.session_state["temp_range_live"], step=1)

    elevation_range = st.slider(
        "標高（m）",
        min_value=-100,
        max_value=2000,
        value=st.session_state["elevation_range_live"],
        step=100,
    )

    city_count = st.slider("表示都市数", min_value=1, max_value=30, value=st.session_state["city_count_live"])

    submitted = st.form_submit_button("検索")

    if submitted:
        st.session_state["temp_range_live"] = temp_range
        st.session_state["elevation_range_live"] = elevation_range
        st.session_state["city_count_live"] = city_count

        st.session_state["city_search_submitted"] = True
        st.session_state["city_search_conditions"] = {
            "selected_area1": st.session_state["selected_area1_live"].copy(),
            "selected_area2": st.session_state["selected_area2_live"].copy(),
            "selected_country": st.session_state["selected_country_live"].copy(),
            "temp_min": temp_range[0],
            "temp_max": temp_range[1],
            "elevation_min": elevation_range[0],
            "elevation_max": elevation_range[1],
            "city_count": city_count,
        }

if st.session_state.get("city_search_submitted"):
    debug_rows: list[dict[str, Any]] = []
    page_t0 = time.perf_counter()

    cond = st.session_state.get("city_search_conditions", {})

    selected_area1 = cond.get("selected_area1", area1_values)
    selected_area2 = cond.get("selected_area2", [])
    selected_country = cond.get("selected_country", [])
    temp_min = cond.get("temp_min", 15)
    temp_max = cond.get("temp_max", 30)
    elevation_min = cond.get("elevation_min", -100)
    elevation_max = cond.get("elevation_max", 2000)
    city_count = cond.get("city_count", 5)

    t0 = time.perf_counter()
    filtered_countries = countries_flag1.copy()

    if selected_area1:
        filtered_countries = filtered_countries[filtered_countries["area1"].isin(selected_area1)]
    if selected_area2:
        filtered_countries = filtered_countries[filtered_countries["area2"].isin(selected_area2)]
    if selected_country:
        filtered_countries = filtered_countries[filtered_countries["country"].isin(selected_country)]

    debug_rows.append({"process": "filter_countries", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    if filtered_countries.empty:
        st.warning("条件に合う国がありません。")
        st.stop()

    t0 = time.perf_counter()
    target_country_ids = tuple(sorted(filtered_countries["country_id"].dropna().astype(int).unique().tolist()))
    debug_rows.append({"process": "build_target_country_ids", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    with st.spinner("対象国の都市データを読み込み中..."):
        filtered_cities = measure(
            debug_rows,
            "load_cities_by_country_ids",
            lambda: load_cities_by_country_ids(target_country_ids).copy(),
        )

    if filtered_cities.empty:
        st.warning("条件に合う都市がありません。")
        st.stop()

    t0 = time.perf_counter()
    if "elevation" in filtered_cities.columns:
        filtered_cities["elevation"] = pd.to_numeric(filtered_cities["elevation"], errors="coerce")

        if elevation_max >= 2000:
            filtered_cities = filtered_cities[filtered_cities["elevation"] >= elevation_min]
        else:
            filtered_cities = filtered_cities[
                (filtered_cities["elevation"] >= elevation_min)
                & (filtered_cities["elevation"] <= elevation_max)
            ]
    debug_rows.append({"process": "filter_cities_by_elevation", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    if filtered_cities.empty:
        st.warning("条件に合う都市がありません。")
        st.stop()

    t0 = time.perf_counter()
    target_city_ids = tuple(sorted(filtered_cities["city_id"].dropna().astype(int).unique().tolist()))
    debug_rows.append({"process": "build_target_city_ids", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    with st.spinner("対象都市の気候データを読み込み中..."):
        climate = measure(
            debug_rows,
            "load_climate_by_city_ids",
            lambda: load_climate_by_city_ids(target_city_ids).copy(),
        )

    if climate.empty:
        st.warning("対象都市の気候データがありません。")
        st.stop()

    t0 = time.perf_counter()
    merged = climate.merge(filtered_cities, on="city_id", how="inner").merge(
        filtered_countries, on="country_id", how="left"
    )
    debug_rows.append({"process": "merge_city_climate_country", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    t0 = time.perf_counter()
    for col in ["min_temp", "avg_temp", "max_temp", "precip_mm"]:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")
    debug_rows.append({"process": "normalize_merged_numeric", "ms": round((time.perf_counter() - t0) * 1000, 3)})

    total_result_rows = 0

    for month in range(1, 13):
        month_t0 = time.perf_counter()
        st.subheader(f"{month}月")

        month_df = merged[
            (merged["month"] == month)
            & (merged["min_temp"] >= temp_min)
            & (merged["max_temp"] <= temp_max)
        ].copy()

        if "avg_temp" in month_df.columns:
            ideal_avg_temp = (temp_min + temp_max) / 2
            month_df["match_score"] = (month_df["avg_temp"] - ideal_avg_temp).abs()
            month_df = month_df.sort_values("match_score", ascending=True)

        month_df = month_df.head(city_count)
        total_result_rows += len(month_df)

        if month_df.empty:
            st.write("該当なし")
            debug_rows.append({"process": f"render_month_{month}", "ms": round((time.perf_counter() - month_t0) * 1000, 3)})
            continue

        for _, row in month_df.iterrows():
            with st.container(border=True):
                col1, col2, col3, col4 = st.columns([2.5, 2.4, 1.8, 1.8])

                city_jp = row.get("city_jp", "")
                city_en = row.get("city_en", "")
                country = row.get("country", "")
                area_text = f"{row.get('area1', '')} > {row.get('area2', '')}"

                population_val = row.get("population", "")
                currency_val = row.get("currency_code", "")

                min_temp_val = row.get("min_temp", "")
                avg_temp_val = row.get("avg_temp", "")
                max_temp_val = row.get("max_temp", "")
                precip_mm_val = row.get("precip_mm", "")
                elevation_val = row.get("elevation", "")

                with col1:
                    if st.button(f"{city_jp} / {city_en}", key=f"detail_{month}_{int(row['city_id'])}"):
                        st.session_state["selected_city_id"] = int(row["city_id"])
                        st.switch_page("pages/city_detail.py")
                    st.caption(f"{country}｜{area_text}")

                with col2:
                    render_label_value("人口", format_population(population_val))
                    render_label_value("通貨", format_text(currency_val))

                with col3:
                    render_label_value("最低", format_temp(min_temp_val))
                    render_label_value("平均", format_temp(avg_temp_val))
                    render_label_value("最高", format_temp(max_temp_val))

                with col4:
                    render_label_value("降水量", format_precip(precip_mm_val))
                    if pd.notna(elevation_val):
                        render_label_value("標高", f"{int(float(elevation_val)):,} m")
                    else:
                        render_label_value("標高", "-")

        debug_rows.append({"process": f"render_month_{month}", "ms": round((time.perf_counter() - month_t0) * 1000, 3)})

    page_total_ms = round((time.perf_counter() - page_t0) * 1000, 3)
    debug_rows.append({"process": "page_total", "ms": page_total_ms})

    if DEBUG_MODE:
        with st.expander("パフォーマンスデバッグ", expanded=True):
            st.json(
                {
                    "page": "city_recommend",
                    "country_count": int(len(target_country_ids)),
                    "city_rows": int(len(filtered_cities)),
                    "target_city_ids": int(len(target_city_ids)),
                    "climate_rows": int(len(climate)),
                    "result_rows": int(total_result_rows),
                    "page_total_ms": page_total_ms,
                }
            )
            st.dataframe(pd.DataFrame(debug_rows), width="stretch", hide_index=True)

else:
    st.info("条件を入れて検索すると、月ごとのおすすめ都市を表示します。")
