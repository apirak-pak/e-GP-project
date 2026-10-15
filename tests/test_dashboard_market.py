import sqlite3
import unittest
from unittest.mock import patch

from app import server


class DashboardMarketTests(unittest.TestCase):
    def test_winner_share_counts_projects_in_selected_agency_provinces(self):
        projects = [
            ("CM-1", "เชียงใหม่", "ทำสัญญาแล้ว", "บริษัท ก", None),
            ("CM-2", "เชียงใหม่", "ทำสัญญาแล้ว", "บริษัท ก", 10),
            ("CM-3", "เชียงใหม่", "ประกาศผู้ชนะ", "บริษัท ข", 1000),
            ("LP-1", "ลำพูน", "ทำสัญญาแล้ว", "บริษัท ข", 100),
            ("CR-1", "เชียงราย", "ทำสัญญาแล้ว", "บริษัท ค", 100),
            ("CM-4", "เชียงใหม่", "ประกาศใหม่", "", None),
            ("CM-5", "เชียงใหม่", "ทำสัญญาแล้ว", "", 200),
        ]
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            with patch.object(server, "connect", return_value=conn):
                server.init_db()
                with conn:
                    conn.executemany(server.UPSERT_SQL, [
                        server.validate_project({
                            "project_id": project_id,
                            "title": "งานทดสอบ",
                            "province": province,
                            "agency_province": province,
                            "status": status,
                            "winner": winner,
                            "winning_price": price,
                        })
                        for project_id, province, status, winner, price in projects
                    ])

                chiang_mai = server.dashboard({"province": ["เชียงใหม่"]})
                self.assertEqual(chiang_mai["summary"]["count"], 5)
                self.assertEqual(chiang_mai["summary"]["share_project_total"], 3)
                self.assertEqual(chiang_mai["summary"]["excluded_winner_count"], 1)
                self.assertEqual(
                    [(row["winner"], row["count"], row["percent"]) for row in chiang_mai["shares"]],
                    [("บริษัท ก", 2, 66.7), ("บริษัท ข", 1, 33.3)],
                )

                nearby = server.dashboard({"province": ["เชียงใหม่", "ลำพูน"]})
                self.assertEqual(nearby["summary"]["count"], 6)
                self.assertEqual(nearby["summary"]["share_project_total"], 4)
                self.assertEqual(nearby["filters"]["provinces"], ["เชียงใหม่", "ลำพูน"])
                self.assertEqual(
                    [(row["winner"], row["count"], row["percent"]) for row in nearby["shares"]],
                    [("บริษัท ก", 2, 50.0), ("บริษัท ข", 2, 50.0)],
                )
        finally:
            conn.close()

    def test_winner_projects_filter_agency_province_even_when_work_is_elsewhere_or_unknown(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            with patch.object(server, "connect", return_value=conn):
                server.init_db()
                with conn:
                    conn.executemany(server.UPSERT_SQL, [
                        server.validate_project({
                            "project_id": project_id,
                            "title": "งานก่อสร้าง",
                            "province": work_province,
                            "agency_province": agency_province,
                            "status": "ทำสัญญาแล้ว",
                            "winner": "บริษัท ก",
                            "budget": budget,
                            "winning_price": price,
                        })
                        for project_id, work_province, agency_province, budget, price in [
                            ("CM-1", "เชียงใหม่", "กรุงเทพมหานคร", 150, 100),
                            ("CM-2", "เชียงใหม่", "กรุงเทพมหานคร", 50, None),
                            ("BK-1", "กรุงเทพมหานคร", "เชียงใหม่", 300, 200),
                            ("UN-1", server.UNKNOWN_PROVINCE, "เชียงใหม่", 80, None),
                        ]
                    ])
                result = server.winner_projects({"province": ["เชียงใหม่"], "winner": ["บริษัท ก"]})
                self.assertEqual(result["summary"]["count"], 2)
                self.assertEqual(result["summary"]["priced_count"], 1)
                self.assertEqual(result["summary"]["winning_price_total"], 200)
                self.assertEqual({row["province"] for row in result["projects"]}, {"กรุงเทพมหานคร", server.UNKNOWN_PROVINCE})
                self.assertEqual({row["agency_province"] for row in result["projects"]}, {"เชียงใหม่"})
                dashboard = server.dashboard({"province": ["เชียงใหม่"]})
                self.assertEqual(dashboard["summary"]["count"], 2)
                self.assertEqual(dashboard["summary"]["province_count"], 1)
                self.assertEqual(dashboard["summary"]["unknown_work_province_count"], 1)
                self.assertEqual(dashboard["meta"]["province_counts"]["เชียงใหม่"], 2)
        finally:
            conn.close()

    def test_project_list_has_fifty_rows_per_page(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            with patch.object(server, "connect", return_value=conn):
                server.init_db()
                with conn:
                    conn.executemany(server.UPSERT_SQL, [
                        server.validate_project({
                            "project_id": f"P-{index:03d}",
                            "title": "งานทดสอบ",
                            "province": "เชียงใหม่",
                            "status": "ประกาศใหม่",
                        })
                        for index in range(55)
                    ])
                first = server.dashboard({})
                second = server.dashboard({"offset": ["50"]})
                self.assertEqual(first["pagination"]["total"], 55)
                self.assertEqual(len(first["projects"]), 50)
                self.assertEqual(second["pagination"]["offset"], 50)
                self.assertEqual(len(second["projects"]), 5)
                self.assertFalse({row["project_id"] for row in first["projects"]} &
                                 {row["project_id"] for row in second["projects"]})
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
