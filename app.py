import streamlit as st

from utils.auth import (
    get_current_user,
    init_auth_state,
    is_logged_in,
    sign_in,
    sign_out,
    sign_up,
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
        login_tab, signup_tab = st.tabs(["ログイン", "新規登録"])

        with login_tab:
            with st.form("login_form", clear_on_submit=False):
                login_email = st.text_input("メールアドレス", key="login_email")
                login_password = st.text_input("パスワード", type="password", key="login_password")
                login_submitted = st.form_submit_button("ログイン", use_container_width=True)

            if login_submitted:
                if not login_email.strip() or not login_password:
                    st.error("メールアドレスとパスワードを入力してください。")
                else:
                    try:
                        sign_in(login_email.strip(), login_password)
                        st.success("ログインしました。")
                        st.rerun()
                    except Exception as e:
                        st.error(f"ログインに失敗しました: {e}")

        with signup_tab:
            with st.form("signup_form", clear_on_submit=False):
                signup_email = st.text_input("メールアドレス", key="signup_email")
                signup_password = st.text_input("パスワード", type="password", key="signup_password")
                signup_submitted = st.form_submit_button("新規登録", use_container_width=True)

            if signup_submitted:
                if not signup_email.strip() or not signup_password:
                    st.error("メールアドレスとパスワードを入力してください。")
                elif len(signup_password) < 6:
                    st.error("パスワードは6文字以上を推奨します。")
                else:
                    try:
                        result = sign_up(signup_email.strip(), signup_password)
                        if getattr(result, "session", None):
                            st.success("アカウントを作成し、そのままログインしました。")
                            st.rerun()
                        else:
                            st.success(
                                "アカウントを作成しました。確認メールを送っている場合は、メール認証後にログインしてください。"
                            )
                    except Exception as e:
                        st.error(f"新規登録に失敗しました: {e}")

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
