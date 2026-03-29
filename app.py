import streamlit as st

st.set_page_config(
    page_title="Travel Support App",
    layout="wide",
)

# 必要に応じて共通CSSをここで管理
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

# -----------------------------
# Navigation
# -----------------------------
# city_detail.py は一覧からの内部遷移専用なので、
# st.navigation のメニューには含めない
expense_register_page = st.Page(
    "pages/expense_register.py",
    title="経費登録",
    icon="💸",
    default=True,
)

expense_manage_page = st.Page(
    "pages/expense_manage.py",
    title="経費管理",
    icon="📊",
)

city_recommend_page = st.Page(
    "pages/city_recommend.py",
    title="都市レコメンド",
    icon="🌏",
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
            city_recommend_page,
            city_suggest_page,
        ]
    },
    position="sidebar",
)

pg.run()
