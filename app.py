import streamlit as st
import pandas as pd

# -----------------------------
# Google Spreadsheet設定
# -----------------------------
SHEET_ID = "1L4qsWHhucIORTjSC9MF5YtuOYk0NMQKFiI_Kzt1anWE"


def load_sheet(sheet_name: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    return pd.read_csv(url)


# -----------------------------
# データ読み込み
# -----------------------------
@st.cache_data
def load_data():
    countries = load_sheet("Countries")
    cities = load_sheet("Cities")
    climate = load_sheet("Climate")

    countries.columns = countries.columns.str.strip()
    cities.columns = cities.columns.str.strip()
    climate.columns = climate.columns.str.strip()

    # 文字列の余計な空白を除去
    for col in ["country", "area1", "area2", "city_jp", "city_en"]:
        if col in countries.columns:
            countries[col] = countries[col].astype(str).str.strip()
        if col in cities.columns:
            cities[col] = cities[col].astype(str).str.strip()

    # 数値型をそろえる
    if "country_id" in countries.columns:
        countries["country_id"] = pd.to_numeric(countries["country_id"], errors="coerce")
    if "country_id" in cities.columns:
        cities["country_id"] = pd.to_numeric(cities["country_id"], errors="coerce")
    if "city_id" in cities.columns:
        cities["city_id"] = pd.to_numeric(cities["city_id"], errors="coerce")
    if "city_id" in climate.columns:
        climate["city_id"] = pd.to_numeric(climate["city_id"], errors="coerce")
    if "month" in climate.columns:
        climate["month"] = pd.to_numeric(climate["month"], errors="coerce")

    for col in ["min_temp", "avg_temp", "max_temp", "humidity", "precip_mm", "rain_days"]:
        if col in climate.columns:
            climate[col] = pd.to_numeric(climate[col], errors="coerce")

    if "flag" in countries.columns:
        countries["flag"] = pd.to_numeric(countries["flag"], errors="coerce")

    return countries, cities, climate


countries, cities, climate = load_data()

# ---------------------------------
# flag=1 の国だけ候補にする
# ---------------------------------
countries_flag1 = countries[countries["flag"] == 1].copy()

# ---------------------------------
# セレクト候補作成
# ---------------------------------
area1_options = sorted(
    [x for x in countries_flag1["area1"].dropna().astype(str).str.strip().unique().tolist() if x and x != "nan"]
)

# 初期値用
default_area1 = area1_options

# -----------------------------
# UI
# -----------------------------
st.title("🌏 年間居住都市レコメンド")

with st.form("search_form"):
    st.subheader("検索条件")

    # area1
    selected_area1 = st.multiselect(
        "対象エリア1（Countries.area1）",
        options=area1_options,
        default=default_area1
    )

    # area1 に応じた area2 候補
    area2_base = countries_flag1.copy()
    if selected_area1:
        area2_base = area2_base[area2_base["area1"].isin(selected_area1)]

    area2_options = sorted(
        [x for x in area2_base["area2"].dropna().astype(str).str.strip().unique().tolist() if x and x != "nan"]
    )

    selected_area2 = st.multiselect(
        "対象エリア2（Countries.area2）",
        options=area2_options,
        default=area2_options
    )

    # area1 + area2 に応じた国候補（flag=1のみ）
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
        default=country_options
    )

    min_temp = st.slider(
        "最低気温（下限）",
        -10,
        35,
        15
    )

    max_temp = st.slider(
        "最高気温（上限）",
        10,
        45,
        30
    )

    city_count = st.slider(
        "各月の表示都市数",
        1,
        20,
        5
    )

    submitted = st.form_submit_button("検索")

# -----------------------------
# 検索実行
# -----------------------------
if submitted:
    filtered_countries = countries_flag1.copy()

    if selected_area1:
        filtered_countries = filtered_countries[
            filtered_countries["area1"].isin(selected_area1)
        ]

    if selected_area2:
        filtered_countries = filtered_countries[
            filtered_countries["area2"].isin(selected_area2)
        ]

    if selected_countries:
        filtered_countries = filtered_countries[
            filtered_countries["country"].isin(selected_countries)
        ]

    if filtered_countries.empty:
        st.warning("条件に合う国がありません。")
        st.stop()

    target_country_ids = filtered_countries["country_id"].dropna().unique().tolist()

    filtered_cities = cities[
        cities["country_id"].isin(target_country_ids)
    ].copy()

    if filtered_cities.empty:
        st.warning("条件に合う都市がありません。")
        st.stop()

    merged = climate.merge(
        filtered_cities,
        on="city_id",
        how="inner"
    ).merge(
        filtered_countries,
        on="country_id",
        how="left"
    )

    selected_area1_text = ", ".join(selected_area1) if selected_area1 else "全て"
    selected_area2_text = ", ".join(selected_area2) if selected_area2 else "全て"
    selected_country_text = ", ".join(selected_countries) if selected_countries else "全て"

    st.caption(f"area1: {selected_area1_text}")
    st.caption(f"area2: {selected_area2_text}")
    st.caption(f"country: {selected_country_text}")

    for month in range(1, 13):
        st.subheader(f"{month}月")

        month_df = merged[
            (merged["month"] == month) &
            (merged["min_temp"] >= min_temp) &
            (merged["max_temp"] <= max_temp)
        ].copy()

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
                    "area1",
                    "area2",
                    "country",
                    "city_jp",
                    "city_en",
                    "min_temp",
                    "avg_temp",
                    "max_temp",
                    "rain_days"
                ] if c in month_df.columns
            ]

            st.dataframe(
                month_df[display_cols],
                # use_container_width=True
                width='content'
            )