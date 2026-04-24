from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FILES_WITH_UTILS_IMPORTS = [
    ROOT / "app.py",
    ROOT / "pages" / "budget_manage.py",
    ROOT / "pages" / "city_detail.py",
    ROOT / "pages" / "city_recommend.py",
    ROOT / "pages" / "city_suggest.py",
    ROOT / "pages" / "expense_manage.py",
    ROOT / "pages" / "expense_register.py",
    ROOT / "pages" / "user_settings.py",
]


def test_streamlit_entrypoints_bootstrap_project_root_for_utils_imports():
    for path in FILES_WITH_UTILS_IMPORTS:
        source = path.read_text(encoding="utf-8")

        assert "from pathlib import Path" in source, f"{path} is missing Path bootstrap"
        assert "import sys" in source, f"{path} is missing sys bootstrap"
        assert "PROJECT_ROOT = Path(__file__).resolve()" in source, f"{path} is missing project root detection"
        assert "sys.path.insert(0, str(PROJECT_ROOT))" in source, f"{path} is missing sys.path bootstrap"
