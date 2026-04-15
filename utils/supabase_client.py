from __future__ import annotations

from typing import Optional

import streamlit as st
from supabase import Client, create_client


def _get_supabase_config() -> dict:
    config = st.secrets.get("supabase", {})
    if not config:
        raise ValueError("secrets.toml の [supabase] セクションが設定されていません。")
    return config


def _get_supabase_url() -> str:
    config = _get_supabase_config()
    url = str(config.get("url", "")).strip()
    if not url:
        raise ValueError("supabase.url が設定されていません。")
    return url


def _get_supabase_anon_key() -> str:
    config = _get_supabase_config()
    anon_key = str(config.get("anon_key", "")).strip()
    if not anon_key:
        raise ValueError("supabase.anon_key が設定されていません。")
    return anon_key


def create_public_supabase_client() -> Client:
    return create_client(_get_supabase_url(), _get_supabase_anon_key())


def get_supabase_client(use_session: bool = True) -> Client:
    client = create_public_supabase_client()

    if not use_session:
        return client

    access_token: Optional[str] = st.session_state.get("sb_access_token")
    refresh_token: Optional[str] = st.session_state.get("sb_refresh_token")

    if access_token and refresh_token:
        response = client.auth.set_session(access_token, refresh_token)
        refreshed_session = getattr(response, "session", None)

        if refreshed_session:
            st.session_state["sb_access_token"] = refreshed_session.access_token
            st.session_state["sb_refresh_token"] = refreshed_session.refresh_token
            st.session_state["sb_session_loaded"] = True

    return client