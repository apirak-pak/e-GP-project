import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from egp_live import server


URL = ("https://process5.gprocurement.go.th/egp-oann10-service/pb/"
       "a-egp-allt-project/announcement?budgetYear=2569&moiId=500000&"
       "methodId=16&typeId=02&announcementTodayFlag=false&page=1")
ROW = {"projectId": "69109071515", "projectName": "ประกวดราคาจ้างก่อสร้างอาคาร",
       "deptSubName": "มหาวิทยาลัยเชียงใหม่", "deptName": "มหาวิทยาลัยเชียงใหม่",
       "flowName": "หนังสือเชิญชวน/ประกาศเชิญชวน", "projectMoney": "2360000.00",
       "budgetYear": 2569, "provinceName": "เชียงใหม่", "extraField": {"value": "เก็บไว้"}}


class EgpLiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=server.ROOT / "data")
        self.db = Path(self.temp.name) / "egp_live.db"
        self.patch = patch.object(server, "DB", self.db)
        self.patch.start()
        server.init_db()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_page_keeps_full_json_and_upserts_project(self):
        result = server.ingest({"source_url": URL, "response": {"data": [ROW]}})
        self.assertEqual(result["saved"], 1)
        server.ingest({"source_url": URL, "response": {"data": [{**ROW, "flowName": "ประกาศผู้ชนะ"}]}})
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM api_pages").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 1)
            raw = json.loads(conn.execute("SELECT raw_json FROM projects").fetchone()[0])
            self.assertEqual(raw["extraField"]["value"], "เก็บไว้")
            self.assertEqual(raw["flowName"], "ประกาศผู้ชนะ")

    def test_rejected_response_never_writes_page(self):
        with self.assertRaisesRegex(ValueError, "ยืนยันตัวตน"):
            server.ingest({"source_url": URL, "response": {"validateCfTurnTile": False}})
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM api_pages").fetchone()[0], 0)

    def test_authentication_query_is_not_persisted(self):
        with self.assertRaisesRegex(ValueError, "ตัวกรอง"):
            server.ingest({"source_url": URL + "&announcementToken=secret", "response": {"data": [ROW]}})
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM api_pages").fetchone()[0], 0)

    def test_nested_authentication_field_is_not_persisted(self):
        with self.assertRaisesRegex(ValueError, "ข้อมูลยืนยันตัวตน"):
            server.ingest({"source_url": URL, "response": {"data": [{**ROW, "extraField": {"apiKey": "secret"}}]}})
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM api_pages").fetchone()[0], 0)

    def test_coverage_resumes_after_latest_page_and_marks_empty_as_complete(self):
        server.ingest({"source_url": URL, "response": {"data": [ROW]}})
        server.ingest({"source_url": URL, "response": {"data": [ROW]}})
        coverage = server.state({"year": ["2569"]})["coverage"][0]
        self.assertEqual((coverage["next_page"], coverage["rows_received"]), (2, 1))
        self.assertFalse(coverage["complete"])
        server.ingest({"source_url": URL.replace("page=1", "page=2"), "response": {"data": []}})
        coverage = server.state({"year": ["2569"]})["coverage"][0]
        self.assertEqual((coverage["empty_page"], coverage["next_page"]), (2, 3))
        self.assertTrue(coverage["complete"])


if __name__ == "__main__":
    unittest.main()
