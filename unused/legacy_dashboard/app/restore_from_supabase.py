"""Copy the current Supabase data back into the local SQLite database."""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

from app.db import connect_postgres
from app.migrate_to_supabase import TABLE_COLUMNS
from app.server import DB, UPSERT_SQL


def restore() -> tuple[Path, dict[str, int], dict[str, int]]:
    if not DB.exists():
        raise ValueError("ไม่พบฐานข้อมูล SQLite ใน data/egp.db")

    backup_dir = DB.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    backup_path = backup_dir / f"egp-before-local-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    if backup_path.exists():
        raise ValueError("ชื่อไฟล์สำรองซ้ำ กรุณาลองอีกครั้ง")

    with closing(sqlite3.connect(DB, timeout=30)) as local:
        for table, columns in TABLE_COLUMNS.items():
            found = {row[1] for row in local.execute(f"PRAGMA table_info({table})")}
            if not set(columns).issubset(found):
                raise ValueError(f"ตาราง {table} ใน SQLite มีคอลัมน์ไม่ครบ")
        with closing(sqlite3.connect(backup_path)) as backup:
            local.backup(backup)

        source_counts: dict[str, int] = {}
        local_counts: dict[str, int] = {}
        with connect_postgres() as source:
            try:
                local.execute("BEGIN IMMEDIATE")
                for table, columns in TABLE_COLUMNS.items():
                    source_counts[table] = source.execute(
                        f"SELECT COUNT(*) AS count FROM egp.{table}"
                    ).fetchone()["count"]
                    names = ", ".join(columns)
                    placeholders = ", ".join("?" for _ in columns)
                    if table == "projects":
                        insert_sql = UPSERT_SQL
                    else:
                        insert_sql = f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({placeholders})"

                    copied = 0
                    with source.connection.cursor(name=f"restore_{table}") as cursor:
                        cursor.execute(f"SELECT {names} FROM egp.{table}")
                        while batch := cursor.fetchmany(1000):
                            local.executemany(
                                insert_sql,
                                [tuple(row[name] for name in columns) for row in batch],
                            )
                            copied += len(batch)
                            if table == "projects" and copied % 5000 == 0:
                                print(f"คัดลอกโครงการแล้ว {copied:,} / {source_counts[table]:,}", flush=True)
                    if copied != source_counts[table]:
                        raise ValueError(f"จำนวนที่คัดลอกจาก {table} ไม่ครบ")
                    local_counts[table] = local.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                    if local_counts[table] < source_counts[table]:
                        raise ValueError(f"จำนวน {table} ใน SQLite ยังน้อยกว่า Supabase")
                local.commit()
            except Exception:
                local.rollback()
                raise

    return backup_path, source_counts, local_counts


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        backup, source_counts, local_counts = restore()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        if exc.__class__.__module__.startswith("psycopg"):
            print("คัดลอกข้อมูลจาก Supabase ไม่สำเร็จ; ตรวจการเชื่อมต่อ", file=sys.stderr)
            return 1
        raise
    print(f"คัดลอกข้อมูลจาก Supabase สำเร็จ; ไฟล์สำรองเดิม: {backup}")
    for table in TABLE_COLUMNS:
        print(f"{table}: Supabase {source_counts[table]:,}; SQLite {local_counts[table]:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
