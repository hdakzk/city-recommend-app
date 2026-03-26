import streamlit as st
import pandas as pd
from utils.sheets import load_data

st.title("年間居住都市レコメンド")

data = load_data()
countries = data.countries.copy()
cities = data.cities.copy()
climate = data.climate.copy()

countries_flag1 = countries[countries["flag"] == 1].copy()

area1_options = sorted(
    [
        x
        for x in countries_flag1["area1"].dropna().astype(str).str.strip().unique().tolist()
        if x and x != "nan"
    ]
)
default_area1 = area1_options

with st.form("search_form"):
    st.subheader("検索条件")

    selected_area1 = st.multiselect(
        "対象エリア1（Countries.area1）",
        options=area1_options,
        default=default_area1,
    )

    area2_base = countries_flag1.copy()
    if selected_area1:
        area2_base = area2_base[area2_base["area1"].isin(selected_area1)]

    area2_options = sorted(
        [
            x
            for x in area2_base["area2"].dropna().astype(str).str.strip().unique().tolist()
            if x and x != "nan"
        ]
    )

    selected_area2 = st.multiselect(
        "対象エリア2（Countries.area2）",
        options=area2_options,
        default=area2_options,
    )

    country_base = countries_flag1.copy()
    if selected_area1:
        country_base = country_base[country_base["area1"].isin(selected_area1)]
    if selected_area2:
        country_base = country_base[country_base["area2"].isin(selected_area2)]

    country_options = sorted(
        [
            x
            for x in country_base["country"].dropna().astype(str).str.strip().unique().tolist()
            if x and x != "nan"
        ]
    )

    selected_countries = st.multiselect(
        "対象国（Countries.country / flag=1のみ）",
        options=country_options,
        default=country_options,
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

    city_count = st.slider("各月の表示都市数", 1, 30, 5)

    submitted = st.form_submit_button("検索")

    if submitted:
        st.session_state["city_search_submitted"] = True
        st.session_state["city_search_conditions"] = {
            "selected_area1": selected_area1,
            "selected_area2": selected_area2,
            "selected_countries": selected_countries,
            "min_temp": min_temp,
            "max_temp": max_temp,
            "elevation_min": elevation_range[0],
            "elevation_max": elevation_range[1],
            "city_count": city_count,
        }

if st.session_state.get("city_search_submitted"):
    cond = st.session_state.get("city_search_conditions", {})

    selected_area1 = cond.get("selected_area1", [])
    selected_area2 = cond.get("selected_area2", [])
    selected_countries = cond.get("selected_countries", [])
    min_temp = cond.get("min_temp", 15)
    max_temp = cond.get("max_temp", 30)
    elevation_min = cond.get("elevation_min", -100)
    elevation_max = cond.get("elevation_max", 5000)
    city_count = cond.get("city_count", 5)

    filtered_countries = countries_flag1.copy()

    if selected_area1:
        filtered_countries = filtered_countries[filtered_countries["area1"].isin(selected_area1)]
    if selected_area2:
        filtered_countries = filtered_countries[filtered_countries["area2"].isin(selected_area2)]
    if selected_countries:
        filtered_countries = filtered_countries[filtered_countries["country"].isin(selected_countries)]

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

    st.caption(f"area1: {', '.join(selected_area1) if selected_area1 else '全て'}")
    st.caption(f"area2: {', '.join(selected_area2) if selected_area2 else '全て'}")
    st.caption(f"country: {', '.join(selected_countries) if selected_countries else '全て'}")
    st.caption(f"elevation: {elevation_min}m ～ {elevation_max}m")

    for month in range(1, 13):
        st.subheader(f"{month}月")

        month_df = merged[
            (merged["month"] == month)
            & (merged["min_temp"] >= min_temp)
            & (merged["max_temp"] <= max_temp)
        ].copy()

        if "avg_temp" in month_df.columns:
            ideal_avg_temp = (min_temp + max_temp) / 2
            month_df["match_score"] = (month_df["avg_temp"] - ideal_avg_temp).abs()
            month_df = month_df.sort_values("match_score", ascending=True)

        month_df = month_df.head(city_count)

        if month_df.empty:
            st.write("該当なし")
            continue

        for _, row in month_df.iterrows():
            with st.container(border=True):
                col1, col2, col3, col4, col5, col6 = st.columns([2.4, 1.6, 1.2, 1.2, 1.2, 1.0])

                city_jp = row.get("city_jp", "")
                city_en = row.get("city_en", "")
                country = row.get("country", "")
                area_text = f"{row.get('area1', '')} > {row.get('area2', '')}"
                min_temp_val = row.get("min_temp", "")
                avg_temp_val = row.get("avg_temp", "")
                max_temp_val = row.get("max_temp", "")
                rain_days = row.get("rain_days", "")
                elevation_val = row.get("elevation", "")

                with col1:
                    if st.button(
                        f"{city_jp} / {city_en}",
                        key=f"detail_{month}_{int(row['city_id'])}"
                    ):
                        st.session_state["selected_city_id"] = int(row["city_id"])
                        st.switch_page("pages/city_detail.py")
                    st.caption(f"{country}｜{area_text}")

                with col2:
                    st.write(f"最低 {min_temp_val}℃")
                    st.write(f"平均 {avg_temp_val}℃")
                    st.write(f"最高 {max_temp_val}℃")

                with col3:
                    st.write("雨日数")
                    st.write(rain_days)

                with col4:
                    st.write("標高")
                    if pd.notna(elevation_val):
                        st.write(f"{int(elevation_val)} m")
                    else:
                        st.write("-")

                with col5:
                    match_score = row.get("match_score", "")
                    if match_score != "":
                        st.write("マッチ度差")
                        st.write(round(float(match_score), 2))

                with col6:
                    st.write("city_id")
                    st.write(int(row["city_id"]))

else:
    st.info("条件を入れて検索すると、月ごとのおすすめ都市を表示します。")