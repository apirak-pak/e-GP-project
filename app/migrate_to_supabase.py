"""Copy the existing local SQLite data to an empty Supabase egp schema."""

from __future__ import annotations

import sqlite3
import sys

from app.db import connect_postgres
from app.schema_postgres import init_db_postgres
from app.server import DB


TABLE_COLUMNS = {
    "projects": (
        "project_id", "title", "province", "project_type", "agency", "status",
        "budget", "reference_price", "winning_price", "winner", "announced_at",
        "source_url", "is_demo", "source_kind", "source_name", "agency_province",
        "province_source", "updated_at",
    ),
    "import_runs": (
        "id", "source_name", "file_sha256", "row_count", "created_count",
        "updated_count", "imported_at",
    ),
    "api_sync_runs": (
        "id", "service", "fiscal_year", "keyword", "result_total", "fetched_count",
        "saved_count", "skipped_count", "synced_at",
    ),
}


def migrate() -> dict[str, int]:
    if not DB.exists():
        raise ValueError("ไม่พบฐานข้อมูล SQLite ใน data/egp.db")
    source = sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        source.execute("BEGIN")  # Keep one consistent view even if the local app is open.
        counts = {}
        for table, columns in TABLE_COLUMNS.items():
            found = {row["name"] for row in source.execute(f"PRAGMA table_info({table})")}
            if not set(columns).issubset(found):
                raise ValueError(f"ตาราง {table} ใน SQLite มีคอลัมน์ไม่ครบ")
            counts[table] = source.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]

        init_db_postgres()
        with connect_postgres() as target:
            target.execute("SET LOCAL statement_timeout = 0")
            for table in TABLE_COLUMNS:
                present = target.execute(f"SELECT COUNT(*) AS count FROM egp.{table}").fetchone()["count"]
                if present:
                    raise ValueError(
                        f"Supabase มีข้อมูลใน egp.{table} อยู่แล้ว ({present:,} รายการ); "
                        "หยุดเพื่อป้องกันการทับข้อมูลเดิม"
                    )
            for table, columns in TABLE_COLUMNS.items():
                names = ", ".join(columns)
                with target.connection.cursor() as cursor:
                    with cursor.copy(f"COPY egp.{table} ({names}) FROM STDIN") as copy:
                        for index, row in enumerate(source.execute(f"SELECT {names} FROM {table}"), start=1):
                            copy.write_row(tuple(row[name] for name in columns))
                            if table == "projects" and index % 5000 == 0:
                                print(f"ส่งโครงการแล้ว {index:,} / {counts[table]:,}", flush=True)
                copied = target.execute(f"SELECT COUNT(*) AS count FROM egp.{table}").fetchone()["count"]
                if copied != counts[table]:
                    raise ValueError(f"ตรวจจำนวน {table} ไม่ตรงกัน; การย้ายถูกยกเลิก")
            for table in ("import_runs", "api_sync_runs"):
                if counts[table]:
                    target.execute(
                        "SELECT setval(pg_get_serial_sequence(?, 'id'), "
                        f"(SELECT MAX(id) FROM egp.{table}), true)",
                        (f"egp.{table}",),
                    )
        return counts
    finally:
        source.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        counts = migrate()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        # A database error may contain connection details. Never print it verbatim.
        if exc.__class__.__module__.startswith("psycopg"):
            print("ย้ายข้อมูลไม่สำเร็จ; ธุรกรรมถูกย้อนกลับ ตรวจการเชื่อมต่อและพื้นที่ฐานข้อมูล", file=sys.stderr)
            return 1
        raise
    print("ย้ายข้อมูลเข้า Supabase สำเร็จ: " + ", ".join(f"{name} {count:,}" for name, count in counts.items()))
    print("ไฟล์ data/egp.db ยังอยู่ในเครื่องเป็นสำรอง; เปลี่ยน DB_BACKEND=postgres ใน .env แล้วเริ่มเว็บใหม่")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
