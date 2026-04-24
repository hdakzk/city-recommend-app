from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from utils.auth import require_authenticated_user
from utils.user_settings import (
    DEFAULT_BASE_CURRENCY,
    load_available_currency_codes,
    load_user_account_data,
    resolve_default_currency_code,
    normalize_currency_selection,
    save_user_account_data,
)


def main() -> None:
    user = require_authenticated_user()
    auth_user_id = str(getattr(user, "id", ""))
    auth_email = str(getattr(user, "email", "") or "")

    st.title("ユーザー設定")
    st.caption("プロフィール、居住設定、利用通貨を編集します。")

    try:
        account_data = load_user_account_data(auth_user_id)
        currency_options = load_available_currency_codes()
    except Exception as e:
        st.error(f"ユーザー設定の読み込みに失敗しました: {e}")
        st.stop()

    profile = account_data.get("profile", {})
    settings = account_data.get("settings", {})
    user_currencies = account_data.get("currencies")

    enabled_currency_codes: list[str] = []
    if user_currencies is not None and not user_currencies.empty and "currency_code" in user_currencies.columns:
        enabled_df = user_currencies.copy()
        if "is_enabled" in enabled_df.columns:
            enabled_df = enabled_df[enabled_df["is_enabled"].fillna(False).astype(bool)]
        enabled_currency_codes = [
            str(value).strip().upper()
            for value in enabled_df["currency_code"].tolist()
            if str(value).strip()
        ]

    existing_default_currency_code = ""
    if user_currencies is not None and not user_currencies.empty:
        default_df = user_currencies.copy()
        if "is_default" in default_df.columns:
            default_df = default_df[default_df["is_default"].fillna(False).astype(bool)]
        if not default_df.empty and "currency_code" in default_df.columns:
            existing_default_currency_code = str(default_df.iloc[0].get("currency_code", "")).strip().upper()

    default_currency_code = resolve_default_currency_code(
        enabled_currency_codes,
        existing_default_currency_code,
    )
    if default_currency_code not in currency_options:
        currency_options.append(default_currency_code)

    with st.form("user_settings_form"):
        col1, col2 = st.columns(2)
        with col1:
            first_name = st.text_input("名", value=str(profile.get("first_name", "") or ""))
            display_name = st.text_input(
                "表示名",
                value=str(profile.get("display_name", "") or auth_email.split("@")[0]),
            )
            email = st.text_input("メールアドレス", value=str(profile.get("email", "") or auth_email))
            nationality_country_code = st.text_input(
                "国籍コード",
                value=str(profile.get("nationality_country_code", "") or ""),
                placeholder="例: JP",
            )
            avatar_url = st.text_input("アバターURL", value=str(profile.get("avatar_url", "") or ""))

        with col2:
            last_name = st.text_input("姓", value=str(profile.get("last_name", "") or ""))
            current_country_code = st.text_input(
                "現在滞在国コード",
                value=str(settings.get("current_country_code", "") or ""),
                placeholder="例: VN",
            )
            base_currency_code = st.selectbox(
                "基準通貨",
                options=currency_options,
                index=currency_options.index(
                    str(settings.get("base_currency_code", "") or DEFAULT_BASE_CURRENCY).upper()
                    if str(settings.get("base_currency_code", "") or DEFAULT_BASE_CURRENCY).upper() in currency_options
                    else DEFAULT_BASE_CURRENCY
                ),
            )
            status = st.selectbox(
                "ステータス",
                options=["active", "inactive"],
                index=0 if str(profile.get("status", "active") or "active") == "active" else 1,
            )

        selected_currency_codes = st.multiselect(
            "利用通貨",
            options=currency_options,
            default=enabled_currency_codes or [default_currency_code],
        )
        _, resolved_default = normalize_currency_selection(
            selected_currency_codes,
            default_currency_code,
            available_currency_codes=currency_options,
        )
        default_currency_code = st.selectbox(
            "既定の決済通貨",
            options=currency_options,
            index=currency_options.index(resolved_default) if resolved_default in currency_options else 0,
        )

        submitted = st.form_submit_button("保存", width="stretch")

    if submitted:
        if not email.strip():
            st.error("メールアドレスを入力してください。")
            st.stop()

        if not display_name.strip():
            st.error("表示名を入力してください。")
            st.stop()

        if not selected_currency_codes:
            st.error("利用通貨を1つ以上選択してください。")
            st.stop()

        try:
            selected_currency_codes, default_currency_code = normalize_currency_selection(
                selected_currency_codes,
                default_currency_code,
                available_currency_codes=currency_options,
            )
            save_user_account_data(
                auth_user_id=auth_user_id,
                email=email,
                first_name=first_name,
                last_name=last_name,
                display_name=display_name,
                avatar_url=avatar_url,
                nationality_country_code=nationality_country_code,
                current_country_code=current_country_code,
                base_currency_code=base_currency_code,
                enabled_currency_codes=selected_currency_codes,
                default_currency_code=default_currency_code,
                status=status,
                sync_auth_email=email.strip() != auth_email.strip(),
            )
            st.success("ユーザー設定を保存しました。")
            st.rerun()
        except Exception as e:
            st.error(f"ユーザー設定の保存に失敗しました: {e}")


if __name__ == "__main__":
    main()
