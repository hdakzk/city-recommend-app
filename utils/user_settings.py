from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

import pandas as pd
import streamlit as st

from utils.supabase_client import create_public_supabase_client, get_supabase_client


DEFAULT_BASE_CURRENCY = "JPY"
DEFAULT_PAYMENT_CURRENCY = "VND"
DEFAULT_USER_STATUS = "active"

_PUBLIC_CLIENT: Any | None = None


def _get_public_client() -> Any:
    global _PUBLIC_CLIENT
    if _PUBLIC_CLIENT is None:
        _PUBLIC_CLIENT = create_public_supabase_client()
    return _PUBLIC_CLIENT


def _now_string() -> str:
    return datetime.now().strftime("%Y/%m/%d %H:%M:%S")


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_code(value: Any) -> str:
    return _normalize_text(value).upper()


def _normalize_currency_codes(values: Iterable[Any] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        code = _normalize_code(value)
        if not code or code in seen:
            continue
        seen.add(code)
        normalized.append(code)
    return normalized


def resolve_default_currency_code(
    enabled_currency_codes: Iterable[Any] | None,
    default_currency_code: Any,
    fallback_currency_code: str = DEFAULT_PAYMENT_CURRENCY,
) -> str:
    normalized_codes = _normalize_currency_codes(enabled_currency_codes)
    requested_default = _normalize_code(default_currency_code)
    fallback_code = _normalize_code(fallback_currency_code) or DEFAULT_PAYMENT_CURRENCY

    if requested_default and requested_default in normalized_codes:
        return requested_default
    if normalized_codes:
        return normalized_codes[0]
    return fallback_code


def normalize_currency_selection(
    enabled_currency_codes: Iterable[Any] | None,
    default_currency_code: Any,
    *,
    available_currency_codes: Iterable[Any] | None = None,
) -> tuple[list[str], str]:
    normalized_enabled = _normalize_currency_codes(enabled_currency_codes)
    available_codes = _normalize_currency_codes(available_currency_codes)
    requested_default = _normalize_code(default_currency_code)
    if requested_default and requested_default in available_codes:
        resolved_default = requested_default
    else:
        resolved_default = resolve_default_currency_code(
            normalized_enabled,
            default_currency_code,
            fallback_currency_code=available_codes[0] if available_codes else DEFAULT_PAYMENT_CURRENCY,
        )

    if resolved_default not in normalized_enabled:
        normalized_enabled.append(resolved_default)

    return normalized_enabled, resolved_default


def build_signup_metadata(
    *,
    first_name: str,
    last_name: str,
    display_name: str,
    nationality_country_code: str,
    current_country_code: str,
    base_currency_code: str,
    enabled_currency_codes: Iterable[Any] | None,
    default_currency_code: str,
    avatar_url: str = "",
) -> dict[str, Any]:
    normalized_codes = _normalize_currency_codes(enabled_currency_codes)
    resolved_default = resolve_default_currency_code(normalized_codes, default_currency_code)
    normalized_base = _normalize_code(base_currency_code) or DEFAULT_BASE_CURRENCY

    if resolved_default not in normalized_codes:
        normalized_codes.append(resolved_default)

    return {
        "first_name": _normalize_text(first_name),
        "last_name": _normalize_text(last_name),
        "display_name": _normalize_text(display_name),
        "avatar_url": _normalize_text(avatar_url),
        "nationality_country_code": _normalize_code(nationality_country_code),
        "current_country_code": _normalize_code(current_country_code),
        "base_currency_code": normalized_base,
        "enabled_currency_codes": normalized_codes,
        "default_currency_code": resolved_default,
        "status": DEFAULT_USER_STATUS,
    }


def _extract_metadata(user: Any) -> dict[str, Any]:
    raw_metadata = getattr(user, "user_metadata", None) or {}
    if isinstance(raw_metadata, dict):
        return raw_metadata
    return {}


def build_user_profile_payload(
    *,
    auth_user_id: str,
    email: str,
    first_name: str,
    last_name: str,
    display_name: str,
    avatar_url: str = "",
    nationality_country_code: str = "",
    status: str = DEFAULT_USER_STATUS,
    now: str | None = None,
) -> dict[str, Any]:
    now_value = now or _now_string()
    return {
        "id": _normalize_text(auth_user_id),
        "first_name": _normalize_text(first_name),
        "last_name": _normalize_text(last_name),
        "display_name": _normalize_text(display_name),
        "email": _normalize_text(email),
        "avatar_url": _normalize_text(avatar_url),
        "nationality_country_code": _normalize_code(nationality_country_code),
        "last_active_at": now_value,
        "status": _normalize_text(status) or DEFAULT_USER_STATUS,
        "updated_at": now_value,
    }


def build_user_settings_payload(
    *,
    auth_user_id: str,
    current_country_code: str,
    base_currency_code: str,
    now: str | None = None,
) -> dict[str, Any]:
    now_value = now or _now_string()
    return {
        "user_id": _normalize_text(auth_user_id),
        "current_country_code": _normalize_code(current_country_code),
        "base_currency_code": _normalize_code(base_currency_code) or DEFAULT_BASE_CURRENCY,
        "updated_at": now_value,
    }


def build_user_currency_payloads(
    *,
    auth_user_id: str,
    enabled_currency_codes: Iterable[Any] | None,
    default_currency_code: str,
    now: str | None = None,
) -> list[dict[str, Any]]:
    now_value = now or _now_string()
    normalized_codes = _normalize_currency_codes(enabled_currency_codes)
    resolved_default = resolve_default_currency_code(normalized_codes, default_currency_code)

    if resolved_default not in normalized_codes:
        normalized_codes.append(resolved_default)

    return [
        {
            "user_id": _normalize_text(auth_user_id),
            "currency_code": code,
            "is_enabled": True,
            "is_default": code == resolved_default,
            "sort_order": index + 1,
            "updated_at": now_value,
        }
        for index, code in enumerate(normalized_codes)
    ]


def _rows_to_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df.columns = [str(col).strip() for col in df.columns]
    return df


def _fetch_single_row(client: Any, table_name: str, key: str, value: str) -> dict[str, Any]:
    response = client.table(table_name).select("*").eq(key, value).limit(1).execute()
    rows = response.data or []
    if not rows:
        return {}
    return dict(rows[0])


def _fetch_rows(client: Any, table_name: str, key: str, value: str) -> pd.DataFrame:
    response = client.table(table_name).select("*").eq(key, value).execute()
    return _rows_to_df(response.data or [])


@st.cache_data(ttl=300, show_spinner=False)
def load_available_currency_codes() -> list[str]:
    candidates: list[str] = []

    try:
        rows = _get_public_client().table("currencies").select("currency_code").execute().data or []
        candidates.extend(str(row.get("currency_code", "")).strip().upper() for row in rows)
    except Exception:
        pass

    if not candidates:
        try:
            rows = _get_public_client().table("countries").select("currency_code").execute().data or []
            candidates.extend(str(row.get("currency_code", "")).strip().upper() for row in rows)
        except Exception:
            pass

    normalized = _normalize_currency_codes(candidates)
    for fallback in [DEFAULT_BASE_CURRENCY, DEFAULT_PAYMENT_CURRENCY]:
        if fallback not in normalized:
            normalized.append(fallback)

    return normalized


@st.cache_data(ttl=120, show_spinner=False)
def load_user_account_data(auth_user_id: str) -> dict[str, Any]:
    client = get_supabase_client(use_session=True)
    profile = _fetch_single_row(client, "users", "id", auth_user_id)
    settings = _fetch_single_row(client, "user_settings", "user_id", auth_user_id)
    currencies_df = _fetch_rows(client, "user_currencies", "user_id", auth_user_id)
    return {
        "profile": profile,
        "settings": settings,
        "currencies": currencies_df,
    }


def resolve_user_expense_preferences(
    settings: dict[str, Any] | None,
    user_currencies: pd.DataFrame | None,
) -> dict[str, str]:
    settings = settings or {}
    base_currency_code = _normalize_code(settings.get("base_currency_code")) or DEFAULT_BASE_CURRENCY

    default_currency_code = ""
    if user_currencies is not None and not user_currencies.empty:
        enabled_df = user_currencies.copy()
        if "is_enabled" in enabled_df.columns:
            enabled_df = enabled_df[enabled_df["is_enabled"].fillna(False).astype(bool)]

        if not enabled_df.empty and "is_default" in enabled_df.columns:
            default_rows = enabled_df[enabled_df["is_default"].fillna(False).astype(bool)]
            if not default_rows.empty:
                default_currency_code = _normalize_code(default_rows.iloc[0].get("currency_code"))

        if not default_currency_code and not enabled_df.empty:
            default_currency_code = _normalize_code(enabled_df.iloc[0].get("currency_code"))

    return {
        "base_currency_code": base_currency_code,
        "payment_currency_code": default_currency_code or DEFAULT_PAYMENT_CURRENCY,
    }


def bootstrap_user_account_from_auth_user(
    user: Any,
    *,
    metadata_override: dict[str, Any] | None = None,
) -> None:
    auth_user_id = _normalize_text(getattr(user, "id", ""))
    email = _normalize_text(getattr(user, "email", ""))
    if not auth_user_id:
        return

    metadata = _extract_metadata(user)
    if metadata_override:
        metadata.update(metadata_override)

    now_value = _now_string()
    client = get_supabase_client(use_session=True)

    existing_profile = _fetch_single_row(client, "users", "id", auth_user_id)
    first_name = _normalize_text(existing_profile.get("first_name") or metadata.get("first_name"))
    last_name = _normalize_text(existing_profile.get("last_name") or metadata.get("last_name"))
    display_name = _normalize_text(
        existing_profile.get("display_name")
        or metadata.get("display_name")
        or email.split("@")[0]
    )
    avatar_url = _normalize_text(existing_profile.get("avatar_url") or metadata.get("avatar_url"))
    nationality_country_code = _normalize_code(
        existing_profile.get("nationality_country_code") or metadata.get("nationality_country_code")
    )
    status = _normalize_text(existing_profile.get("status") or metadata.get("status") or DEFAULT_USER_STATUS)

    profile_payload = build_user_profile_payload(
        auth_user_id=auth_user_id,
        email=email,
        first_name=first_name,
        last_name=last_name,
        display_name=display_name,
        avatar_url=avatar_url,
        nationality_country_code=nationality_country_code,
        status=status,
        now=now_value,
    )
    client.table("users").upsert(profile_payload, on_conflict="id").execute()

    existing_settings = _fetch_single_row(client, "user_settings", "user_id", auth_user_id)
    if not existing_settings:
        settings_payload = build_user_settings_payload(
            auth_user_id=auth_user_id,
            current_country_code=_normalize_code(metadata.get("current_country_code")),
            base_currency_code=_normalize_code(metadata.get("base_currency_code")) or DEFAULT_BASE_CURRENCY,
            now=now_value,
        )
        client.table("user_settings").upsert(settings_payload, on_conflict="user_id").execute()

    existing_currencies = _fetch_rows(client, "user_currencies", "user_id", auth_user_id)
    if existing_currencies.empty:
        currency_rows = build_user_currency_payloads(
            auth_user_id=auth_user_id,
            enabled_currency_codes=metadata.get("enabled_currency_codes") or [metadata.get("default_currency_code")],
            default_currency_code=_normalize_code(metadata.get("default_currency_code")),
            now=now_value,
        )
        if currency_rows:
            client.table("user_currencies").insert(currency_rows).execute()

    st.cache_data.clear()


def save_user_account_data(
    *,
    auth_user_id: str,
    email: str,
    first_name: str,
    last_name: str,
    display_name: str,
    avatar_url: str,
    nationality_country_code: str,
    current_country_code: str,
    base_currency_code: str,
    enabled_currency_codes: Iterable[Any] | None,
    default_currency_code: str,
    status: str = DEFAULT_USER_STATUS,
    sync_auth_email: bool = False,
) -> None:
    now_value = _now_string()
    client = get_supabase_client(use_session=True)

    if sync_auth_email:
        client.auth.update_user({"email": _normalize_text(email)})

    profile_payload = build_user_profile_payload(
        auth_user_id=auth_user_id,
        email=email,
        first_name=first_name,
        last_name=last_name,
        display_name=display_name,
        avatar_url=avatar_url,
        nationality_country_code=nationality_country_code,
        status=status,
        now=now_value,
    )
    settings_payload = build_user_settings_payload(
        auth_user_id=auth_user_id,
        current_country_code=current_country_code,
        base_currency_code=base_currency_code,
        now=now_value,
    )
    currency_rows = build_user_currency_payloads(
        auth_user_id=auth_user_id,
        enabled_currency_codes=enabled_currency_codes,
        default_currency_code=default_currency_code,
        now=now_value,
    )

    client.table("users").upsert(profile_payload, on_conflict="id").execute()
    client.table("user_settings").upsert(settings_payload, on_conflict="user_id").execute()
    client.table("user_currencies").delete().eq("user_id", auth_user_id).execute()
    if currency_rows:
        client.table("user_currencies").insert(currency_rows).execute()

    st.cache_data.clear()
