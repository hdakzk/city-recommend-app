from __future__ import annotations

import json
import os
from typing import Any, Optional
from urllib.parse import quote, unquote

import streamlit as st
from streamlit_cookies_manager import EncryptedCookieManager

from utils.supabase_client import create_public_supabase_client, get_supabase_client


AUTH_COOKIE_NAME = "city_recommend_auth"
AUTH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
AUTH_COOKIE_PREFIX = "city-recommend-app/"
AUTH_COOKIE_PASSWORD_SECRET_KEY = "COOKIE_PASSWORD"
AUTH_COOKIE_MANAGER_STATE_KEY = "_auth_cookie_manager"


def init_auth_state() -> None:
    defaults = {
        "sb_access_token": None,
        "sb_refresh_token": None,
        "sb_session_loaded": False,
        "sb_skip_cookie_restore": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if st.session_state.get("sb_skip_cookie_restore") or is_logged_in():
        return

    cookies = _get_cookie_manager()
    if not cookies.ready():
        st.stop()

    cookie_payload = _load_auth_cookie_payload(cookies.get(AUTH_COOKIE_NAME))
    if not cookie_payload:
        return

    st.session_state["sb_access_token"] = cookie_payload["access_token"]
    st.session_state["sb_refresh_token"] = cookie_payload["refresh_token"]
    st.session_state["sb_session_loaded"] = True


def _save_session(session: Any) -> None:
    if session is None:
        return

    st.session_state["sb_access_token"] = getattr(session, "access_token", None)
    st.session_state["sb_refresh_token"] = getattr(session, "refresh_token", None)
    st.session_state["sb_session_loaded"] = True
    st.session_state["sb_skip_cookie_restore"] = False
    st.cache_data.clear()


def clear_auth_state() -> None:
    st.session_state["sb_access_token"] = None
    st.session_state["sb_refresh_token"] = None
    st.session_state["sb_session_loaded"] = False
    st.session_state["sb_skip_cookie_restore"] = True
    st.cache_data.clear()


def is_logged_in() -> bool:
    return bool(
        st.session_state.get("sb_access_token")
        and st.session_state.get("sb_refresh_token")
    )


def sign_up(email: str, password: str):
    client = create_public_supabase_client()
    response = client.auth.sign_up(
        {
            "email": email,
            "password": password,
        }
    )

    session = getattr(response, "session", None)
    if session:
        _save_session(session)

    return response


def sign_in(email: str, password: str):
    client = create_public_supabase_client()
    response = client.auth.sign_in_with_password(
        {
            "email": email,
            "password": password,
        }
    )

    session = getattr(response, "session", None)
    if not session:
        raise ValueError("セッションを取得できませんでした。メール認証設定を確認してください。")

    _save_session(session)
    return response


def sign_out() -> None:
    if not is_logged_in():
        clear_auth_state()
        return

    try:
        client = get_supabase_client(use_session=True)
        client.auth.sign_out()
    finally:
        clear_auth_state()


def get_current_user() -> Optional[Any]:
    if not is_logged_in():
        return None

    try:
        client = get_supabase_client(use_session=True)
        response = client.auth.get_user()
        user = getattr(response, "user", None)

        if user is None:
            clear_auth_state()
            return None

        return user
    except Exception:
        # Treat transient auth API failures differently from confirmed logout.
        return None


def require_authenticated_user() -> Any:
    user = get_current_user()
    if user is None:
        st.warning("このページを利用するにはログインしてください。")
        st.stop()
    return user


def sync_auth_cookie() -> None:
    cookies = _get_cookie_manager()
    if not cookies.ready():
        return

    changed = False

    if is_logged_in():
        cookie_value = _dump_auth_cookie_payload(
            st.session_state.get("sb_access_token"),
            st.session_state.get("sb_refresh_token"),
        )
        if cookies.get(AUTH_COOKIE_NAME) != cookie_value:
            cookies[AUTH_COOKIE_NAME] = cookie_value
            changed = True
    else:
        if cookies.get(AUTH_COOKIE_NAME):
            del cookies[AUTH_COOKIE_NAME]
            changed = True

    if changed:
        cookies.save()


def _get_cookie_manager() -> EncryptedCookieManager:
    cookie_manager = st.session_state.get(AUTH_COOKIE_MANAGER_STATE_KEY)
    if cookie_manager is None:
        cookie_manager = EncryptedCookieManager(
            prefix=AUTH_COOKIE_PREFIX,
            password=_get_cookie_password(),
        )
        st.session_state[AUTH_COOKIE_MANAGER_STATE_KEY] = cookie_manager
    return cookie_manager


def _get_cookie_password() -> str:
    configured_password = str(st.secrets.get(AUTH_COOKIE_PASSWORD_SECRET_KEY, "")).strip()
    if configured_password:
        return configured_password

    env_password = str(os.environ.get(AUTH_COOKIE_PASSWORD_SECRET_KEY, "")).strip()
    if env_password:
        return env_password

    supabase_password = str(st.secrets.get("supabase", {}).get("anon_key", "")).strip()
    if supabase_password:
        return supabase_password

    raise ValueError(
        f"{AUTH_COOKIE_PASSWORD_SECRET_KEY} が設定されていません。"
        " 本番環境の secrets に認証 Cookie 用のパスワードを追加してください。"
    )


def _dump_auth_cookie_payload(
    access_token: Optional[str],
    refresh_token: Optional[str],
) -> str:
    if not access_token or not refresh_token:
        return ""

    payload = {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
    return quote(json.dumps(payload, separators=(",", ":")))


def _load_auth_cookie_payload(cookie_value: Optional[str]) -> Optional[dict[str, str]]:
    if not cookie_value:
        return None

    try:
        payload = json.loads(unquote(cookie_value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    access_token = str(payload.get("access_token") or "").strip()
    refresh_token = str(payload.get("refresh_token") or "").strip()
    if not access_token or not refresh_token:
        return None

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
