from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_FILES = [
    ROOT / "app.py",
    ROOT / "utils" / "auth.py",
    ROOT / "pages" / "budget_manage.py",
    ROOT / "pages" / "city_detail.py",
    ROOT / "pages" / "city_recommend.py",
    ROOT / "pages" / "city_suggest.py",
    ROOT / "pages" / "expense_manage.py",
    ROOT / "pages" / "expense_register.py",
    ROOT / "pages" / "user_settings.py",
]


def test_streamlit_use_container_width_deprecations_are_removed():
    for path in STREAMLIT_FILES:
        source = path.read_text(encoding="utf-8")

        if path.name == "city_suggest.py":
            assert "st_folium(" in source
            assert "use_container_width=True" in source
            assert 'st.dataframe(result_table, width="stretch", hide_index=True)' in source
            assert 'st.dataframe(pd.DataFrame(debug_rows), width="stretch", hide_index=True)' in source
            continue

        assert "use_container_width" not in source, f"{path} still uses deprecated use_container_width"
        assert 'width="stretch"' in source, f"{path} is expected to use width='stretch'"
