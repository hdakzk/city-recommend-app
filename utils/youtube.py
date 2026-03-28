from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
from collections import OrderedDict
import re
import time
import requests
import os

from utils.sheets import (
    load_data,
    _append_rows,   # sheets側の書き込み関数をそのまま利用
    SheetsWriteError,
)

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


# =========================
# 基本ユーティリティ
# =========================

def _now_string() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _int_or_none(value):
    try:
        return int(value)
    except:
        return None


# =========================
# APIキー取得
# =========================

def get_youtube_api_key() -> Optional[str]:
    import streamlit as st

    try:
        if hasattr(st, "secrets"):
            return st.secrets.get("YOUTUBE_API_KEY")
    except:
        pass

    return os.getenv("YOUTUBE_API_KEY")


# =========================
# API呼び出し
# =========================

def _youtube_get(endpoint: str, params: dict, retries=5):
    url = f"{YOUTUBE_API_BASE}/{endpoint}"

    backoff = 1.0
    for i in range(retries):
        try:
            res = requests.get(url, params=params, timeout=30)

            if res.status_code == 200:
                return res.json()

            if res.status_code in [429, 500, 502, 503]:
                time.sleep(backoff)
                backoff *= 2
                continue

            raise Exception(res.text)

        except Exception as e:
            if i == retries - 1:
                raise e
            time.sleep(backoff)
            backoff *= 2


# =========================
# クエリ生成（国名込み）
# =========================

def generate_queries(city_detail: Dict, max_queries=5) -> List[str]:
    city = str(city_detail.get("city_jp", "")).strip()
    country = str(city_detail.get("country", "")).strip()

    queries = [
        f"{country} {city} 旅行",
        f"{country} {city} 観光",
        f"{country} {city} vlog",
        f"{country} {city} 街歩き",
        f"{country} {city} 観光ガイド",
    ]

    return queries[:max_queries]


# =========================
# 動画検索
# =========================

def search_videos(api_key: str, query: str, max_results=5):
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
        "key": api_key,
        "videoEmbeddable": "true",
    }

    data = _youtube_get("search", params)

    results = []
    for i, item in enumerate(data.get("items", []), 1):
        vid = item["id"].get("videoId")
        if vid:
            results.append({
                "video_id": vid,
                "rank": i
            })

    return results


# =========================
# 動画詳細取得
# =========================

def fetch_video_details(api_key: str, video_ids: List[str]):
    if not video_ids:
        return {}

    params = {
        "part": "snippet,statistics,contentDetails,status",
        "id": ",".join(video_ids),
        "key": api_key,
    }

    data = _youtube_get("videos", params)

    result = {}
    for item in data.get("items", []):
        result[item["id"]] = item

    return result


# =========================
# メイン処理
# =========================

def collect_city_youtube_videos(city_id: int, city_detail: Dict):
    api_key = get_youtube_api_key()
    if not api_key:
        raise SheetsWriteError("APIキーがない")

    base_data = load_data()

    queries = generate_queries(city_detail)

    query_rows = []
    now = _now_string()

    # クエリ保存
    for i, q in enumerate(queries):
        query_rows.append({
            "id": i + 1,
            "city_id": city_id,
            "query_text": q,
            "created_at": now,
            "updated_at": now,
        })

    _append_rows("Queries_content", query_rows)

    # 検索
    all_hits = {}
    video_ids = set()

    for q in query_rows:
        hits = search_videos(api_key, q["query_text"])

        all_hits[q["id"]] = hits

        for h in hits:
            video_ids.add(h["video_id"])

    # 詳細取得
    details = fetch_video_details(api_key, list(video_ids))

    # 動画保存
    rows = []
    for vid, item in details.items():
        snippet = item["snippet"]
        stats = item.get("statistics", {})

        rows.append({
            "city_id": city_id,
            "video_id": vid,
            "title": snippet.get("title"),
            "url": f"https://youtube.com/watch?v={vid}",
            "view_count": _int_or_none(stats.get("viewCount")),
            "like_count": _int_or_none(stats.get("likeCount")),
            "created_at": now,
        })

    _append_rows("Youtube_videos", rows)

    return len(rows)