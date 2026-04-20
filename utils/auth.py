from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import quote, unquote

import streamlit as st
from streamlit.components.v1 import html as components_html

from utils.supabase_client import create_public_supabase_client, get_supabase_client


AUTH_COOKIE_NAME = "city_recommend_auth"
AUTH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
AUTH_STORAGE_RESTORE_KEY = "sb_restore_from_storage_attempted"


def init_auth_state() -> None:
    defaults = {
        "sb_access_token": None,
        "sb_refresh_token": None,
        "sb_session_loaded": False,
        "sb_skip_cookie_restore": False,
        AUTH_STORAGE_RESTORE_KEY: False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if st.session_state.get("sb_skip_cookie_restore") or is_logged_in():
        return

    cookie_payload = _load_auth_cookie_payload(st.context.cookies.get(AUTH_COOKIE_NAME))
    if not cookie_payload:
        _request_cookie_restore_from_browser_storage_once()
        return

    st.session_state["sb_access_token"] = cookie_payload["access_token"]
    st.session_state["sb_refresh_token"] = cookie_payload["refresh_token"]
    st.session_state["sb_session_loaded"] = True
    st.session_state[AUTH_STORAGE_RESTORE_KEY] = False


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
    cookie_value = ""
    max_age_seconds = 0

    if is_logged_in():
        cookie_value = _dump_auth_cookie_payload(
            st.session_state.get("sb_access_token"),
            st.session_state.get("sb_refresh_token"),
        )
        max_age_seconds = AUTH_COOKIE_MAX_AGE_SECONDS if cookie_value else 0

    secure_attr_script = "window.location.protocol === 'https:' ? '; Secure' : ''"
    _render_auth_script(
        f"""
        <script>
        const cookieString = "{AUTH_COOKIE_NAME}={cookie_value}; Max-Age={max_age_seconds}; Path=/; SameSite=Lax" + ({secure_attr_script});
        try {{
            document.cookie = cookieString;
        }} catch (error) {{}}

        try {{
            if ({'true' if max_age_seconds else 'false'}) {{
                window.localStorage.setItem("{AUTH_COOKIE_NAME}", "{cookie_value}");
            }} else {{
                window.localStorage.removeItem("{AUTH_COOKIE_NAME}");
            }}
        }} catch (error) {{}}
        </script>
        """
    )


def _request_cookie_restore_from_browser_storage_once() -> None:
    if st.session_state.get(AUTH_STORAGE_RESTORE_KEY):
        return

    st.session_state[AUTH_STORAGE_RESTORE_KEY] = True
    secure_attr_script = "window.location.protocol === 'https:' ? '; Secure' : ''"
    _render_auth_script(
        f"""
        <script>
        const storageKey = "{AUTH_COOKIE_NAME}";
        let storedValue = "";

        try {{
            storedValue = window.localStorage.getItem(storageKey) || "";
        }} catch (error) {{}}

        if (storedValue) {{
            const cookieString = "{AUTH_COOKIE_NAME}=" + storedValue + "; Max-Age={AUTH_COOKIE_MAX_AGE_SECONDS}; Path=/; SameSite=Lax" + ({secure_attr_script});

            try {{
                document.cookie = cookieString;
            }} catch (error) {{}}

            window.location.reload();
        }}
        </script>
        """
    )


def _render_auth_script(source: str) -> None:
    html_renderer = getattr(st, "html", None)
    if callable(html_renderer):
        html_renderer(source)
        return

    components_html(source, height=0)


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
