import importlib
import sys
from types import ModuleType, SimpleNamespace


def _clear_utils_db_modules() -> None:
    sys.modules.pop("utils.db", None)
    sys.modules.pop("utils", None)


def test_utils_db_import_does_not_create_supabase_client(monkeypatch):
    _clear_utils_db_modules()

    fake_supabase_client = ModuleType("utils.supabase_client")

    def _fail_create_client():
        raise AssertionError("create_public_supabase_client should not run during import")

    fake_supabase_client.create_public_supabase_client = _fail_create_client
    monkeypatch.setitem(sys.modules, "utils.supabase_client", fake_supabase_client)

    db = importlib.import_module("utils.db")

    assert hasattr(db, "load_countries")


def test_fetch_rows_creates_client_only_when_called(monkeypatch):
    _clear_utils_db_modules()

    queries = []

    class _FakeQuery:
        def __init__(self, table_name):
            self.table_name = table_name
            self.filters = []

        def select(self, columns):
            self.columns = columns
            return self

        def eq(self, key, value):
            self.filters.append(("eq", key, value))
            return self

        def range(self, start, end):
            self.range_args = (start, end)
            return self

        def execute(self):
            return SimpleNamespace(data=[])

    class _FakeClient:
        def table(self, table_name):
            query = _FakeQuery(table_name)
            queries.append(query)
            return query

    fake_supabase_client = ModuleType("utils.supabase_client")
    fake_supabase_client.create_public_supabase_client = lambda: _FakeClient()
    monkeypatch.setitem(sys.modules, "utils.supabase_client", fake_supabase_client)

    db = importlib.import_module("utils.db")
    result = db._fetch_rows("countries", select_columns="country_id")

    assert result.empty
    assert len(queries) == 1
    assert queries[0].table_name == "countries"
