import streamlit as st
from utils.sheets import load_data, get_city_detail

st.title("都市詳細")

selected_city_id = st.session_state.get("selected_city_id")

if not selected_city_id:
    st.warning("都市が選択されていません。候補都市一覧から選択してください。")
    if st.button("候補都市一覧へ戻る"):
        st.switch_page("pages/city_recommend.py")
    st.stop()

data = load_data()

try:
    detail = get_city_detail(int(selected_city_id), data)
except Exception as e:
    st.error(f"都市詳細の取得に失敗しました: {e}")
    if st.button("候補都市一覧へ戻る"):
        st.switch_page("pages/city_recommend.py")
    st.stop()

top_left, top_right = st.columns([4, 1])

with top_left:
    st.subheader(f"{detail.get('city_jp', '')} / {detail.get('city_en', '')}")
    st.caption(f"{detail.get('country', '')}｜{detail.get('area1', '')} > {detail.get('area2', '')}")

with top_right:
    if st.button("一覧へ戻る"):
        st.switch_page("pages/city_recommend.py")

st.markdown("### 基本情報")

left, right = st.columns(2)

with left:
    st.text_input("国名", value=str(detail.get("country", "")), disabled=True)
    st.text_input("地域", value=f"{detail.get('area1', '')} > {detail.get('area2', '')}", disabled=True)
    st.text_input("都市名（英語表記）", value=str(detail.get("city_en", "")), disabled=True)
    st.text_input("都市名（日本語表記）", value=str(detail.get("city_jp", "")), disabled=True)
    #st.text_input("主要言語", value=str(detail.get("language", "")), disabled=True)
    st.text_input("通貨", value=str(detail.get("currency_code", "")), disabled=True)
    st.text_input("為替", value=str(detail.get("exchange_rate", "")), disabled=True)
    st.text_input("宗教", value=str(detail.get("religion", "")), disabled=True)

with right:
    st.text_input("緯度", value=str(detail.get("lat", "")), disabled=True)
    st.text_input("経度", value=str(detail.get("lon", "")), disabled=True)
    st.text_area("空港", value=str(detail.get("airports", "")), disabled=True, height=100)
    st.text_input("人口", value=str(detail.get("population", "")), disabled=True)
    st.text_input("タイムゾーン", value=str(detail.get("timezone_offset", "")), disabled=True)
    st.text_input("標高", value=str(detail.get("elevation", "")), disabled=True)
    st.text_input("コスト指数", value=str(detail.get("cost_index", "")), disabled=True)

# ---------------------------
# 地図情報
# ---------------------------
st.markdown("---")
st.markdown("### 地図情報")

lat = detail.get("lat")
lon = detail.get("lon")

if lat not in ["", None] and lon not in ["", None]:
    google_map_url = f"https://www.google.com/maps?q={lat},{lon}"
    st.link_button("Google Mapで開く", google_map_url)

    # iframe埋め込み
    map_iframe = f"""
    <iframe
        src="https://www.google.com/maps?q={lat},{lon}&z=12&output=embed"
        width="100%"
        height="450"
        style="border:0;"
        allowfullscreen=""
        loading="lazy"
        referrerpolicy="no-referrer-when-downgrade">
    </iframe>
    """
    st.components.v1.html(map_iframe, height=460)
else:
    st.info("地図情報がありません。")

# ---------------------------
# 動画情報（ハードコード）
# ---------------------------
st.markdown("---")
st.markdown("### 動画情報")

youtube_urls = [
    "https://youtu.be/7JmpD9eHok0?si=CTmrXB94iZw3J28T",
    "https://youtu.be/qwC-Qyu1bhg?si=yMJTqtChjBH9ZFXW",
]

video_cols = st.columns(2)

for i, url in enumerate(youtube_urls):
    with video_cols[i % 2]:
        st.video(url)
        st.caption(url)

# ---------------------------
# ブログ情報（ハードコード）
# ---------------------------
st.markdown("---")
st.markdown("### ブログ情報")

blog_links = [
    {
        "title": "4travel - サパ旅行記一覧",
        "url": "https://4travel.jp/os_travelogue_list-city-sapa.html",
        "thumbnail": "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?w=1200&q=80",
    },
    {
        "title": "Amebaブログ - サパ旅行記事",
        "url": "https://ameblo.jp/kimagure0toya/entry-12873100915.html",
        "thumbnail": "https://images.unsplash.com/photo-1488646953014-85cb44e25828?w=1200&q=80",
    },
]

blog_cols = st.columns(2)

for i, blog in enumerate(blog_links):
    with blog_cols[i % 2]:
        st.image(blog["thumbnail"], use_container_width=True)
        st.markdown(f"**{blog['title']}**")
        st.link_button("ブログを開く", blog["url"])

# ---------------------------
# 今後追加予定
# ---------------------------
st.markdown("---")
st.markdown("### 今後追加予定")
c1, c2, c3, c4, c5 = st.columns(5)
c1.info("気温")
c2.info("雨季乾季")
c3.info("物価")
c4.info("空気")
c5.info("水")