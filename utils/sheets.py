from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from collections import OrderedDict
import os
import re
import time

import pandas as pd
import requests
import streamlit as st

SHEET_ID = "1L4qsWHhucIORTjSC9MF5YtuOYk0NMQKFiI_Kzt1anWE"
PAYMENT_METHODS = ["現金", "クレジットカード", "電子決済", "WISE"]
FRANKFURTER_BASE_URL = "https://api.frankfurter.dev/v2"
JST = "Asia/Tokyo"


class SheetsWriteError(RuntimeError):
    pass


@dataclass
class AppData:
    countries: pd.DataFrame
    cities: pd.DataFrame
    climate: pd.DataFrame
    expenses: pd.DataFrame
    usage_categories: pd.DataFrame
    tax_categories: pd.DataFrame
    city_airports: pd.DataFrame
    airports: pd.DataFrame
    youtube_videos: pd.DataFrame
    queries_content: pd.DataFrame
    query_hits: pd.DataFrame


def _normalize_text_columns(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    for col in columns:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
            df.loc[df[col].isin(["nan", "None"]), col] = ""
    return df


def _normalize_numeric_column(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_public_sheet(sheet_name: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    return pd.read_csv(url)


def load_public_sheet_safe(sheet_name: str) -> pd.DataFrame:
    try:
        return load_public_sheet(sheet_name)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_data() -> AppData:
    countries = load_public_sheet("Countries")
    cities = load_public_sheet("Cities")
    climate = load_public_sheet("Climate")
    expenses = load_public_sheet("Expenses")
    usage_categories = load_public_sheet("Usage_categories")
    tax_categories = load_public_sheet("Tax_categories")
    city_airports = load_public_sheet("City_airports")
    airports = load_public_sheet("Airport")
    youtube_videos = load_public_sheet("Youtube_videos")
    queries_content = load_public_sheet_safe("Queries_content")
    query_hits = load_public_sheet_safe("Query_hits")

    for df in [
        countries,
        cities,
        climate,
        expenses,
        usage_categories,
        tax_categories,
        city_airports,
        airports,
        youtube_videos,
        queries_content,
        query_hits,
    ]:
        df.columns = df.columns.str.strip()

    countries = _normalize_text_columns(
        countries,
        ["country", "country_en", "area1", "area2", "currency_code", "religion"]
    )
    cities = _normalize_text_columns(
        cities,
        ["city_jp", "city_en", "timezone_offset"]
    )
    climate = _normalize_text_columns(climate, [])
    expenses = _normalize_text_columns(
        expenses,
        ["payment_date", "currency_code", "payment_method", "description", "created_at", "updated_at"]
    )
    usage_categories = _normalize_text_columns(usage_categories, ["name_ja", "name_en"])
    tax_categories = _normalize_text_columns(tax_categories, ["name_ja", "name_en"])
    city_airports = _normalize_text_columns(city_airports, [])
    airports = _normalize_text_columns(
        airports,
        ["name", "name_ja", "city", "city_ja", "country", "country_ja", "iata_code", "icao_code", "timezone_name"]
    )
    youtube_videos = _normalize_text_columns(
        youtube_videos,
        [
            "video_id",
            "title",
            "url",
            "channel_title",
            "thumbnail_url",
            "description",
            "published_at",
            "privacy_status",
            "upload_status",
            "license",
            "matched_status",
            "default_language",
        ]
    )
    queries_content = _normalize_text_columns(
        queries_content,
        ["query_text", "language_code", "created_at", "updated_at"]
    )
    query_hits = _normalize_text_columns(
        query_hits,
        ["video_id", "searched_at", "matched_status", "created_at", "updated_at"]
    )

    for col in ["country_id", "flag"]:
        countries = _normalize_numeric_column(countries, col)

    for col in ["country_id", "city_id", "lat", "lon", "population", "elevation", "cost_index"]:
        cities = _normalize_numeric_column(cities, col)

    for col in ["city_id", "month", "min_temp", "avg_temp", "max_temp", "humidity", "precip_mm", "rain_days"]:
        climate = _normalize_numeric_column(climate, col)

    for col in ["id", "amount", "exchange_rate", "amount_base", "usage_categories_id", "tax_categories_id"]:
        expenses = _normalize_numeric_column(expenses, col)

    for col in ["id", "sort_order", "is_enabled"]:
        usage_categories = _normalize_numeric_column(usage_categories, col)

    tax_categories = _normalize_numeric_column(tax_categories, "id")
    tax_categories = _normalize_numeric_column(tax_categories, "sort_order")
    tax_categories = _normalize_numeric_column(tax_categories, "is_enabled")

    for col in ["city_id", "airport_id"]:
        city_airports = _normalize_numeric_column(city_airports, col)

    for col in ["airport_id", "latitude", "longitude", "altitude_ft", "timezone_offset", "priority"]:
        airports = _normalize_numeric_column(airports, col)

    for col in [
        "city_id",
        "view_count",
        "like_count",
        "duration_sec",
        "comment_count",
        "like_rate",
    ]:
        youtube_videos = _normalize_numeric_column(youtube_videos, col)

    for col in ["id", "city_id", "priority", "is_active"]:
        queries_content = _normalize_numeric_column(queries_content, col)

    for col in ["id", "city_id", "query_id", "result_rank"]:
        query_hits = _normalize_numeric_column(query_hits, col)

    return AppData(
        countries=countries,
        cities=cities,
        climate=climate,
        expenses=expenses,
        usage_categories=usage_categories,
        tax_categories=tax_categories,
        city_airports=city_airports,
        airports=airports,
        youtube_videos=youtube_videos,
        queries_content=queries_content,
        query_hits=query_hits,
    )



YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeApiError(RuntimeError):
    pass


def _debug_log(debug: List[str], message: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    debug.append(line)


def _normalize_header(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _int_or_none(value: object) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _now_string() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def get_youtube_api_key() -> Optional[str]:
    try:
        if hasattr(st, "secrets"):
            value = st.secrets.get("YOUTUBE_API_KEY", "")
            if value:
                return str(value).strip()
            youtube_section = st.secrets.get("youtube", {})
            if youtube_section:
                nested = youtube_section.get("api_key", "")
                if nested:
                    return str(nested).strip()
    except Exception:
        pass

    value = os.getenv("YOUTUBE_API_KEY", "").strip()
    return value or None


def _youtube_get(endpoint: str, params: dict, session: requests.Session, retries: int = 5) -> dict:
    url = f"{YOUTUBE_API_BASE}/{endpoint}"
    backoff = 1.0
    last_error = None

    for attempt in range(retries):
        try:
            response = session.get(url, params=params, timeout=60)
        except requests.RequestException as exc:
            last_error = exc
            if attempt == retries - 1:
                break
            time.sleep(backoff)
            backoff *= 2
            continue

        if response.status_code in {429, 500, 502, 503, 504}:
            last_error = response.text
            if attempt == retries - 1:
                break
            time.sleep(backoff)
            backoff *= 2
            continue

        if not response.ok:
            try:
                payload = response.json()
            except Exception:
                payload = response.text
            raise YouTubeApiError(f"HTTP {response.status_code}: {payload}")

        return response.json()

    raise YouTubeApiError(f"YouTube API request failed after retries: {last_error}")


def _pick_thumbnail_url(thumbnails: Optional[dict]) -> Optional[str]:
    if not thumbnails:
        return None
    for key in ("maxres", "standard", "high", "medium", "default"):
        entry = thumbnails.get(key)
        if entry and entry.get("url"):
            return entry["url"]
    for entry in thumbnails.values():
        if isinstance(entry, dict) and entry.get("url"):
            return entry["url"]
    return None


def _parse_iso8601_duration_to_seconds(duration: Optional[str]) -> Optional[int]:
    if not duration:
        return None
    pattern = re.compile(r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$")
    match = pattern.match(duration)
    if not match:
        return None
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _generate_youtube_query_texts(city_detail: Dict[str, Any], max_queries: int = 5) -> List[str]:
    city_jp = str(city_detail.get("city_jp", "") or "").strip()
    country = str(city_detail.get("country", "") or "").strip()
    candidates = [
        f"{city_jp} 旅行",
        f"{city_jp} 観光",
        f"{city_jp} 街歩き",
        f"{city_jp} 観光ガイド",
        f"{country} {city_jp} 旅行".strip(),
    ]
    seen = set()
    queries: List[str] = []
    for query in candidates:
        cleaned = re.sub(r"\s+", " ", query).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        queries.append(cleaned)
        if len(queries) >= max_queries:
            break
    return queries


def _search_videos_for_query(*, api_key: str, session: requests.Session, query_text: str, language_code: str, max_results: int, debug: Optional[List[str]] = None) -> List[dict]:
    if debug is not None:
        _debug_log(debug, f"_search_videos_for_query start query={query_text!r} api_key_prefix={(api_key[:8] + '...') if api_key else None}")
    params = {
        "part": "snippet",
        "q": query_text,
        "type": "video",
        "maxResults": min(50, max_results),
        "order": "relevance",
        "relevanceLanguage": language_code,
        "videoEmbeddable": "true",
        "key": api_key,
    }
    payload = _youtube_get("search", params, session)
    if debug is not None:
        _debug_log(debug, f"search response items={len(payload.get('items', []))} for query={query_text!r}")
    hits = []
    for index, item in enumerate(payload.get("items", []), start=1):
        video_id = ((item.get("id") or {}).get("videoId"))
        if not video_id:
            continue
        hits.append({"video_id": video_id, "rank": index})
        if len(hits) >= max_results:
            break
    return hits


def _fetch_video_details(api_key: str, session: requests.Session, video_ids: List[str], debug: Optional[List[str]] = None) -> Dict[str, dict]:
    if not video_ids:
        if debug is not None:
            _debug_log(debug, "_fetch_video_details skipped because video_ids is empty")
        return {}
    details = {}
    for start in range(0, len(video_ids), 50):
        batch_ids = video_ids[start:start + 50]
        params = {
            "part": "snippet,contentDetails,statistics,status",
            "id": ",".join(batch_ids),
            "key": api_key,
        }
        if debug is not None:
            _debug_log(debug, f"_fetch_video_details request batch_size={len(batch_ids)} api_key_prefix={(api_key[:8] + '...') if api_key else None}")
        payload = _youtube_get("videos", params, session)
        if debug is not None:
            _debug_log(debug, f"_fetch_video_details response items={len(payload.get('items', []))}")
        for item in payload.get("items", []):
            video_id = item.get("id")
            if video_id:
                details[video_id] = item
    return details


def _next_sheet_id(df: pd.DataFrame) -> int:
    if df is None or df.empty or "id" not in df.columns:
        return 1
    series = pd.to_numeric(df["id"], errors="coerce").dropna()
    return int(series.max()) + 1 if not series.empty else 1


def _build_row_for_headers(headers: List[str], candidates: Dict[str, Any]) -> List[Any]:
    normalized_map = {_normalize_header(k): v for k, v in candidates.items()}
    return [normalized_map.get(_normalize_header(header), "") for header in headers]


def _append_rows(sheet_name: str, rows: List[Dict[str, Any]], debug: Optional[List[str]] = None) -> None:
    if not rows:
        if debug is not None:
            _debug_log(debug, f"_append_rows skipped sheet={sheet_name} rows=0")
        return

    if debug is not None:
        _debug_log(debug, f"_append_rows start sheet={sheet_name} rows={len(rows)}")
    client = get_gspread_client()
    if client is None:
        raise SheetsWriteError("Google Sheets の書き込み認証が未設定です。.streamlit/secrets.toml に service account を設定してください。")

    spreadsheet = client.open_by_key(SHEET_ID)
    worksheet = spreadsheet.worksheet(sheet_name)
    headers = worksheet.row_values(1)
    if not headers:
        raise SheetsWriteError(f"{sheet_name} シートのヘッダーが取得できませんでした。")

    values = [_build_row_for_headers(headers, row) for row in rows]
    worksheet.append_rows(values, value_input_option="USER_ENTERED")
    if debug is not None:
        _debug_log(debug, f"_append_rows success sheet={sheet_name} rows={len(rows)}")


def _build_query_content_rows(existing_df: pd.DataFrame, city_id: int, query_texts: List[str], language_code: str = "ja") -> List[Dict[str, Any]]:
    next_id = _next_sheet_id(existing_df)
    now = _now_string()
    rows = []
    for index, query_text in enumerate(query_texts):
        rows.append({
            "id": next_id + index,
            "city_id": city_id,
            "query_text": query_text,
            "querytext": query_text,
            "language_code": language_code,
            "languagecode": language_code,
            "priority": index + 1,
            "is_active": 1,
            "isactive": 1,
            "created_at": now,
            "updated_at": now,
        })
    return rows


def _build_query_hit_rows(existing_df: pd.DataFrame, hit_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    next_id = _next_sheet_id(existing_df)
    rows = []
    for index, row in enumerate(hit_rows):
        copied = dict(row)
        copied["id"] = next_id + index
        rows.append(copied)
    return rows


def _build_video_rows(existing_df: pd.DataFrame, city_id: int, query_texts_by_video: OrderedDict, details: Dict[str, dict], language_code: str = "ja") -> List[Dict[str, Any]]:
    next_id = _next_sheet_id(existing_df)
    run_ts = _now_string()
    existing_video_ids = set()
    if existing_df is not None and not existing_df.empty and "video_id" in existing_df.columns:
        existing_video_ids = set(existing_df["video_id"].dropna().astype(str).str.strip())

    rows: List[Dict[str, Any]] = []
    row_index = 0
    for video_id, query_texts in query_texts_by_video.items():
        if video_id in existing_video_ids:
            continue
        item = details.get(video_id)
        if not item:
            continue
        snippet = item.get("snippet") or {}
        if (snippet.get("defaultLanguage") or "").strip().lower() != language_code:
            continue

        content = item.get("contentDetails") or {}
        stats = item.get("statistics") or {}
        status = item.get("status") or {}
        rows.append({
            "id": next_id + row_index,
            "city_id": city_id,
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": snippet.get("title"),
            "description": snippet.get("description"),
            "published_at": snippet.get("publishedAt"),
            "channel_id": snippet.get("channelId"),
            "channel_title": snippet.get("channelTitle"),
            "duration_sec": _parse_iso8601_duration_to_seconds(content.get("duration")),
            "thumbnail_url": _pick_thumbnail_url(snippet.get("thumbnails")),
            "view_count": _int_or_none(stats.get("viewCount")),
            "like_count": _int_or_none(stats.get("likeCount")),
            "comment_count": _int_or_none(stats.get("commentCount")),
            "default_language": snippet.get("defaultLanguage"),
            "default_audio_language": snippet.get("defaultAudioLanguage"),
            "caption_flag": str(content.get("caption")).lower() == "true" if content.get("caption") is not None else None,
            "search_query": " | ".join(query_texts),
            "privacy_status": status.get("privacyStatus"),
            "privacyStatus": status.get("privacyStatus"),
            "embeddable": status.get("embeddable"),
            "madeForKids": status.get("madeForKids"),
            "upload_status": status.get("uploadStatus"),
            "uploadStatus": status.get("uploadStatus"),
            "created_at": run_ts,
            "updated_at": run_ts,
        })
        row_index += 1
    return rows


def collect_city_youtube_videos(
    city_id: int,
    city_detail: Dict[str, Any],
    data: AppData,
    api_key: str,
    max_total_videos: int = 5,
    max_queries: int = 5,
    language_code: str = "ja",
) -> Dict[str, Any]:
    debug: List[str] = []
    _debug_log(debug, f"collect_city_youtube_videos start city_id={city_id} city_jp={city_detail.get('city_jp')!r}")
    query_texts = _generate_youtube_query_texts(city_detail, max_queries=max_queries)
    _debug_log(debug, f"generated query_texts={query_texts}")
    if not query_texts:
        _debug_log(debug, "no query_texts generated")
        return {"added_videos": 0, "queries": [], "query_hits": [], "debug": debug}

    query_rows = _build_query_content_rows(data.queries_content, city_id, query_texts, language_code=language_code)
    _debug_log(debug, f"query_rows_count={len(query_rows)} query_ids={[row.get('id') for row in query_rows]}")
    _append_rows("Queries_content", query_rows, debug=debug)

    api_key = str(api_key or "").strip()
    _debug_log(debug, f"received api_key_exists={bool(api_key)} api_key_prefix={(api_key[:8] + '...') if api_key else None}")
    if not api_key:
        raise SheetsWriteError("YouTube APIキーが設定されていません。 city_detail から空の api_key が渡されています。")

    session = requests.Session()
    all_hit_rows: List[Dict[str, Any]] = []
    video_first_seen_order: List[str] = []
    query_texts_by_video: OrderedDict[str, List[str]] = OrderedDict()
    seen_video_ids: set[str] = set()

    for query_row in query_rows:
        query_id = query_row["id"]
        query_text = query_row.get("query_text", "")
        searched_at = _now_string()
        try:
            search_hits = _search_videos_for_query(
                api_key=api_key,
                session=session,
                query_text=query_text,
                language_code=language_code,
                max_results=max_total_videos,
                debug=debug,
            )
        except Exception as exc:
            _debug_log(debug, f"search error query_id={query_id} query_text={query_text!r} exc={type(exc).__name__}: {exc}")
            all_hit_rows.append({
                "city_id": city_id,
                "query_id": query_id,
                "video_id": "",
                "searched_at": searched_at,
                "result_rank": 0,
                "matched_status": f"error:{type(exc).__name__}",
                "created_at": searched_at,
                "updated_at": searched_at,
            })
            continue

        if not search_hits:
            _debug_log(debug, f"no search hits query_id={query_id} query_text={query_text!r}")
            all_hit_rows.append({
                "city_id": city_id,
                "query_id": query_id,
                "video_id": "",
                "searched_at": searched_at,
                "result_rank": 0,
                "matched_status": "no_results",
                "created_at": searched_at,
                "updated_at": searched_at,
            })
            continue

        _debug_log(debug, f"search hits query_id={query_id} count={len(search_hits)}")
        for hit in search_hits:
            video_id = hit["video_id"]
            if video_id not in query_texts_by_video:
                query_texts_by_video[video_id] = []
            if query_text not in query_texts_by_video[video_id]:
                query_texts_by_video[video_id].append(query_text)

            if video_id not in seen_video_ids:
                seen_video_ids.add(video_id)
                video_first_seen_order.append(video_id)

            all_hit_rows.append({
                "city_id": city_id,
                "query_id": query_id,
                "video_id": video_id,
                "searched_at": searched_at,
                "result_rank": hit["rank"],
                "matched_status": "fetched",
                "created_at": searched_at,
                "updated_at": searched_at,
            })

    _debug_log(debug, f"video_first_seen_order_count={len(video_first_seen_order)} ids={video_first_seen_order}")
    details = _fetch_video_details(api_key, session, video_first_seen_order, debug=debug)
    _debug_log(debug, f"details_count={len(details)}")
    filtered_hit_rows: List[Dict[str, Any]] = []
    kept_video_ids: List[str] = []
    city_existing = data.youtube_videos.copy() if data.youtube_videos is not None else pd.DataFrame()
    existing_city_video_ids = set()
    if not city_existing.empty and "city_id" in city_existing.columns and "video_id" in city_existing.columns:
        city_existing["city_id"] = pd.to_numeric(city_existing["city_id"], errors="coerce")
        subset = city_existing[city_existing["city_id"] == city_id]
        existing_city_video_ids = set(subset["video_id"].dropna().astype(str).str.strip())

    for row in all_hit_rows:
        video_id = str(row.get("video_id", "") or "").strip()
        if not video_id:
            filtered_hit_rows.append(row)
            continue
        detail_item = details.get(video_id)
        snippet = (detail_item or {}).get("snippet") or {}
        default_language = (snippet.get("defaultLanguage") or "").strip().lower()

        if video_id in existing_city_video_ids:
            row["matched_status"] = "already_exists"
        elif default_language != language_code:
            row["matched_status"] = "filtered_out"
        elif video_id in kept_video_ids:
            row["matched_status"] = "duplicate"
        elif len(kept_video_ids) >= max_total_videos:
            row["matched_status"] = "overflow"
        else:
            row["matched_status"] = "adopted"
            kept_video_ids.append(video_id)
        filtered_hit_rows.append(row)

    video_rows = _build_video_rows(data.youtube_videos, city_id, query_texts_by_video, details, language_code=language_code)
    if len(video_rows) > max_total_videos:
        video_rows = video_rows[:max_total_videos]

    adopted_ids = {str(row.get("video_id", "")) for row in video_rows}
    for row in filtered_hit_rows:
        video_id = str(row.get("video_id", "") or "")
        if row.get("matched_status") == "adopted" and video_id not in adopted_ids:
            row["matched_status"] = "filtered_out"

    _debug_log(debug, f"filtered_hit_rows_count={len(filtered_hit_rows)} kept_video_ids={kept_video_ids}")
    _debug_log(debug, f"video_rows_count={len(video_rows)} adopted_ids={list(adopted_ids)}")
    query_hit_rows = _build_query_hit_rows(data.query_hits, filtered_hit_rows)
    _append_rows("Query_hits", query_hit_rows, debug=debug)
    if video_rows:
        _append_rows("Youtube_videos", video_rows, debug=debug)
    else:
        _debug_log(debug, "no video_rows to append")

    load_data.clear()
    _debug_log(debug, f"collect_city_youtube_videos end added_videos={len(video_rows)}")
    return {"added_videos": len(video_rows), "queries": query_rows, "query_hits": query_hit_rows, "debug": debug}

def categories_enabled(df: pd.DataFrame) -> pd.DataFrame:
    if "is_enabled" in df.columns:
        df = df[df["is_enabled"] == 1].copy()
    if "sort_order" in df.columns:
        df = df.sort_values(["sort_order", "id"], ascending=[True, True])
    return df


def get_enabled_currency_codes(countries: pd.DataFrame) -> List[str]:
    base = countries.copy()
    if "flag" in base.columns:
        base = base[base["flag"] == 1]
    if "currency_code" not in base.columns:
        return []
    values = base["currency_code"].dropna().astype(str).str.strip()
    return sorted([x for x in values.unique().tolist() if x])


@st.cache_data(ttl=43200, show_spinner=False)
def get_exchange_rate(payment_date: str, from_currency: str, to_currency: str = "JPY") -> float:
    from_currency = from_currency.upper().strip()
    to_currency = to_currency.upper().strip()

    if from_currency == to_currency:
        return 1.0

    response = requests.get(
        f"{FRANKFURTER_BASE_URL}/rates",
        params={"date": payment_date, "base": from_currency, "quotes": to_currency},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()

    if not payload:
        raise ValueError("為替データが取得できませんでした。")

    rate = payload[0].get("rate")
    if rate is None:
        raise ValueError("為替レートが見つかりませんでした。")

    return float(rate)


@st.cache_data(ttl=3600, show_spinner=False)
def get_latest_exchange_rate(from_currency: str, to_currency: str = "JPY") -> float:
    from_currency = from_currency.upper().strip()
    to_currency = to_currency.upper().strip()

    if from_currency == to_currency:
        return 1.0

    response = requests.get(
        f"{FRANKFURTER_BASE_URL}/latest",
        params={"base": from_currency, "symbols": to_currency},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()

    rates = payload.get("rates", {})
    rate = rates.get(to_currency)

    if rate is None:
        raise ValueError("最新の為替レートが取得できませんでした。")

    return float(rate)


def get_city_airport_text(city_id: int, city_airports: pd.DataFrame, airports: pd.DataFrame) -> str:
    links = city_airports[city_airports["city_id"] == city_id].copy()
    if links.empty:
        return ""

    merged = links.merge(airports, on="airport_id", how="left")

    if "priority" in merged.columns:
        merged = merged.sort_values(["priority", "airport_id"], ascending=[True, True])
    else:
        merged = merged.sort_values(["airport_id"], ascending=True)

    result = []
    for _, row in merged.iterrows():
        name = row.get("name_ja") or row.get("name") or ""
        iata = str(row.get("iata_code", "")).strip()
        if name and iata:
            result.append(f"{name} ({iata})")
        elif name:
            result.append(name)
        elif iata:
            result.append(iata)

    return "、".join([x for x in result if x])


def get_city_detail(city_id: int, data: AppData) -> Dict[str, Any]:
    cities = data.cities.copy()
    countries = data.countries.copy()

    city_row = cities[cities["city_id"] == city_id]
    if city_row.empty:
        raise ValueError("指定された city_id の都市が見つかりません。")

    city_row = city_row.iloc[0]

    country_row = countries[countries["country_id"] == city_row["country_id"]]
    if country_row.empty:
        raise ValueError("都市に対応する country が見つかりません。")

    country_row = country_row.iloc[0]

    currency_code = str(country_row.get("currency_code", "")).strip()
    exchange_text = ""

    try:
        if currency_code:
            latest_rate = get_latest_exchange_rate(currency_code, "JPY")
            exchange_text = f"1 {currency_code} = {latest_rate:.2f} JPY"
    except Exception:
        exchange_text = "取得失敗"

    return {
        "country": country_row.get("country", ""),
        "area1": country_row.get("area1", ""),
        "area2": country_row.get("area2", ""),
        "city_jp": city_row.get("city_jp", ""),
        "city_en": city_row.get("city_en", ""),
        "language": country_row.get("language", "") if "language" in country_row.index else "",
        "currency_code": currency_code,
        "exchange_rate": exchange_text,
        "religion": country_row.get("religion", ""),
        "lat": city_row.get("lat", ""),
        "lon": city_row.get("lon", ""),
        "airports": get_city_airport_text(int(city_id), data.city_airports, data.airports),
        "population": city_row.get("population", ""),
        "timezone_offset": city_row.get("timezone_offset", ""),
        "elevation": city_row.get("elevation", ""),
        "cost_index": city_row.get("cost_index", ""),
    }


def format_date(dt_value: datetime) -> str:
    return dt_value.strftime("%Y/%m/%d")


def format_datetime(dt_value: datetime) -> str:
    return dt_value.strftime("%Y/%m/%d %H:%M:%S")


@st.cache_resource(show_spinner=False)
def get_gspread_client():
    import gspread
    from google.oauth2.service_account import Credentials

    service_account_info = None
    if "gcp_service_account" in st.secrets:
        service_account_info = dict(st.secrets["gcp_service_account"])
    elif "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
        service_account_info = dict(st.secrets["connections"]["gsheets"])

    if service_account_info is None:
        return None

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
    return gspread.authorize(credentials)


def append_expense_row(expense_row: Dict[str, Any], sheet_name: str = "Expenses") -> None:
    if debug is not None:
        _debug_log(debug, f"_append_rows start sheet={sheet_name} rows={len(rows)}")
    client = get_gspread_client()
    if client is None:
        raise SheetsWriteError(
            "Google Sheets の書き込み認証が未設定です。.streamlit/secrets.toml に service account を設定してください。"
        )

    spreadsheet = client.open_by_key(SHEET_ID)
    worksheet = spreadsheet.worksheet(sheet_name)

    headers = worksheet.row_values(1)
    if not headers:
        raise SheetsWriteError("Expenses シートのヘッダーが取得できませんでした。")

    ordered_values = [expense_row.get(header, "") for header in headers]
    worksheet.append_row(ordered_values, value_input_option="USER_ENTERED")
    load_data.clear()


def build_expense_row(
    expenses_df: pd.DataFrame,
    payment_date: datetime,
    currency_code: str,
    amount: float,
    exchange_rate: float,
    payment_method: str,
    description: str,
    usage_category_id: int,
    tax_category_id: int,
) -> Dict[str, Any]:
    now = pd.Timestamp.now(tz=JST).to_pydatetime()
    existing_ids = pd.to_numeric(expenses_df.get("id", pd.Series(dtype=float)), errors="coerce").dropna()
    next_id = int(existing_ids.max()) + 1 if not existing_ids.empty else 1
    amount_base = round(float(amount) * float(exchange_rate))

    return {
        "id": next_id,
        "payment_date": format_date(payment_date),
        "currency_code": currency_code,
        "amount": float(amount),
        "exchange_rate": float(exchange_rate),
        "amount_base": int(amount_base),
        "payment_method": payment_method,
        "description": description.strip(),
        "usage_categories_id": int(usage_category_id),
        "tax_categories_id": int(tax_category_id),
        "created_at": format_datetime(now),
        "updated_at": format_datetime(now),
    }


def enrich_expenses(expenses: pd.DataFrame, usage_categories: pd.DataFrame, tax_categories: pd.DataFrame) -> pd.DataFrame:
    df = expenses.copy()
    if df.empty:
        return df

    usage_map = categories_enabled(usage_categories)[["id", "name_ja", "name_en"]].rename(
        columns={"id": "usage_categories_id", "name_ja": "usage_category_name_ja", "name_en": "usage_category_name_en"}
    )
    tax_map = categories_enabled(tax_categories)[["id", "name_ja", "name_en"]].rename(
        columns={"id": "tax_categories_id", "name_ja": "tax_category_name_ja", "name_en": "tax_category_name_en"}
    )

    df = df.merge(usage_map, on="usage_categories_id", how="left")
    df = df.merge(tax_map, on="tax_categories_id", how="left")
    df["payment_date_dt"] = pd.to_datetime(df["payment_date"], format="%Y/%m/%d", errors="coerce")
    df["month"] = df["payment_date_dt"].dt.to_period("M").astype(str)
    df["day"] = df["payment_date_dt"].dt.strftime("%Y/%m/%d")
    df["amount_base"] = pd.to_numeric(df["amount_base"], errors="coerce").fillna(0)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    return df


def build_pivot_table(expenses: pd.DataFrame, category_basis: str, period_basis: str) -> pd.DataFrame:
    if expenses.empty:
        return pd.DataFrame()

    if category_basis == "用途別":
        category_col = "usage_category_name_ja"
    else:
        category_col = "tax_category_name_ja"

    index_col = "day" if period_basis == "日次" else "month"

    pivot = pd.pivot_table(
        expenses,
        index=index_col,
        columns=category_col,
        values="amount_base",
        aggfunc="sum",
        fill_value=0,
    )

    pivot["合計"] = pivot.sum(axis=1)
    ordered_cols = [col for col in pivot.columns if col != "合計"] + ["合計"]
    pivot = pivot[ordered_cols].sort_index()
    return pivot.reset_index().rename(columns={index_col: period_basis})