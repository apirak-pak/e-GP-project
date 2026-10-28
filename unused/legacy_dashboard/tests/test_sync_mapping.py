import unittest

from app.server import CSV_FIELDS
from app.location import UNKNOWN_PROVINCE, project_province_from_title
from app.sync_egp import thai_date, to_project


class SyncMappingTests(unittest.TestCase):
    def test_thai_buddhist_date(self):
        self.assertEqual(thai_date("21 มิ.ย. 67"), "2024-06-21")
        self.assertEqual(thai_date("12 ธ.ค. 2567"), "2024-12-12")

    def test_project_area_uses_explicit_title_not_agency_province(self):
        self.assertEqual(project_province_from_title("ก่อสร้างถนน จ.เชียงใหม่"), "เชียงใหม่")
        self.assertEqual(project_province_from_title("ก่อสร้างจาก จ.เชียงใหม่ ถึง จ.ลำพูน"), UNKNOWN_PROVINCE)
        self.assertEqual(project_province_from_title("ก่อสร้างถนนสายหลัก"), UNKNOWN_PROVINCE)

    def test_multiple_winners_are_excluded_from_share(self):
        project = {
            "project_id": "TEST-1",
            "project_name": "จ้างก่อสร้าง",
            "province": "เชียงใหม่",
            "project_status": "ระหว่างดำเนินการ",
            "sum_price_agree": 30_000_000,
            "contract": [
                {"winner_name": "บริษัท ก", "price_agree": 10_000_000},
                {"winner_name": "บริษัท ข", "price_agree": 20_000_000},
            ],
        }
        row = dict(zip(CSV_FIELDS, to_project(project)))
        self.assertEqual(row["status"], "ทำสัญญาแล้ว")
        self.assertEqual(row["winner"], "")
        self.assertIsNone(row["winning_price"])


if __name__ == "__main__":
    unittest.main()
