import zipfile
from io import BytesIO
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from utils.expense_db import (
    build_expense_record,
    build_receipt_storage_path,
    insert_expense_records,
    update_expense_record,
    upload_expense_receipt,
)
from utils.expense_manage_support import (
    build_bulk_expense_edit_frame,
    build_bulk_expense_update_plan,
    build_expense_update_payload,
    build_wechat_expense_records,
    find_category_label_by_id,
    get_expense_row_by_id,
    get_selected_expense_id,
    get_selected_expense_ids,
)


class _FakeExpenseQuery:
    def __init__(self):
        self.insert_payload = None
        self.update_payload = None
        self.conditions = []

    def insert(self, payload):
        self.insert_payload = payload
        return self

    def update(self, payload):
        self.update_payload = payload
        return self

    def eq(self, column_name, value):
        self.conditions.append((column_name, value))
        return self

    def execute(self):
        return SimpleNamespace(data=[{"id": 10}])


class _FakeSupabaseClient:
    def __init__(self, fake_query):
        self.fake_query = fake_query
        self.table_names = []
        self.storage = _FakeStorageManager()

    def table(self, table_name):
        self.table_names.append(table_name)
        return self.fake_query


class _FakeStorageBucket:
    def __init__(self, bucket_name):
        self.bucket_name = bucket_name
        self.upload_calls = []

    def upload(self, path, file_content, file_options):
        self.upload_calls.append(
            {
                "path": path,
                "file_content": file_content,
                "file_options": file_options,
            }
        )
        return SimpleNamespace(path=path)


class _FakeStorageManager:
    def __init__(self):
        self.bucket_names = []
        self.bucket = _FakeStorageBucket("expense-receipts")

    def from_(self, bucket_name):
        self.bucket_names.append(bucket_name)
        self.bucket = _FakeStorageBucket(bucket_name)
        return self.bucket


class ExpenseManageSupportTest(unittest.TestCase):
    def _make_wechat_xlsx_bytes(self, rows):
        shared_strings = []
        shared_index = {}

        def shared_string_index(value):
            if value not in shared_index:
                shared_index[value] = len(shared_strings)
                shared_strings.append(value)
            return shared_index[value]

        row_xml_list = []
        for row_number, row_values in enumerate(rows, start=1):
            cell_xml_list = []
            for col_index, value in enumerate(row_values):
                col_number = col_index + 1
                col_letters = ""
                while col_number:
                    col_number, remainder = divmod(col_number - 1, 26)
                    col_letters = chr(ord("A") + remainder) + col_letters

                if value == "":
                    continue

                if isinstance(value, (int, float)):
                    cell_xml_list.append(
                        f'<c r="{col_letters}{row_number}"><v>{value}</v></c>'
                    )
                else:
                    sst_index = shared_string_index(str(value))
                    cell_xml_list.append(
                        f'<c r="{col_letters}{row_number}" t="s"><v>{sst_index}</v></c>'
                    )

            row_xml_list.append(f'<row r="{row_number}">{"".join(cell_xml_list)}</row>')

        shared_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + "".join(f"<si><t>{value}</t></si>" for value in shared_strings)
            + "</sst>"
        )
        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>"
        )
        rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        )
        sheet_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(row_xml_list)}</sheetData>'
            "</worksheet>"
        )

        xlsx_buffer = BytesIO()
        with zipfile.ZipFile(xlsx_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr("xl/workbook.xml", workbook_xml)
            zip_file.writestr("xl/_rels/workbook.xml.rels", rels_xml)
            zip_file.writestr("xl/worksheets/sheet1.xml", sheet_xml)
            zip_file.writestr("xl/sharedStrings.xml", shared_xml)
        return xlsx_buffer.getvalue()

    def test_get_selected_expense_id_returns_id_for_selected_row(self):
        table_df = pd.DataFrame([{"ID": 30}, {"ID": 20}])
        self.assertEqual(get_selected_expense_id(table_df, [1]), 20)

    def test_get_selected_expense_id_returns_none_for_out_of_range_boundary(self):
        table_df = pd.DataFrame([{"ID": 30}])
        self.assertIsNone(get_selected_expense_id(table_df, [1]))
        self.assertIsNone(get_selected_expense_id(table_df, []))

    def test_get_selected_expense_ids_returns_unique_ids_in_selection_order(self):
        table_df = pd.DataFrame([{"ID": 30}, {"ID": 20}, {"ID": 20}, {"ID": "x"}])
        self.assertEqual(get_selected_expense_ids(table_df, [1, 2, 0, 3, 9]), [20, 30])

    def test_get_expense_row_by_id_returns_matching_row(self):
        expenses_df = pd.DataFrame(
            [{"id": 10, "description": "Lunch"}, {"id": 20, "description": "Hotel"}]
        )
        self.assertEqual(
            get_expense_row_by_id(expenses_df, 20),
            {"id": 20, "description": "Hotel"},
        )

    def test_find_category_label_by_id_falls_back_to_first_label_for_invalid_id(self):
        self.assertEqual(find_category_label_by_id({"Food": 1, "Hotel": 2}, None), "Food")

    def test_build_expense_update_payload_builds_normalized_payload(self):
        expense_id, payload = build_expense_update_payload(
            expense_id="10",
            payment_date_value=date(2026, 4, 3),
            currency_code=" usd ",
            amount=15000,
            exchange_rate=0.006,
            payment_method=" 現金 ",
            description=" ランチ ",
            usage_category_id="2",
            tax_category_id="3",
        )

        self.assertEqual(expense_id, 10)
        self.assertEqual(payload["payment_date"], "2026/04/03")
        self.assertEqual(payload["currency_code"], "USD")
        self.assertEqual(payload["amount_base"], 90)
        self.assertEqual(payload["payment_method"], "現金")
        self.assertEqual(payload["description"], "ランチ")
        self.assertEqual(payload["usage_categories_id"], 2)
        self.assertEqual(payload["tax_categories_id"], 3)

    def test_build_expense_update_payload_rejects_zero_amount_boundary(self):
        with self.assertRaises(ValueError):
            build_expense_update_payload(
                expense_id=10,
                payment_date_value=date(2026, 4, 3),
                currency_code="USD",
                amount=0,
                exchange_rate=0.006,
                payment_method="現金",
                description="Lunch",
                usage_category_id=2,
                tax_category_id=3,
            )

    def test_build_expense_update_payload_rejects_invalid_category_id(self):
        with self.assertRaises(ValueError):
            build_expense_update_payload(
                expense_id=10,
                payment_date_value=date(2026, 4, 3),
                currency_code="USD",
                amount=100,
                exchange_rate=0.006,
                payment_method="現金",
                description="Lunch",
                usage_category_id=None,
                tax_category_id=3,
            )

    def test_build_expense_update_payload_rejects_blank_currency_boundary(self):
        with self.assertRaises(ValueError):
            build_expense_update_payload(
                expense_id=10,
                payment_date_value=date(2026, 4, 3),
                currency_code=" ",
                amount=100,
                exchange_rate=0.006,
                payment_method="現金",
                description="Lunch",
                usage_category_id=2,
                tax_category_id=3,
            )

    def test_build_bulk_expense_edit_frame_builds_rowwise_editor_source(self):
        selected_expenses_df = pd.DataFrame(
            [
                {
                    "id": 10,
                    "payment_date": "2026/04/01",
                    "currency_code": "usd",
                    "amount": 100.0,
                    "exchange_rate": 20.0,
                    "amount_base": 2000,
                    "payment_method": "現金",
                    "description": "朝食",
                    "usage_categories_id": 1,
                    "tax_categories_id": 3,
                },
                {
                    "id": 20,
                    "payment_date": "2026/04/02",
                    "currency_code": "JPY",
                    "amount": 150.0,
                    "exchange_rate": 21.0,
                    "amount_base": 3150,
                    "payment_method": "WISE",
                    "description": "昼食",
                    "usage_categories_id": 2,
                    "tax_categories_id": 4,
                },
            ]
        )

        editable_df = build_bulk_expense_edit_frame(
            selected_expenses_df,
            {"食費": 1, "交通": 2},
            {"課税": 3, "非課税": 4},
        )

        self.assertEqual(editable_df.loc[0, "ID"], 10)
        self.assertEqual(editable_df.loc[0, "支払日"], date(2026, 4, 1))
        self.assertEqual(editable_df.loc[0, "通貨"], "USD")
        self.assertEqual(editable_df.loc[0, "用途カテゴリ"], "食費")
        self.assertEqual(editable_df.loc[1, "税務カテゴリ"], "非課税")
        self.assertEqual(editable_df.loc[1, "金額"], 150.0)
        self.assertEqual(editable_df.loc[1, "為替レート"], 21.0)

    def test_build_bulk_expense_update_plan_builds_preview_and_payloads(self):
        original_expenses_df = pd.DataFrame(
            [
                {
                    "id": 10,
                    "payment_date": "2026/04/01",
                    "currency_code": "USD",
                    "amount": 100.0,
                    "exchange_rate": 20.0,
                    "amount_base": 2000,
                    "payment_method": "現金",
                    "description": "朝食",
                    "usage_categories_id": 1,
                    "tax_categories_id": 3,
                },
                {
                    "id": 20,
                    "payment_date": "2026/04/02",
                    "currency_code": "JPY",
                    "amount": 150.0,
                    "exchange_rate": 21.0,
                    "amount_base": 3150,
                    "payment_method": "WISE",
                    "description": "昼食",
                    "usage_categories_id": 2,
                    "tax_categories_id": 4,
                },
            ]
        )

        edited_expenses_df = pd.DataFrame(
            [
                {
                    "ID": 10,
                    "支払日": date(2026, 4, 5),
                    "通貨": "eur",
                    "決済方法": "クレジットカード",
                    "用途カテゴリ": "交通",
                    "税務カテゴリ": "非課税",
                    "内容": "交通費",
                    "金額": 300.0,
                    "為替レート": 22.5,
                },
                {
                    "ID": 20,
                    "支払日": date(2026, 4, 2),
                    "通貨": "JPY",
                    "決済方法": "WISE",
                    "用途カテゴリ": "交通",
                    "税務カテゴリ": "非課税",
                    "内容": "昼食",
                    "金額": 200.0,
                    "為替レート": 21.0,
                },
            ]
        )

        update_plan, preview_df = build_bulk_expense_update_plan(
            original_expenses_df,
            edited_expenses_df,
            {"食費": 1, "交通": 2},
            {"課税": 3, "非課税": 4},
        )

        self.assertEqual(
            update_plan,
            [
                (
                    10,
                    {
                        "payment_date": "2026/04/05",
                        "currency_code": "EUR",
                        "payment_method": "クレジットカード",
                        "description": "交通費",
                        "amount": 300.0,
                        "exchange_rate": 22.5,
                        "amount_base": 6750,
                        "usage_categories_id": 2,
                        "tax_categories_id": 4,
                    },
                ),
                (
                    20,
                    {
                        "amount": 200.0,
                        "amount_base": 4200,
                    },
                ),
            ],
        )
        self.assertEqual(preview_df.loc[0, "通貨(変更前)"], "USD")
        self.assertEqual(preview_df.loc[0, "通貨(変更後)"], "EUR")
        self.assertEqual(preview_df.loc[0, "為替レート(変更後)"], 22.5)
        self.assertEqual(preview_df.loc[0, "用途カテゴリ(変更前)"], "食費")
        self.assertEqual(preview_df.loc[0, "用途カテゴリ(変更後)"], "交通")
        self.assertEqual(preview_df.loc[0, "支払日(変更後)"], "2026-04-05")
        self.assertEqual(preview_df.loc[1, "金額(変更後)"], 200.0)
        self.assertEqual(preview_df.loc[1, "円換算額(変更後)"], 4200)

    def test_build_bulk_expense_update_plan_rejects_zero_selected_rows_boundary(self):
        with self.assertRaises(ValueError):
            build_bulk_expense_update_plan(
                pd.DataFrame(),
                pd.DataFrame([{"ID": 10}]),
                {"食費": 1},
                {"課税": 3},
            )

    def test_build_bulk_expense_update_plan_rejects_no_changes(self):
        with self.assertRaises(ValueError):
            build_bulk_expense_update_plan(
                pd.DataFrame(
                    [
                        {
                            "id": 10,
                            "payment_date": "2026/04/01",
                            "currency_code": "USD",
                            "amount": 100.0,
                            "exchange_rate": 20.0,
                            "payment_method": "現金",
                            "description": "朝食",
                            "usage_categories_id": 1,
                            "tax_categories_id": 3,
                        }
                    ]
                ),
                pd.DataFrame(
                    [
                        {
                            "ID": 10,
                            "支払日": date(2026, 4, 1),
                            "通貨": "USD",
                            "決済方法": "現金",
                            "用途カテゴリ": "食費",
                            "税務カテゴリ": "課税",
                            "内容": "朝食",
                            "金額": 100.0,
                            "為替レート": 20.0,
                        }
                    ]
                ),
                {"食費": 1},
                {"課税": 3},
            )

    def test_build_bulk_expense_update_plan_rejects_zero_amount_boundary(self):
        with self.assertRaises(ValueError):
            build_bulk_expense_update_plan(
                pd.DataFrame(
                    [
                        {
                            "id": 10,
                            "payment_date": "2026/04/01",
                            "currency_code": "USD",
                            "amount": 100.0,
                            "exchange_rate": 20.0,
                            "payment_method": "現金",
                            "description": "朝食",
                            "usage_categories_id": 1,
                            "tax_categories_id": 3,
                        }
                    ]
                ),
                pd.DataFrame(
                    [
                        {
                            "ID": 10,
                            "支払日": date(2026, 4, 1),
                            "通貨": "USD",
                            "決済方法": "現金",
                            "用途カテゴリ": "食費",
                            "税務カテゴリ": "課税",
                            "内容": "朝食",
                            "金額": 0.0,
                            "為替レート": 20.0,
                        }
                    ]
                ),
                {"食費": 1},
                {"課税": 3},
            )

    def test_build_bulk_expense_update_plan_rejects_invalid_exchange_rate(self):
        with self.assertRaises(ValueError):
            build_bulk_expense_update_plan(
                pd.DataFrame(
                    [
                        {
                            "id": 10,
                            "payment_date": "2026/04/01",
                            "currency_code": "USD",
                            "amount": 50.0,
                            "exchange_rate": 10.0,
                            "payment_method": "現金",
                            "description": "朝食",
                            "usage_categories_id": 1,
                            "tax_categories_id": 3,
                        }
                    ]
                ),
                pd.DataFrame(
                    [
                        {
                            "ID": 10,
                            "支払日": date(2026, 4, 1),
                            "通貨": "USD",
                            "決済方法": "現金",
                            "用途カテゴリ": "食費",
                            "税務カテゴリ": "課税",
                            "内容": "朝食",
                            "金額": 100.0,
                            "為替レート": 0.0,
                        }
                    ]
                ),
                {"食費": 1},
                {"課税": 3},
            )

    def test_build_bulk_expense_update_plan_rejects_blank_currency_boundary(self):
        with self.assertRaises(ValueError):
            build_bulk_expense_update_plan(
                pd.DataFrame(
                    [
                        {
                            "id": 10,
                            "payment_date": "2026/04/01",
                            "currency_code": "USD",
                            "amount": 50.0,
                            "exchange_rate": 10.0,
                            "payment_method": "現金",
                            "description": "朝食",
                            "usage_categories_id": 1,
                            "tax_categories_id": 3,
                        }
                    ]
                ),
                pd.DataFrame(
                    [
                        {
                            "ID": 10,
                            "支払日": date(2026, 4, 1),
                            "通貨": " ",
                            "決済方法": "現金",
                            "用途カテゴリ": "食費",
                            "税務カテゴリ": "課税",
                            "内容": "朝食",
                            "金額": 50.0,
                            "為替レート": 10.0,
                        }
                    ]
                ),
                {"食費": 1},
                {"課税": 3},
            )

    def test_update_expense_record_filters_by_id_and_user_id(self):
        fake_query = _FakeExpenseQuery()
        fake_client = _FakeSupabaseClient(fake_query)

        with patch("utils.expense_db.get_supabase_client", return_value=fake_client):
            update_expense_record(10, "user-1", {"description": "Updated lunch"})

        self.assertEqual(fake_client.table_names, ["expenses"])
        self.assertEqual(fake_query.update_payload, {"description": "Updated lunch"})
        self.assertEqual(fake_query.conditions, [("id", 10), ("auth_user_id", "user-1")])

    def test_build_wechat_expense_records_imports_only_success_rows(self):
        file_content = self._make_wechat_xlsx_bytes(
            [
                ["微信支付账单明细"],
                ["----------------------微信支付账单明细列表--------------------"],
                ["交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)", "支付方式", "当前状态", "交易单号", "商户单号", "备注"],
                ["2026-03-15 22:17:23", "商户消费", "云宝宝", "南宁地铁-乘车", "支出", "3.4", "MASTERCARD(4035)", "支付成功", "1", "2", "/"],
                ["2026-03-16 10:00:00", "转账", "友人", "午餐", "支出", "8", "零钱", "已全额退款", "3", "4", "/"],
            ]
        )

        records = build_wechat_expense_records(
            file_content,
            "user-1",
            exchange_rate_provider=lambda payment_date_value: 20.5,
        )

        self.assertEqual(
            records,
            [
                {
                    "payment_date": "2026/03/15",
                    "currency_code": "CNY",
                    "amount": 3.4,
                    "exchange_rate": 20.5,
                    "amount_base": 70,
                    "payment_method": "クレジットカード",
                    "description": "云宝宝/南宁地铁-乘车/商户消费",
                    "usage_categories_id": None,
                    "tax_categories_id": None,
                    "auth_user_id": "user-1",
                }
            ],
        )

    def test_build_wechat_expense_records_returns_empty_when_no_success_status_boundary(self):
        file_content = self._make_wechat_xlsx_bytes(
            [
                ["交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)", "支付方式", "当前状态"],
                ["2026-03-15 22:17:23", "商户消费", "云宝宝", "/", "支出", "3.4", "零钱", "已全额退款"],
            ]
        )

        self.assertEqual(build_wechat_expense_records(file_content, "user-1"), [])

    def test_build_wechat_expense_records_uses_fixed_cny_to_jpy_rate_by_default(self):
        file_content = self._make_wechat_xlsx_bytes(
            [
                ["交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)", "支付方式", "当前状态"],
                ["2026-03-15 22:17:23", "商户消费", "云宝宝", "南宁地铁-乘车", "支出", "3", "零钱", "支付成功"],
            ]
        )

        records = build_wechat_expense_records(file_content, "user-1")

        self.assertEqual(records[0]["exchange_rate"], 21.0)
        self.assertEqual(records[0]["amount_base"], 63)

    def test_build_wechat_expense_records_rejects_invalid_xlsx(self):
        with self.assertRaises(ValueError):
            build_wechat_expense_records(b"not-xlsx", "user-1")

    def test_build_wechat_expense_records_infers_categories_from_existing_descriptions(self):
        file_content = self._make_wechat_xlsx_bytes(
            [
                ["交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)", "支付方式", "当前状态"],
                ["2026-03-15 22:17:23", "商户消费", "云宝宝", "南宁地铁-乘车_2026-03-15 23:17:11", "支出", "3", "零钱", "支付成功"],
            ]
        )
        existing_expenses_df = pd.DataFrame(
            [
                {
                    "description": "云宝宝/南宁地铁-乘车/商户消费",
                    "usage_categories_id": 2,
                    "tax_categories_id": 5,
                }
            ]
        )

        records = build_wechat_expense_records(
            file_content,
            "user-1",
            existing_expenses_df=existing_expenses_df,
        )

        self.assertEqual(records[0]["usage_categories_id"], 2)
        self.assertEqual(records[0]["tax_categories_id"], 5)

    def test_insert_expense_records_inserts_bulk_payload(self):
        fake_query = _FakeExpenseQuery()
        fake_client = _FakeSupabaseClient(fake_query)
        records = [{"payment_date": "2026/03/15", "amount": 3.4}]

        with patch("utils.expense_db.get_supabase_client", return_value=fake_client):
            insert_expense_records(records)

        self.assertEqual(fake_client.table_names, ["expenses"])
        self.assertEqual(fake_query.insert_payload, records)

    def test_build_expense_record_includes_receipt_storage_path(self):
        record = build_expense_record(
            payment_date_value=date(2026, 4, 5),
            currency_code="VND",
            amount=1000,
            exchange_rate=0.006,
            amount_base=6,
            payment_method="現金",
            description="ランチ",
            usage_category_id=1,
            tax_category_id=2,
            auth_user_id="user-1",
            receipt_storage_path="user-1/2026/04/20260405_token.jpg",
        )

        self.assertEqual(
            record["receipt_storage_path"],
            "user-1/2026/04/20260405_token.jpg",
        )

    def test_build_receipt_storage_path_falls_back_to_jpg_for_missing_extension(self):
        self.assertEqual(
            build_receipt_storage_path(
                auth_user_id="user-1",
                payment_date_value=date(2026, 4, 5),
                original_file_name="receipt",
                unique_token="token",
            ),
            "user-1/2026/04/20260405_token.jpg",
        )

    def test_upload_expense_receipt_uploads_to_expense_receipts_bucket(self):
        fake_query = _FakeExpenseQuery()
        fake_client = _FakeSupabaseClient(fake_query)

        with patch("utils.expense_db.get_supabase_client", return_value=fake_client), patch(
            "utils.expense_db.uuid4"
        ) as fake_uuid4:
            fake_uuid4.return_value.hex = "fixedtoken"
            storage_path = upload_expense_receipt(
                file_content=b"image-bytes",
                original_file_name="receipt.png",
                content_type="image/png",
                payment_date_value=date(2026, 4, 5),
                auth_user_id="user-1",
            )

        self.assertEqual(fake_client.storage.bucket_names, ["expense-receipts"])
        self.assertEqual(storage_path, "user-1/2026/04/20260405_fixedtoken.png")
        self.assertEqual(
            fake_client.storage.bucket.upload_calls,
            [
                {
                    "path": "user-1/2026/04/20260405_fixedtoken.png",
                    "file_content": b"image-bytes",
                    "file_options": {"content-type": "image/png"},
                }
            ],
        )

    def test_upload_expense_receipt_rejects_empty_file_content(self):
        with self.assertRaises(ValueError):
            upload_expense_receipt(
                file_content=b"",
                original_file_name="receipt.png",
                content_type="image/png",
                payment_date_value=date(2026, 4, 5),
                auth_user_id="user-1",
            )


if __name__ == "__main__":
    unittest.main()
