import streamlit as st

from utils.sheets import load_data

st.title("🌏 年間居住都市レコメンド")

data = load_data()
countries = data.countries.copy()
cities = data.cities.copy()
climate = data.climate.copy()

countries_flag1 = countries[countries["flag"] == 1].copy()

area1_options = sorted(
    [x for x in countries_flag1["area1"].dropna().astype(str).str.strip().unique().tolist() if x and x != "nan"]
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
        [x for x in area2_base["area2"].dropna().astype(str).str.strip().unique().tolist() if x and x != "nan"]
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
        [x for x in country_base["country"].dropna().astype(str).str.strip().unique().tolist() if x and x != "nan"]
    )

    selected_countries = st.multiselect(
        "対象国（Countries.country / flag=1のみ）",
        options=country_options,
        default=country_options,
    )

    min_temp = st.slider("最低気温（下限）", -10, 35, 15)
    max_temp = st.slider("最高気温（上限）", 10, 45, 30)
    city_count = st.slider("各月の表示都市数", 1, 30, 5)

    submitted = st.form_submit_button("検索")

if submitted:
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

    merged = climate.merge(filtered_cities, on="city_id", how="inner").merge(filtered_countries, on="country_id", how="left")

    st.caption(f"area1: {', '.join(selected_area1) if selected_area1 else '全て'}")
    st.caption(f"area2: {', '.join(selected_area2) if selected_area2 else '全て'}")
    st.caption(f"country: {', '.join(selected_countries) if selected_countries else '全て'}")

    for month in range(1, 13):
        st.subheader(f"{month}月")

        month_df = merged[(merged["month"] == month) & (merged["min_temp"] >= min_temp) & (merged["max_temp"] <= max_temp)].copy()

        if "avg_temp" in month_df.columns:
            ideal_avg_temp = (min_temp + max_temp) / 2
            month_df["match_score"] = (month_df["avg_temp"] - ideal_avg_temp).abs()
            month_df = month_df.sort_values("match_score", ascending=True)

        month_df = month_df.head(city_count)

        if month_df.empty:
            st.write("該当なし")
        else:
            display_cols = [
                c for c in [
                    #"area1",
                    #"area2",
                    "country",
                    "city_jp",
                    "city_en",
                    "min_temp",
                    "avg_temp",
                    "max_temp",
                    #"rain_days",
                    "precip_mm",
                ]
                if c in month_df.columns
            ]
            #st.dataframe(month_df[display_cols], width='content', hide_index=True)
            from st_aggrid import AgGrid

            AgGrid(month_df[display_cols])
            
else:
    st.info("条件を入れて検索すると、月ごとのおすすめ都市を表示します。")
