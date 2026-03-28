import html
import re
from urllib.parse import parse_qs, urlparse

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from utils.sheets import load_data, get_city_detail, collect_city_youtube_videos


# =========================
# 共通関数
# =========================
def to_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def to_datetime(value):
    try:
        return pd.to_datetime(value, errors="coerce")
    except Exception:
        return pd.NaT


def format_count(value):
    return f"{to_int(value, 0):,}"


def format_duration(seconds):
    sec = to_int(seconds, 0)
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_published_at(value):
    dt = to_datetime(value)
    if pd.isna(dt):
        return ""
    return dt.strftime("%Y-%m-%d")


def extract_youtube_video_id(url, fallback=None):
    if fallback and str(fallback).strip():
        return str(fallback).strip()

    if not url:
        return None

    url = str(url).strip()

    m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "v" in qs and qs["v"]:
        return qs["v"][0]

    m = re.search(r"/embed/([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)

    return None


def normalize_bool(value, default=True):
    if value is None or value == "":
        return default

    if isinstance(value, bool):
        return value

    s = str(value).strip().lower()
    if s in ["true", "1", "yes", "y"]:
        return True
    if s in ["false", "0", "no", "n"]:
        return False
    return default


def build_youtube_videos_df(data, city_id: int) -> pd.DataFrame:
    if not hasattr(data, "youtube_videos"):
        return pd.DataFrame()

    df = data.youtube_videos.copy()
    if df is None or df.empty:
        return pd.DataFrame()

    df.columns = df.columns.str.strip()

    if "city_id" not in df.columns or "url" not in df.columns:
        return pd.DataFrame()

    df["city_id"] = pd.to_numeric(df["city_id"], errors="coerce")
    city_id_num = pd.to_numeric(pd.Series([city_id]), errors="coerce").iloc[0]
    df = df[df["city_id"] == city_id_num].copy()

    if "default_language" in df.columns:
        df["default_language"] = df["default_language"].astype(str).str.strip().str.lower()
        df = df[df["default_language"] == "ja"].copy()

    if df.empty:
        return df

    if "default_language" in df.columns:
        df["default_language"] = df["default_language"].astype(str).str.strip().str.lower()
        df = df[df["default_language"] == "ja"].copy()

    if df.empty:
        return df

    for col in ["view_count", "like_count", "duration_sec", "comment_count"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "published_at" not in df.columns:
        df["published_at"] = pd.NaT
    df["published_at_dt"] = pd.to_datetime(df["published_at"], errors="coerce")

    if "embeddable" in df.columns:
        df = df[df["embeddable"].apply(lambda x: normalize_bool(x, default=True))].copy()

    if "video_id" not in df.columns:
        df["video_id"] = None

    df["resolved_video_id"] = df.apply(
        lambda row: extract_youtube_video_id(row.get("url"), row.get("video_id")),
        axis=1,
    )
    df = df[df["resolved_video_id"].notna()].copy()

    if df.empty:
        return df

    # 指示通り: like_rate は like_count / view_count
    df["like_rate"] = df.apply(
        lambda row: (row["like_count"] / row["view_count"]) if row["view_count"] > 0 else 0,
        axis=1,
    )

    for col in ["title", "channel_title", "thumbnail_url", "description"]:
        if col not in df.columns:
            df[col] = ""

    return df


def render_video_cards_html(df: pd.DataFrame, height=640):
    cards_html = []

    for _, row in df.iterrows():
        title = html.escape(str(row.get("title", "") or "Untitled"))
        channel_title = html.escape(str(row.get("channel_title", "") or ""))
        video_id = str(row.get("resolved_video_id", "") or "").strip()
        published_at = format_published_at(row.get("published_at_dt"))
        duration = format_duration(row.get("duration_sec"))
        view_count = format_count(row.get("view_count"))
        like_count = format_count(row.get("like_count"))
        like_rate = f"{row.get('like_rate', 0) * 100:.2f}%"

        if not video_id:
            continue

        card = f"""
        <div class="yt-card">
            <div class="yt-player-wrap">
                <iframe
                    class="yt-player"
                    src="https://www.youtube.com/embed/{video_id}"
                    title="{title}"
                    frameborder="0"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                    allowfullscreen>
                </iframe>
            </div>
            <div class="yt-meta">
                <div class="yt-title">{title}</div>
                <div class="yt-channel">{channel_title}</div>
                <div class="yt-stats">
                    <span>再生 {view_count}</span>
                    <span>👍 {like_count}</span>
                    <span>Like率 {like_rate}</span>
                </div>
                <div class="yt-stats">
                    <span>公開日 {published_at}</span>
                    <span>長さ {duration}</span>
                </div>
            </div>
        </div>
        """
        cards_html.append(card)

    html_block = f"""
    <style>
      .yt-rail {{
        display: flex;
        gap: 16px;
        overflow-x: auto;
        padding: 4px 4px 12px 4px;
        scroll-snap-type: x proximity;
      }}
      .yt-card {{
        min-width: 380px;
        max-width: 380px;
        width: 380px;
        border: 1px solid rgba(120, 120, 120, 0.25);
        border-radius: 14px;
        overflow: hidden;
        background: white;
        scroll-snap-align: start;
        box-shadow: 0 2px 10px rgba(0,0,0,0.06);
      }}
      .yt-player-wrap {{
        width: 100%;
        aspect-ratio: 16 / 9;
        background: #000;
      }}
      .yt-player {{
        width: 100%;
        height: 100%;
      }}
      .yt-meta {{
        padding: 12px;
      }}
      .yt-title {{
        font-size: 15px;
        font-weight: 700;
        line-height: 1.4;
        margin-bottom: 6px;
        color: #111;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }}
      .yt-channel {{
        font-size: 13px;
        color: #666;
        margin-bottom: 8px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      .yt-stats {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px 12px;
        font-size: 12px;
        color: #444;
        margin-bottom: 6px;
      }}
      @media (max-width: 768px) {{
        .yt-card {{
          min-width: 92vw;
          max-width: 92vw;
          width: 92vw;
        }}
      }}
    </style>

    <div class="yt-rail">
      {''.join(cards_html)}
    </div>
    """
    components.html(html_block, height=height, scrolling=False)


#追加
def render_main_video_player(video_id: str, title: str = ""):
    if not video_id:
        return

    import html
    import streamlit.components.v1 as components

    title_escaped = html.escape(title or "YouTube video")

    iframe = f"""
    <div style="width: 100%; max-width: 960px; margin: 0 auto 16px auto;">
        <div style="position: relative; width: 100%; aspect-ratio: 16 / 9; background: #000; border-radius: 12px; overflow: hidden;">
            <iframe
                src="https://www.youtube.com/embed/{video_id}?autoplay=1"
                title="{title_escaped}"
                frameborder="0"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                allowfullscreen
                style="width:100%; height:100%;">
            </iframe>
        </div>
    </div>
    """
    components.html(iframe, height=580)

# =========================
# 画面本体
# =========================
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
    # st.text_input("国名", value=str(detail.get("country", "")), disabled=True)
    # st.text_input("地域", value=f"{detail.get('area1', '')} > {detail.get('area2', '')}", disabled=True)
    # st.text_input("都市名（英語表記）", value=str(detail.get("city_en", "")), disabled=True)
    # st.text_input("都市名（日本語表記）", value=str(detail.get("city_jp", "")), disabled=True)
    st.text_input("人口", value=str(detail.get("population", "")), disabled=True)
    st.text_input("タイムゾーン", value=str(detail.get("timezone_offset", "")), disabled=True)
    st.text_input("通貨", value=str(detail.get("currency_code", "")), disabled=True)
    st.text_input("宗教", value=str(detail.get("religion", "")), disabled=True)

with right:
    # st.text_input("緯度", value=str(detail.get("lat", "")), disabled=True)
    # st.text_input("経度", value=str(detail.get("lon", "")), disabled=True)
    st.text_input("標高", value=str(detail.get("elevation", "")), disabled=True)
    st.text_input("コスト指数", value=str(detail.get("cost_index", "")), disabled=True)
    st.text_input("為替", value=str(detail.get("exchange_rate", "")), disabled=True)
    st.text_area("空港", value=str(detail.get("airports", "")), disabled=True, height=100)
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
    components.html(map_iframe, height=460)
else:
    st.info("地図情報がありません。")

# ---------------------------
# 動画情報
# ---------------------------
st.markdown("---")
st.markdown("### 動画情報")

initial_fetch_limit = 5
more_fetch_limit = 15
visible_default_count = 5
session_city_key = f"youtube_visible_count_{int(selected_city_id)}"
status_city_key = f"youtube_fetch_status_{int(selected_city_id)}"

if session_city_key not in st.session_state:
    st.session_state[session_city_key] = visible_default_count

videos_df = build_youtube_videos_df(data, int(selected_city_id))

import os

api_key = ""
api_key_source = "none"
try:
    api_key = str(st.secrets["YOUTUBE_API_KEY"]).strip()
    api_key_source = "st.secrets[YOUTUBE_API_KEY]"
except Exception:
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if api_key:
        api_key_source = "os.environ[YOUTUBE_API_KEY]"

with st.expander("YouTubeデバッグ情報", expanded=False):
    try:
        secret_keys = list(st.secrets.keys())
    except Exception:
        secret_keys = []
    st.write({
        "city_id": int(selected_city_id),
        "api_key_exists": bool(api_key),
        "api_key_prefix": api_key[:8] + "..." if api_key else None,
        "api_key_source": api_key_source,
        "secret_keys": secret_keys,
        "existing_video_rows": int(len(videos_df)),
    })

if videos_df.empty:
    try:
        with st.spinner("関連動画を検索中…"):
            result = collect_city_youtube_videos(
                city_id=int(selected_city_id),
                city_detail=detail,
                data=data,
                api_key=api_key,
                max_total_videos=initial_fetch_limit,
                max_queries=5,
                language_code="ja",
            )
        st.session_state[status_city_key] = {
            "added_videos": int(result.get("added_videos", 0) or 0),
            "debug": result.get("debug", []),
        }
        with st.expander("YouTube自動取得デバッグ", expanded=True):
            st.write(result.get("debug", []))
        st.rerun()
    except Exception as e:
        st.error(f"動画検索時に一部取得できなかったクエリがあります: {e}")
        with st.expander("YouTube自動取得エラー詳細", expanded=True):
            st.exception(e)
            st.write({"city_id": int(selected_city_id), "api_key_exists": bool(api_key), "api_key_prefix": api_key[:8] + "..." if api_key else None})
else:
    fetch_status = st.session_state.get(status_city_key, {})
    debug_messages = fetch_status.get("debug", [])
    if debug_messages:
        with st.expander("前回取得デバッグログ", expanded=False):
            st.write(debug_messages)
    added_videos = int(fetch_status.get("added_videos", 0) or 0)
    if added_videos > 0:
        st.success(f"関連動画を {added_videos} 件取得しました。")
        st.session_state.pop(status_city_key, None)

    sort_col1, sort_col2, sort_col3 = st.columns([2, 1, 1])

    sort_options = {
        "view_count": "view_count",
        "like_count": "like_count",
        "like_rate": "like_rate",
        "published_at": "published_at_dt",
        "duration_sec": "duration_sec",
    }

    with sort_col1:
        sort_label = st.selectbox("表示順", options=list(sort_options.keys()), index=2)

    with sort_col2:
        sort_order = st.radio("並び順", options=["降順", "昇順"], index=0, horizontal=True)

    with sort_col3:
        st.metric("表示件数", f"{min(len(videos_df), st.session_state[session_city_key])}件")

    sort_key = sort_options[sort_label]
    ascending = sort_order == "昇順"

    videos_df = videos_df.sort_values(
        by=sort_key,
        ascending=ascending,
        na_position="last",
    ).reset_index(drop=True)

    visible_count = min(len(videos_df), st.session_state[session_city_key])
    visible_videos_df = videos_df.head(visible_count).reset_index(drop=True)

    if visible_videos_df.empty:
        st.info("この都市に紐づく動画はありません。")
    else:
        current_ids = set(visible_videos_df["resolved_video_id"].astype(str).tolist())
        if (
            "current_video_id" not in st.session_state
            or st.session_state["current_video_id"] not in current_ids
        ):
            st.session_state["current_video_id"] = visible_videos_df.iloc[0]["resolved_video_id"]
            st.session_state["current_video_title"] = visible_videos_df.iloc[0].get("title", "")

        st.caption("下の一覧から動画を選ぶと、この画面内のプレーヤーで再生できます。")

        render_main_video_player(
            st.session_state["current_video_id"],
            st.session_state.get("current_video_title", "")
        )

        st.markdown("#### 動画一覧")
        row_cols = st.columns(min(3, len(visible_videos_df)))

        for idx, row in visible_videos_df.iterrows():
            col = row_cols[idx % len(row_cols)]
            with col:
                thumb = row.get("thumbnail_url", "")
                if thumb:
                    st.image(thumb, use_container_width=True)
                st.markdown(f"**{row.get('title', 'Untitled')}**")
                st.caption(
                    f"再生 {format_count(row.get('view_count'))} / "
                    f"👍 {format_count(row.get('like_count'))} / "
                    f"{format_published_at(row.get('published_at_dt'))}"
                )
                if st.button("この動画を再生", key=f"play_{idx}"):
                    st.session_state["current_video_id"] = row["resolved_video_id"]
                    st.session_state["current_video_title"] = row.get("title", "")
                    st.rerun()

    more_col1, more_col2 = st.columns([1, 3])
    with more_col1:
        if st.button("追加取得してもっと見る", key=f"more_fetch_{int(selected_city_id)}"):
            try:
                with st.spinner("関連動画を追加で検索中…"):
                    result = collect_city_youtube_videos(
                        city_id=int(selected_city_id),
                        city_detail=detail,
                        data=data,
                        api_key=api_key,
                        max_total_videos=more_fetch_limit,
                        max_queries=5,
                        language_code="ja",
                    )
                st.session_state[session_city_key] = more_fetch_limit
                st.session_state[status_city_key] = {
                    "added_videos": int(result.get("added_videos", 0) or 0),
                    "debug": result.get("debug", []),
                }
                with st.expander("YouTube追加取得デバッグ", expanded=True):
                    st.write(result.get("debug", []))
                st.rerun()
            except Exception as e:
                st.error(f"追加取得に失敗しました: {e}")
                with st.expander("YouTube追加取得エラー詳細", expanded=True):
                    st.exception(e)
                    st.write({"city_id": int(selected_city_id), "api_key_exists": bool(api_key), "api_key_prefix": api_key[:8] + "..." if api_key else None})
    with more_col2:
        if len(videos_df) > visible_count and st.button("既存の動画をもっと表示", key=f"show_more_{int(selected_city_id)}"):
            st.session_state[session_city_key] = min(len(videos_df), more_fetch_limit)
            st.rerun()

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

