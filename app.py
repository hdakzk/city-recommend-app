import streamlit as st

from utils.auth import (
    get_current_user,
    init_auth_state,
    is_logged_in,
    sign_out,
    render_auth_forms,
    sync_auth_cookie,
)

st.set_page_config(
    page_title="Travel Support App",
    layout="wide",
)

init_auth_state()

st.markdown(
    """
    <style>
    .block-container {
        max-width: 100% !important;
        padding-top: 1.2rem;
        padding-left: 2rem;
        padding-right: 2rem;
        padding-bottom: 2rem;
    }

    section[data-testid="stSidebar"] + div .block-container {
        max-width: 100% !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

user = get_current_user()
logged_in = user is not None and is_logged_in()
sync_auth_cookie()

with st.sidebar:
    st.markdown("## アカウント")

    if logged_in:
        user_email = getattr(user, "email", "") or "ログイン中"
        st.success(f"ログイン中: {user_email}")

        if st.button("ログアウト", use_container_width=True):
            try:
                sign_out()
                st.success("ログアウトしました。")
                st.rerun()
            except Exception as e:
                st.error(f"ログアウトに失敗しました: {e}")
    else:
        render_auth_forms(key_prefix="sidebar_auth")

# city_detail.py は一覧からの内部遷移専用なので、メニューには含めない。
expense_register_page = st.Page(
    "pages/expense_register.py",
    title="経費登録",
    icon="💸",
    default=logged_in,
)

expense_manage_page = st.Page(
    "pages/expense_manage.py",
    title="経費管理",
    icon="📊",
)

budget_manage_page = st.Page(
    "pages/budget_manage.py",
    title="予算管理",
    icon="💰",
)

city_recommend_page = st.Page(
    "pages/city_recommend.py",
    title="都市レコメンド",
    icon="🌏",
    default=not logged_in,
)

city_suggest_page = st.Page(
    "pages/city_suggest.py",
    title="都市情報探索",
    icon="🧭",
)

pg = st.navigation(
    {
        "menu": [
            expense_register_page,
            expense_manage_page,
            budget_manage_page,
            city_recommend_page,
            city_suggest_page,
        ]
    },
    position="sidebar",
)

pg.run()
