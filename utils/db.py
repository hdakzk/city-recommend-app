from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence

import pandas as pd
import streamlit as st

from utils.supabase_client import create_public_supabase_client


MASTER_CACHE_TTL_SECONDS = 60 * 60 * 10  # 10時間


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
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = out[col].astype(str).str.strip()
            out.loc[out[col].isin(["nan", "None"]), col] = ""
    return out


def _normalize_numeric_column(df: pd.DataFrame, col: str) -> pd.DataFrame:
    out = df.copy()
    if col in out.columns:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def _empty_df(columns: Sequence[str] | None = None) -> pd.DataFrame:
    if not columns:
        return pd.DataFrame()
    return pd.DataFrame(columns=list(columns))


def _chunked(values: Sequence[Any], chunk_size: int) -> Iterable[List[Any]]:
    for i in range(0, len(values), chunk_size):
        yield list(values[i:i + chunk_size])


def _fetch_rows(
    table_name: str,
    select_columns: str = "*",
    eq_filters: Dict[str, Any] | None = None,
    in_filters: Dict[str, Sequence[Any]] | None = None,
    page_size: int = 10000,
    in_chunk_size: int = 300,
    expected_columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    eq_filters = eq_filters or {}
    in_filters = in_filters or {}
    public_client = create_public_supabase_client()

    if not in_filters:
        all_rows: List[Dict[str, Any]] = []
        start = 0

        while True:
            end = start + page_size - 1
            query = public_client.table(table_name).select(select_columns)

            for key, value in eq_filters.items():
                query = query.eq(key, value)

            response = query.range(start, end).execute()
            rows = response.data or []

            if not rows:
                break

            all_rows.extend(rows)

            if len(rows) < page_size:
                break

            start += page_size

        if not all_rows:
            return _empty_df(expected_columns)

        df = pd.DataFrame(all_rows)
        df.columns = df.columns.str.strip()
        return df

    in_items = list(in_filters.items())
    if len(in_items) != 1:
        raise ValueError("in_filters は1項目のみ対応です。")

    in_column, in_values = in_items[0]
    normalized_values = [
        v for v in in_values
        if v is not None and not (isinstance(v, float) and pd.isna(v))
    ]

    if not normalized_values:
        return _empty_df(expected_columns)

    all_rows: List[Dict[str, Any]] = []

    for chunk in _chunked(list(dict.fromkeys(normalized_values)), in_chunk_size):
        start = 0
        while True:
            end = start + page_size - 1
            query = public_client.table(table_name).select(select_columns).in_(in_column, chunk)

            for key, value in eq_filters.items():
                query = query.eq(key, value)

            response = query.range(start, end).execute()
            rows = response.data or []

            if not rows:
                break

            all_rows.extend(rows)

            if len(rows) < page_size:
                break

            start += page_size

    if not all_rows:
        return _empty_df(expected_columns)

    df = pd.DataFrame(all_rows)
    df.columns = df.columns.str.strip()
    return df


def _normalize_countries(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    out = _normalize_text_columns(
        df,
        ["country", "country_en", "area1", "area2", "currency_code", "religion"],
    )

    for col in ["country_id", "flag"]:
        out = _normalize_numeric_column(out, col)

    return out


def _normalize_cities(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    out = _normalize_text_columns(df, ["city_jp", "city_en", "city_aliases_match"])

    for col in ["city_id", "country_id", "lat", "lon", "population", "elevation", "cost_index"]:
        out = _normalize_numeric_column(out, col)

    return out


def _normalize_climate(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()
    for col in ["city_id", "month", "min_temp", "avg_temp", "max_temp", "precip_mm"]:
        out = _normalize_numeric_column(out, col)
    return out


def _normalize_city_airports(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()
    for col in ["city_id", "airport_id"]:
        out = _normalize_numeric_column(out, col)
    return out


def _normalize_airports(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    out = _normalize_text_columns(
        df,
        ["name", "name_ja", "city", "city_ja", "country_ja", "iata_code", "icao_code", "timezone_name"],
    )

    for col in ["airport_id", "country_id", "latitude", "longitude", "altitude_ft", "priority"]:
        out = _normalize_numeric_column(out, col)

    return out


def _normalize_youtube_videos(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    out = _normalize_text_columns(
        df,
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
            "default_audio_language",
            "search_query",
            "created_at",
            "updated_at",
        ],
    )

    for col in ["id", "city_id", "duration_sec", "view_count", "like_count", "comment_count"]:
        out = _normalize_numeric_column(out, col)

    return out


def prepare_cities_for_selection(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    required_cols = {"city_id", "country_id"}
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        return _empty_df()

    out = df.copy()
    for col in ["city_id", "country_id", "lat", "lon", "population", "elevation", "cost_index"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["city_id"]).copy()
    if out.empty:
        return out

    out["city_id"] = out["city_id"].astype(int)
    out["country_id"] = pd.to_numeric(out["country_id"], errors="coerce")
    out = out.dropna(subset=["country_id"]).copy()
    if out.empty:
        return out

    out["country_id"] = out["country_id"].astype(int)

    if "city_jp" not in out.columns:
        out["city_jp"] = ""
    if "city_en" not in out.columns:
        out["city_en"] = ""

    return _normalize_text_columns(out, ["city_jp", "city_en"])


@st.cache_data(ttl=MASTER_CACHE_TTL_SECONDS, show_spinner=False)
def load_all_countries() -> pd.DataFrame:
    df = _fetch_rows(
        table_name="countries",
        select_columns="country_id,country,country_en,area1,area2,flag,currency_code,religion",
        expected_columns=[
            "country_id",
            "country",
            "country_en",
            "area1",
            "area2",
            "flag",
            "currency_code",
            "religion",
        ],
    )
    return _normalize_countries(df)


@st.cache_data(ttl=MASTER_CACHE_TTL_SECONDS, show_spinner=False)
def load_all_cities() -> pd.DataFrame:
    df = _fetch_rows(
        table_name="cities",
        select_columns="city_id,country_id,city_jp,city_en,lat,lon,population,elevation,cost_index",
        expected_columns=[
            "city_id",
            "country_id",
            "city_jp",
            "city_en",
            "lat",
            "lon",
            "population",
            "elevation",
            "cost_index",
        ],
    )
    return _normalize_cities(df)


@st.cache_data(ttl=MASTER_CACHE_TTL_SECONDS, show_spinner=False)
def load_countries() -> pd.DataFrame:
    return load_all_countries().copy()


@st.cache_data(ttl=MASTER_CACHE_TTL_SECONDS, show_spinner=False)
def load_cities_by_country_ids(country_ids: tuple[int, ...]) -> pd.DataFrame:
    cities = load_all_cities().copy()

    if not country_ids:
        return _empty_df(
            ["city_id", "country_id", "city_jp", "city_en", "lat", "lon", "population", "elevation", "cost_index"]
        )

    target_country_ids = set(int(x) for x in country_ids)
    cities = cities[cities["country_id"].isin(target_country_ids)].copy()
    return cities


@st.cache_data(ttl=1800, show_spinner=False)
def load_climate_by_city_ids(city_ids: tuple[int, ...] | list[int]) -> pd.DataFrame:
    city_ids = tuple(int(x) for x in city_ids) if city_ids else tuple()
    if not city_ids:
        return _empty_df(["city_id", "month", "min_temp", "avg_temp", "max_temp", "precip_mm"])

    df = _fetch_rows(
        table_name="climate",
        select_columns="city_id,month,min_temp,avg_temp,max_temp,precip_mm",
        in_filters={"city_id": list(city_ids)},
        expected_columns=["city_id", "month", "min_temp", "avg_temp", "max_temp", "precip_mm"],
    )
    return _normalize_climate(df)


@st.cache_data(ttl=1800, show_spinner=False)
def load_climate_by_city_ids_and_month(city_ids: tuple[int, ...], month: int) -> pd.DataFrame:
    if not city_ids:
        return _empty_df(["city_id", "month", "min_temp", "avg_temp", "max_temp", "precip_mm"])

    df = _fetch_rows(
        table_name="climate",
        select_columns="city_id,month,min_temp,avg_temp,max_temp,precip_mm",
        in_filters={"city_id": list(city_ids)},
        eq_filters={"month": int(month)},
        expected_columns=["city_id", "month", "min_temp", "avg_temp", "max_temp", "precip_mm"],
    )
    return _normalize_climate(df)


@st.cache_data(ttl=300, show_spinner=False)
def load_city_detail_by_id(city_id: int) -> pd.DataFrame:
    cities = load_all_cities().copy()
    city_df = cities[cities["city_id"] == int(city_id)].copy()

    if city_df.empty:
        return city_df

    countries = load_all_countries().copy()
    merged = city_df.merge(
        countries[["country_id", "country", "country_en", "currency_code", "religion"]],
        on="country_id",
        how="left",
    )
    return merged


@st.cache_data(ttl=300, show_spinner=False)
def load_airports_by_city_id(city_id: int) -> pd.DataFrame:
    city_airports = _fetch_rows(
        table_name="city_airports",
        select_columns="city_id,airport_id",
        eq_filters={"city_id": int(city_id)},
        expected_columns=["city_id", "airport_id"],
    )
    city_airports = _normalize_city_airports(city_airports)

    if city_airports.empty or "airport_id" not in city_airports.columns:
        return _empty_df(
            ["airport_id", "name", "name_ja", "city", "city_ja", "country_ja", "iata_code", "icao_code", "timezone_name"]
        )

    airport_ids = (
        pd.to_numeric(city_airports["airport_id"], errors="coerce")
        .dropna()
        .astype(int)
        .unique()
        .tolist()
    )

    if not airport_ids:
        return _empty_df(
            ["airport_id", "name", "name_ja", "city", "city_ja", "country_ja", "iata_code", "icao_code", "timezone_name"]
        )

    airports = _fetch_rows(
        table_name="airports",
        select_columns="airport_id,name,name_ja,city,city_ja,country_ja,iata_code,icao_code,timezone_name",
        in_filters={"airport_id": airport_ids},
        expected_columns=[
            "airport_id", "name", "name_ja", "city", "city_ja", "country_ja", "iata_code", "icao_code", "timezone_name"
        ],
    )
    return _normalize_airports(airports)


@st.cache_data(ttl=300, show_spinner=False)
def load_youtube_videos_by_city_id(city_id: int) -> pd.DataFrame:
    try:
        df = _fetch_rows(
            table_name="youtube_videos",
            select_columns=(
                "id,city_id,video_id,title,url,channel_title,thumbnail_url,description,"
                "published_at,view_count,like_count,comment_count,duration_sec,"
                "default_language,default_audio_language,privacy_status,upload_status,"
                "license,matched_status,search_query,created_at,updated_at"
            ),
            eq_filters={"city_id": int(city_id)},
        )
        return _normalize_youtube_videos(df)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def load_data() -> AppData:
    return AppData(
        countries=load_all_countries().copy(),
        cities=load_all_cities().copy(),
        climate=pd.DataFrame(),
        expenses=pd.DataFrame(),
        usage_categories=pd.DataFrame(),
        tax_categories=pd.DataFrame(),
        city_airports=pd.DataFrame(),
        airports=pd.DataFrame(),
        youtube_videos=pd.DataFrame(),
        queries_content=pd.DataFrame(),
        query_hits=pd.DataFrame(),
    )
