import streamlit as st
import pandas as pd
from utils.sheets import load_data

st.title("年間居住都市レコメンド")

data = load_data()
countries = data.countries.copy()
cities = data.cities.copy()
climate = data.climate.copy()

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


area1_values = clean_options(countries_flag1["area1"])

# 初期化
if "selected_area1_live" not in st.session_state:
    st.session_state["selected_area1_live"] = area1_values

if "selected_area2_live" not in st.session_state:
    st.session_state["selected_area2_live"] = []

if "selected_country_live" not in st.session_state:
    st.session_state["selected_country_live"] = []

st.subheader("検索条件")

# ----------------------------
# form の外で連鎖させる項目
# ----------------------------
selected_area1 = st.multiselect(
    "対象エリア1",
    options=area1_values,
    default=st.session_state["selected_area1_live"],
    placeholder="対象エリア1を選択",
    key="selected_area1_live",
)

area2_base = countries_flag1.copy()
if selected_area1:
    area2_base = area2_base[area2_base["area1"].isin(selected_area1)]

area2_values = clean_options(area2_base["area2"])

# 候補外になった値は落とす
valid_area2 = [x for x in st.session_state["selected_area2_live"] if x in area2_values]
if valid_area2 != st.session_state["selected_area2_live"]:
    st.session_state["selected_area2_live"] = valid_area2

selected_area2 = st.multiselect(
    "対象エリア2",
    options=area2_values,
    default=st.session_state["selected_area2_live"],
    placeholder="対象エリア2を選択",
    key="selected_area2_live",
)

country_base = countries_flag1.copy()
if selected_area1:
    country_base = country_base[country_base["area1"].isin(selected_area1)]
if selected_area2:
    country_base = country_base[country_base["area2"].isin(selected_area2)]

country_values = clean_options(country_base["country"])

valid_country = [x for x in st.session_state["selected_country_live"] if x in country_values]
if valid_country != st.session_state["selected_country_live"]:
    st.session_state["selected_country_live"] = valid_country

selected_country = st.multiselect(
    "対象国",
    options=country_values,
    default=st.session_state["selected_country_live"],
    placeholder="対象国を選択",
    key="selected_country_live",
)

# ----------------------------
# form に残す項目
# ----------------------------
with st.form("search_form"):
    temp_range = st.slider(
        "気温",
        min_value=-10,
        max_value=45,
        value=st.session_state.get("temp_range_live", (15, 30)),
        step=1,
    )

    elevation_range = st.slider(
        "標高（m）",
        min_value=-100,
        max_value=2000,
        value=st.session_state.get("elevation_range_live", (-100, 2000)),
        step=100,
    )

    city_count = st.slider(
        "表示都市数",
        1,
        30,
        st.session_state.get("city_count_live", 5),
    )

    submitted = st.form_submit_button("検索")

    if submitted:
        st.session_state["temp_range_live"] = temp_range
        st.session_state["elevation_range_live"] = elevation_range
        st.session_state["city_count_live"] = city_count

        st.session_state["city_search_submitted"] = True
        st.session_state["city_search_conditions"] = {
            "selected_area1": selected_area1,
            "selected_area2": selected_area2,
            "selected_country": selected_country,
            "temp_min": temp_range[0],
            "temp_max": temp_range[1],
            "elevation_min": elevation_range[0],
            "elevation_max": elevation_range[1],
            "city_count": city_count,
        }

if st.session_state.get("city_search_submitted"):
    cond = st.session_state.get("city_search_conditions", {})

    selected_area1 = cond.get("selected_area1", area1_values)
    selected_area2 = cond.get("selected_area2", [])
    selected_country = cond.get("selected_country", [])
    temp_min = cond.get("temp_min", 15)
    temp_max = cond.get("temp_max", 30)
    elevation_min = cond.get("elevation_min", -100)
    elevation_max = cond.get("elevation_max", 2000)
    city_count = cond.get("city_count", 5)

    filtered_countries = countries_flag1.copy()

    if selected_area1:
        filtered_countries = filtered_countries[filtered_countries["area1"].isin(selected_area1)]
    if selected_area2:
        filtered_countries = filtered_countries[filtered_countries["area2"].isin(selected_area2)]
    if selected_country:
        filtered_countries = filtered_countries[filtered_countries["country"].isin(selected_country)]

    if filtered_countries.empty:
        st.warning("条件に合う国がありません。")
        st.stop()

    target_country_ids = filtered_countries["country_id"].dropna().unique().tolist()
    filtered_cities = cities[cities["country_id"].isin(target_country_ids)].copy()

    if filtered_cities.empty:
        st.warning("条件に合う都市がありません。")
        st.stop()

    if "elevation" in filtered_cities.columns:
        filtered_cities["elevation"] = pd.to_numeric(filtered_cities["elevation"], errors="coerce")

        if elevation_max >= 2000:
            filtered_cities = filtered_cities[
                filtered_cities["elevation"] >= elevation_min
            ]
        else:
            filtered_cities = filtered_cities[
                (filtered_cities["elevation"] >= elevation_min)
                & (filtered_cities["elevation"] <= elevation_max)
            ]

    if filtered_cities.empty:
        st.warning("条件に合う都市がありません。")
        st.stop()

    merged = climate.merge(filtered_cities, on="city_id", how="inner").merge(
        filtered_countries, on="country_id", how="left"
    )

    for col in ["min_temp", "avg_temp", "max_temp", "precip_mm"]:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")

    for month in range(1, 13):
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

        if month_df.empty:
            st.write("該当なし")
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
                timezone_val = row.get("timezone", "")

                min_temp_val = row.get("min_temp", "")
                avg_temp_val = row.get("avg_temp", "")
                max_temp_val = row.get("max_temp", "")
                precip_mm_val = row.get("precip_mm", "")
                elevation_val = row.get("elevation", "")

                with col1:
                    if st.button(
                        f"{city_jp} / {city_en}",
                        key=f"detail_{month}_{int(row['city_id'])}",
                    ):
                        st.session_state["selected_city_id"] = int(row["city_id"])
                        st.switch_page("pages/city_detail.py")
                    st.caption(f"{country}｜{area_text}")

                with col2:
                    render_label_value("人口", format_population(population_val))
                    render_label_value("通貨", format_text(currency_val))
                    render_label_value("TZ", format_text(timezone_val))

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

else:
    st.info("条件を入れて検索すると、月ごとのおすすめ都市を表示します。")