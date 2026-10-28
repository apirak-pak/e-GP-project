import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from app import capture_dga as capture


class RawCaptureTests(unittest.TestCase):
    def args(self):
        return argparse.Namespace(year=2569, keyword="จ้างก่อสร้าง", limit=20, offset=0)

    def test_raw_project_preserved_and_echoed_key_redacted_in_new_db(self):
        secret = "test-secret-32-characters-abcdefg"
        project = {"project_id": "69100000001", "project_status": "ระหว่างดำเนินการ",
                   "announce_date": "1 ต.ค. 69", "province": "เชียงใหม่",
                   "unused_new_field": {"original": True},
                   "contract": [{"contract_date": "2 ต.ค. 69", "price_agree": 0}]}
        body = json.dumps({"success": True, "request": {"api-key": secret},
                           "total": 1, "data": [project]}, ensure_ascii=False).encode()
        response = MagicMock()
        response.status = 200
        response.read.return_value = body
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(capture, "ROOT", root), patch.object(capture, "RAW_ROOT", root / "data/dga_raw"), \
                    patch.object(capture, "read_key", return_value=secret), \
                    patch.object(capture, "build_opener", return_value=opener):
                folder, manifest = capture.capture(self.args())
            saved = (folder / "response.json").read_bytes()
            self.assertEqual(saved, body.replace(secret.encode(), b"[REDACTED_API_KEY]"))
            self.assertEqual(json.loads(saved)["data"][0], project)
            self.assertTrue(manifest["credential_redacted"])
            self.assertFalse(manifest["mapped_or_imported"])
            self.assertFalse((root / "data/egp.db").exists())
            with closing(sqlite3.connect(root / "data/dga_explore.db")) as conn:
                saved_body = conn.execute("SELECT response_body FROM dga_raw_captures").fetchone()[0]
                saved_project = json.loads(conn.execute("SELECT raw_json FROM dga_raw_projects").fetchone()[0])
                self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE name='projects'").fetchone(), None)
            self.assertEqual(saved_body, saved)
            self.assertEqual(saved_project, project)
            opener.open.assert_called_once()
            for file in root.rglob("*"):
                if file.is_file():
                    self.assertNotIn(secret.encode(), file.read_bytes())

    def test_inventory_keeps_nested_fields_and_zero_values(self):
        rows = [{"extra": None, "contract": [{"price": 0, "status": "A"}, {"price": 3}]},
                {"extra": False, "contract": []}]
        fields = {item["path"]: item for item in capture.field_inventory(rows)}
        self.assertEqual(fields["contract[].price"]["examples"], [0, 3])
        self.assertEqual(fields["contract[].price"]["nonempty_occurrences"], 2)
        self.assertEqual(fields["extra"]["types"], {"null": 1, "boolean": 1})
        self.assertEqual(fields["extra"]["nonempty_occurrences"], 1)

    def test_http_failure_does_not_save_response_or_retry(self):
        opener = MagicMock()
        opener.open.side_effect = HTTPError("https://example.invalid/?secret=do-not-log", 429, "Limit", {}, None)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(capture, "ROOT", root), patch.object(capture, "RAW_ROOT", root / "data/dga_raw"), \
                    patch.object(capture, "read_key", return_value="fake-key"), \
                    patch.object(capture, "build_opener", return_value=opener):
                with self.assertRaisesRegex(ValueError, "HTTP 429") as caught:
                    capture.capture(self.args())
            self.assertNotIn("do-not-log", str(caught.exception))
            self.assertFalse((root / "data/dga_raw").exists())
            self.assertFalse((root / "data/dga_explore.db").exists())
            opener.open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
