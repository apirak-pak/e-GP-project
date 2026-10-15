"""Local e-GP dashboard with SQLite or Supabase PostgreSQL storage."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import sqlite3
from datetime import date, datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.location import PROVINCES, UNKNOWN_PROVINCE, project_province_from_title
from app.db import backend, connect_postgres


ROOT = Path(__file__).resolve().parent.parent
WEB = Path(__file__).resolve().parent / "web"
DATA = ROOT / "data"
DB = DATA / "egp.db"
HOST = "127.0.0.1"  # Local prototype: do not expose to a network without authentication.
PORT = 8501
PAGE_SIZE = 50

STATUSES = (
    "ประกาศใหม่",
    "ระหว่างประมูล",
    "ประกาศผู้ชนะ",
    "ทำสัญญาแล้ว",
    "ยกเลิก",
    "ไม่ทราบสถานะ",
)
PRICE_FIELDS = {
    "budget": "budget",
    "reference_price": "reference_price",
    "winning_price": "winning_price",
}
REQUIRED_CSV = {"project_id", "title", "province", "status"}
CSV_FIELDS = [
    "project_id", "title", "province", "project_type", "agency", "status",
    "budget", "reference_price", "winning_price", "winner",
    "announced_at", "source_url",
]


def connect() -> sqlite3.Connection | object:
    if backend() == "postgres":
        return connect_postgres()
    DATA.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    if backend() == "postgres":
        from app.schema_postgres import init_db_postgres
        init_db_postgres()
        return
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                province TEXT NOT NULL,
                project_type TEXT NOT NULL DEFAULT '',
                agency TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                budget REAL,
                reference_price REAL,
                winning_price REAL,
                winner TEXT NOT NULL DEFAULT '',
                announced_at TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                is_demo INTEGER NOT NULL DEFAULT 0,
                source_kind TEXT NOT NULL DEFAULT 'manual',
                source_name TEXT NOT NULL DEFAULT '',
                agency_province TEXT NOT NULL DEFAULT '',
                province_source TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_province ON projects(province)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status)")
        # Existing local databases from the first prototype are upgraded in place.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
        if "source_kind" not in columns:
            conn.execute("ALTER TABLE projects ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'manual'")
        if "source_name" not in columns:
            conn.execute("ALTER TABLE projects ADD COLUMN source_name TEXT NOT NULL DEFAULT ''")
        if "agency_province" not in columns:
            conn.execute("ALTER TABLE projects ADD COLUMN agency_province TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_agency_province ON projects(agency_province)")
        if "province_source" not in columns:
            conn.execute("ALTER TABLE projects ADD COLUMN province_source TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE projects SET source_kind='demo', source_name='sample_projects.csv' WHERE is_demo=1 AND source_kind='manual'")
        for legacy in conn.execute(
            "SELECT project_id, title, province FROM projects WHERE source_kind='api' AND province_source=''"
        ).fetchall():
            location = project_province_from_title(legacy["title"])
            conn.execute(
                "UPDATE projects SET province=?, agency_province=?, province_source=? WHERE project_id=?",
                (location, legacy["province"], "title" if location != UNKNOWN_PROVINCE else "unknown", legacy["project_id"]),
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS import_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL,
                file_sha256 TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                created_count INTEGER NOT NULL,
                updated_count INTEGER NOT NULL,
                imported_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT NOT NULL,
                fiscal_year INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                result_total INTEGER NOT NULL,
                fetched_count INTEGER NOT NULL,
                saved_count INTEGER NOT NULL,
                skipped_count INTEGER NOT NULL,
                synced_at TEXT NOT NULL
            )
            """
        )


def text_field(value: object, name: str, *, required: bool = False, maximum: int = 300) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ValueError(f"ต้องระบุ {name}")
    if len(result) > maximum:
        raise ValueError(f"{name} ยาวเกิน {maximum} ตัวอักษร")
    return result


def money_field(value: object, name: str) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        result = float(str(value).replace(",", "").strip())
    except ValueError as exc:
        raise ValueError(f"{name} ต้องเป็นตัวเลข") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} ต้องเป็นตัวเลขตั้งแต่ 0 ขึ้นไป")
    return result


def validate_project(
    raw: dict, *, is_demo: bool = False, source_kind: str = "manual", source_name: str = ""
) -> tuple:
    project_id = text_field(raw.get("project_id"), "รหัสโครงการ", required=True, maximum=80)
    if project_id.startswith("DEMO-") and not is_demo:
        raise ValueError("รหัสที่ขึ้นต้น DEMO- สงวนไว้สำหรับข้อมูลตัวอย่าง")
    title = text_field(raw.get("title"), "ชื่อโครงการ", required=True, maximum=500)
    province = text_field(raw.get("province"), "จังหวัด", required=True, maximum=100)
    project_type = text_field(raw.get("project_type"), "ประเภทงาน", maximum=100)
    agency = text_field(raw.get("agency"), "หน่วยงาน", maximum=200)
    status = text_field(raw.get("status"), "สถานะ", required=True, maximum=40)
    if status not in STATUSES:
        raise ValueError(f"สถานะต้องเป็นหนึ่งใน: {', '.join(STATUSES)}")
    budget = money_field(raw.get("budget"), "วงเงินงบประมาณ")
    reference_price = money_field(raw.get("reference_price"), "ราคากลาง")
    winning_price = money_field(raw.get("winning_price"), "ราคาที่ชนะ")
    winner = text_field(raw.get("winner"), "ผู้ชนะ", maximum=200)
    announced_at = text_field(raw.get("announced_at"), "วันที่ประกาศ", maximum=10)
    if announced_at:
        try:
            date.fromisoformat(announced_at)
        except ValueError as exc:
            raise ValueError("วันที่ประกาศต้องเป็น YYYY-MM-DD") from exc
    source_url = text_field(raw.get("source_url"), "ลิงก์ต้นทาง", maximum=1000)
    if source_url and urlparse(source_url).scheme not in {"http", "https"}:
        raise ValueError("ลิงก์ต้นทางต้องเริ่มด้วย http:// หรือ https://")
    agency_province = text_field(raw.get("agency_province"), "จังหวัดหน่วยจัดซื้อ", maximum=100)
    if is_demo and not agency_province:
        agency_province = province
    province_source = text_field(raw.get("province_source") or source_kind, "ที่มาของพื้นที่", maximum=40)
    return (
        project_id, title, province, project_type, agency, status, budget,
        reference_price, winning_price, winner, announced_at, source_url,
        int(is_demo), source_kind, source_name, agency_province, province_source,
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


UPSERT_SQL = """
    INSERT INTO projects (
        project_id, title, province, project_type, agency, status, budget,
        reference_price, winning_price, winner, announced_at, source_url,
        is_demo, source_kind, source_name, agency_province, province_source, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(project_id) DO UPDATE SET
        title=excluded.title, province=excluded.province,
        project_type=excluded.project_type, agency=excluded.agency,
        status=excluded.status, budget=excluded.budget,
        reference_price=excluded.reference_price,
        winning_price=excluded.winning_price, winner=excluded.winner,
        announced_at=excluded.announced_at, source_url=excluded.source_url,
        is_demo=excluded.is_demo, source_kind=excluded.source_kind,
        source_name=excluded.source_name, agency_province=excluded.agency_province,
        province_source=excluded.province_source, updated_at=excluded.updated_at
"""


def first_param(params: dict[str, list[str]], key: str) -> str:
    return (params.get(key) or [""])[0].strip()


def page_offset(params: dict[str, list[str]]) -> int:
    try:
        offset = int(first_param(params, "offset") or "0")
    except ValueError as exc:
        raise ValueError("หน้ารายการไม่ถูกต้อง") from exc
    if offset < 0 or offset > 1_000_000:
        raise ValueError("หน้ารายการไม่ถูกต้อง")
    return offset


def project_filter(params: dict[str, list[str]]) -> tuple[str, list[object], list[str]]:
    price_key = first_param(params, "price_field") or "budget"
    if price_key not in PRICE_FIELDS:
        raise ValueError("ชนิดราคาไม่ถูกต้อง")
    price_col = PRICE_FIELDS[price_key]
    conditions = []
    values: list[object] = []
    selected_provinces = list(dict.fromkeys(
        value.strip() for value in params.get("province", []) if value.strip()
    ))
    if len(selected_provinces) > 100:
        raise ValueError("เลือกจังหวัดมากเกินไป")
    if selected_provinces:
        conditions.append(f"agency_province IN ({','.join('?' for _ in selected_provinces)})")
        values.extend(selected_provinces)
    for key, column in (("project_type", "project_type"), ("status", "status")):
        value = first_param(params, key)
        if value:
            conditions.append(f"{column} = ?")
            values.append(value)
    search = first_param(params, "q")
    if search:
        conditions.append("(project_id LIKE ? OR title LIKE ? OR agency LIKE ? OR winner LIKE ?)")
        values.extend([f"%{search}%"] * 4)
    for key, operator in (("min_price", ">="), ("max_price", "<=")):
        if first_param(params, key):
            amount = money_field(first_param(params, key), "ช่วงราคา")
            conditions.append(f"{price_col} {operator} ?")
            values.append(amount)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    return where, values, selected_provinces


def dashboard(params: dict[str, list[str]]) -> dict:
    offset = page_offset(params)
    where, values, selected_provinces = project_filter(params)
    with connect() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM projects" + where + " ORDER BY announced_at DESC, project_id DESC LIMIT ? OFFSET ?",
            [*values, PAGE_SIZE, offset],
        )]
        totals = conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(budget), 0) AS budget_total, "
            "COALESCE(SUM(CASE WHEN province = ? THEN 1 ELSE 0 END), 0) AS unknown_work_province_count, "
            "COALESCE(SUM(CASE WHEN status = 'ประกาศใหม่' THEN 1 ELSE 0 END), 0) AS announced_count, "
            "COALESCE(SUM(CASE WHEN status = 'ระหว่างประมูล' THEN 1 ELSE 0 END), 0) AS bidding_count, "
            "COALESCE(SUM(CASE WHEN status IN ('ประกาศผู้ชนะ', 'ทำสัญญาแล้ว') THEN 1 ELSE 0 END), 0) AS winner_count, "
            "COALESCE(SUM(CASE WHEN status IN ('ประกาศผู้ชนะ', 'ทำสัญญาแล้ว') AND winner = '' "
            "THEN 1 ELSE 0 END), 0) AS excluded_winner_count "
            "FROM projects" + where,
            [UNKNOWN_PROVINCE, *values],
        ).fetchone()
        matching_provinces = {row["agency_province"] for row in conn.execute(
            "SELECT DISTINCT agency_province FROM projects" + where, values
        )}
        all_meta = conn.execute(
            "SELECT COUNT(*) AS total, SUM(is_demo) AS demo_count, MAX(updated_at) AS updated_at FROM projects"
        ).fetchone()
        last_import = conn.execute(
            "SELECT source_name, row_count, created_count, updated_count, imported_at FROM import_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        last_api_sync = conn.execute(
            "SELECT service, fiscal_year, keyword, result_total, fetched_count, saved_count, skipped_count, synced_at "
            "FROM api_sync_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        province_counts = {row["agency_province"]: row["count"] for row in conn.execute(
            "SELECT agency_province, COUNT(*) AS count FROM projects WHERE agency_province <> '' GROUP BY agency_province"
        )}
        unknown_work_province_count = conn.execute(
            "SELECT COUNT(*) AS count FROM projects WHERE province = ?", (UNKNOWN_PROVINCE,)
        ).fetchone()["count"]
        types = [row["project_type"] for row in conn.execute("SELECT DISTINCT project_type FROM projects WHERE project_type <> '' ORDER BY project_type")]
        statuses = [row["status"] for row in conn.execute("SELECT DISTINCT status FROM projects ORDER BY status")]
        api_count = conn.execute("SELECT COUNT(*) AS count FROM projects WHERE source_kind='api'").fetchone()["count"]

        award_condition = "status IN ('ประกาศผู้ชนะ', 'ทำสัญญาแล้ว') AND winner <> ''"
        award_where = where + (" AND " if where else " WHERE ") + award_condition
        real_count = conn.execute(
            "SELECT COUNT(*) AS count FROM projects" + award_where + " AND is_demo = 0", values
        ).fetchone()["count"]
        demo_count = 0 if real_count else conn.execute(
            "SELECT COUNT(*) AS count FROM projects" + award_where + " AND is_demo = 1", values
        ).fetchone()["count"]
        share_project_total = real_count or demo_count
        share_where = award_where + " AND is_demo = ?"
        share_values = [*values, 0 if real_count else 1]
        share_winner_total = conn.execute(
            "SELECT COUNT(DISTINCT winner) AS count FROM projects" + share_where, share_values
        ).fetchone()["count"] if share_project_total else 0
        shares = [dict(row) for row in conn.execute(
            "SELECT winner, COUNT(*) AS count FROM projects" + share_where +
            " GROUP BY winner ORDER BY count DESC, winner LIMIT 10", share_values
        )] if share_project_total else []

    known_provinces = set(PROVINCES)
    province_options = list(PROVINCES)
    province_options.extend(sorted(p for p in province_counts if p not in known_provinces))

    for item in shares:
        item["percent"] = round(item["count"] / share_project_total * 100, 1) if share_project_total else 0
    return {
        "filters": {"provinces": selected_provinces},
        "projects": rows,
        "pagination": {
            "offset": offset,
            "page_size": PAGE_SIZE,
            "total": totals["count"],
            "has_more": offset + PAGE_SIZE < totals["count"],
        },
        "summary": {
            "count": totals["count"],
            "budget_total": totals["budget_total"],
            "province_count": len(matching_provinces & known_provinces),
            "unknown_work_province_count": totals["unknown_work_province_count"],
            "announced_count": totals["announced_count"],
            "bidding_count": totals["bidding_count"],
            "winner_count": totals["winner_count"],
            "share_project_total": share_project_total,
            "share_winner_total": share_winner_total,
            "share_is_demo": not real_count and bool(demo_count),
            "excluded_winner_count": totals["excluded_winner_count"],
        },
        "shares": shares[:10],
        "meta": {
            "total_in_database": all_meta["total"],
            "demo_count": all_meta["demo_count"] or 0,
            "updated_at": all_meta["updated_at"],
            "last_import": dict(last_import) if last_import else None,
            "last_api_sync": dict(last_api_sync) if last_api_sync else None,
            "api_count": api_count,
            "covered_province_count": sum(province_counts.get(p, 0) > 0 for p in PROVINCES),
            "unknown_work_province_count": unknown_work_province_count,
            "province_counts": province_counts,
            "provinces": province_options,
            "province_reference": list(PROVINCES),
            "project_types": types,
            "statuses": statuses or STATUSES,
        },
    }


def winner_projects(params: dict[str, list[str]]) -> dict:
    winner = first_param(params, "winner")
    if not winner or len(winner) > 200:
        raise ValueError("ต้องระบุชื่อผู้ชนะ")
    offset = page_offset(params)
    where, values, selected_provinces = project_filter(params)
    award_filter = " AND status IN ('ประกาศผู้ชนะ', 'ทำสัญญาแล้ว') AND winner <> ''" if where else " WHERE status IN ('ประกาศผู้ชนะ', 'ทำสัญญาแล้ว') AND winner <> ''"
    with connect() as conn:
        has_real = conn.execute(
            "SELECT 1 FROM projects" + where + award_filter + " AND is_demo = 0 LIMIT 1", values
        ).fetchone() is not None
        winner_filter = award_filter + " AND is_demo = ? AND winner = ?"
        winner_values = [*values, 0 if has_real else 1, winner]
        stats = conn.execute(
            "SELECT COUNT(*) AS total, COUNT(winning_price) AS priced_count, "
            "SUM(winning_price) AS winning_price_total FROM projects" + where + winner_filter,
            winner_values,
        ).fetchone()
        rows = [dict(row) for row in conn.execute(
            "SELECT project_id, title, province, agency_province, announced_at, "
            "winning_price, budget, status FROM projects" + where + winner_filter +
            " ORDER BY announced_at DESC, project_id DESC LIMIT ? OFFSET ?",
            [*winner_values, PAGE_SIZE, offset],
        )]
    return {
        "winner": winner,
        "filters": {"provinces": selected_provinces},
        "projects": rows,
        "pagination": {"offset": offset, "page_size": PAGE_SIZE, "total": stats["total"]},
        "summary": {
            "count": stats["total"],
            "priced_count": stats["priced_count"],
            "winning_price_total": stats["winning_price_total"],
            "is_demo": not has_real,
        },
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        print("%s - %s" % (self.address_string(), format % args))

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/dashboard":
            try:
                self.send_json(dashboard(parse_qs(parsed.query)))
            except ValueError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/winner-projects":
            try:
                self.send_json(winner_projects(parse_qs(parsed.query)))
            except ValueError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/imports":
            with connect() as conn:
                runs = [dict(row) for row in conn.execute(
                    "SELECT id, source_name, file_sha256, row_count, created_count, updated_count, imported_at "
                    "FROM import_runs ORDER BY id DESC LIMIT 20"
                )]
            self.send_json({"imports": runs})
            return
        assets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
        }
        if parsed.path not in assets:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        filename, content_type = assets[parsed.path]
        body = (WEB / filename).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/projects", "/api/import", "/api/demo/load", "/api/demo/clear"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 6_000_000:
                raise ValueError("ข้อมูลใหญ่เกิน 6 MB")
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("ข้อมูลที่ส่งมาต้องเป็น JSON object")
            if parsed.path == "/api/projects":
                row = validate_project(payload)
                with connect() as conn:
                    conn.execute(UPSERT_SQL, row)
                self.send_json({"message": "บันทึกโครงการแล้ว"})
            elif parsed.path == "/api/import":
                csv_text = payload.get("csv", "")
                if not isinstance(csv_text, str):
                    raise ValueError("ไฟล์ CSV ไม่ถูกต้อง")
                source_name = text_field(payload.get("filename"), "ชื่อไฟล์", maximum=200) or "uploaded.csv"
                source_name = source_name.replace("\\", "/").split("/")[-1]
                reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
                if not reader.fieldnames or not REQUIRED_CSV.issubset(reader.fieldnames):
                    raise ValueError("CSV ต้องมีคอลัมน์ project_id, title, province, status")
                rows = []
                seen_ids = set()
                for line, item in enumerate(reader, start=2):
                    if line > 5001:
                        raise ValueError("นำเข้าได้ไม่เกิน 5,000 รายการต่อครั้ง")
                    try:
                        row = validate_project(item, source_kind="csv", source_name=source_name)
                        if row[0] in seen_ids:
                            raise ValueError("รหัสโครงการซ้ำในไฟล์เดียวกัน")
                        seen_ids.add(row[0])
                        rows.append(row)
                    except ValueError as exc:
                        raise ValueError(f"แถว {line}: {exc}") from exc
                if not rows:
                    raise ValueError("CSV ไม่มีรายการโครงการ")
                with connect() as conn:
                    existing = set()
                    ids = list(seen_ids)
                    for offset in range(0, len(ids), 500):
                        chunk = ids[offset:offset + 500]
                        existing.update(row["project_id"] for row in conn.execute(
                            f"SELECT project_id FROM projects WHERE project_id IN ({','.join('?' for _ in chunk)})",
                            chunk,
                        ))
                    conn.executemany(UPSERT_SQL, rows)
                    conn.execute(
                        "INSERT INTO import_runs (source_name, file_sha256, row_count, created_count, updated_count, imported_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            source_name, hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
                            len(rows), len(rows) - len(existing), len(existing),
                            datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        ),
                    )
                self.send_json({"message": f"นำเข้า {len(rows):,} รายการแล้ว (ใหม่ {len(rows) - len(existing):,}, อัปเดต {len(existing):,})"})
            elif parsed.path == "/api/demo/load":
                with (ROOT / "examples" / "sample_projects.csv").open(encoding="utf-8-sig", newline="") as handle:
                    rows = [
                        validate_project(item, is_demo=True, source_kind="demo", source_name="sample_projects.csv")
                        for item in csv.DictReader(handle)
                    ]
                with connect() as conn:
                    conn.executemany(UPSERT_SQL, rows)
                self.send_json({"message": f"เพิ่มข้อมูลตัวอย่าง {len(rows)} รายการแล้ว"})
            else:
                with connect() as conn:
                    count = conn.execute("DELETE FROM projects WHERE is_demo = 1").rowcount
                self.send_json({"message": f"ลบข้อมูลตัวอย่าง {count} รายการแล้ว"})
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"e-GP dashboard: http://{HOST}:{PORT}")
    print(f"Database: {DB}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
