"""Database configuration and a small PostgreSQL compatibility adapter."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent


def setting(name: str) -> str:
    """Read one setting from the process or local .env without displaying secrets."""
    if name in os.environ:
        return os.environ[name].strip()
    path = ROOT / ".env"
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == name:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value
    return ""


def backend() -> str:
    result = setting("DB_BACKEND").lower() or "sqlite"
    if result not in {"sqlite", "postgres"}:
        raise ValueError("DB_BACKEND ต้องเป็น sqlite หรือ postgres")
    return result


class PostgresConnection:
    """Expose the execute interface used by the SQLite version of the app."""

    def __init__(self, connection: Any):
        self.connection = connection

    def __enter__(self) -> "PostgresConnection":
        self.connection.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Any:
        return self.connection.__exit__(exc_type, exc_value, traceback)

    def execute(self, sql: str, params: Any = ()) -> Any:
        return self.connection.execute(sql.replace("?", "%s"), params)

    def executemany(self, sql: str, rows: Any) -> None:
        with self.connection.cursor() as cursor:
            cursor.executemany(sql.replace("?", "%s"), rows)


def connect_postgres() -> PostgresConnection:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise ValueError("ต้องติดตั้งไลบรารีฐานข้อมูลก่อน: python -m pip install -r requirements.txt") from exc

    required = {
        "host": setting("SUPABASE_DB_HOST"),
        "user": setting("SUPABASE_DB_USER"),
        "password": setting("SUPABASE_DB_PASSWORD"),
    }
    if any(not value or value.startswith("PASTE_") for value in required.values()):
        raise ValueError("กรุณาใส่ SUPABASE_DB_HOST, SUPABASE_DB_USER และ SUPABASE_DB_PASSWORD ใน .env")
    port = setting("SUPABASE_DB_PORT") or "5432"
    if not port.isdigit():
        raise ValueError("SUPABASE_DB_PORT ต้องเป็นตัวเลข")
    connection = None
    try:
        connection = psycopg.connect(
            host=required["host"], port=int(port), user=required["user"],
            password=required["password"], dbname="postgres", sslmode="require",
            connect_timeout=15, row_factory=dict_row,
        )
        connection.execute("SET search_path TO egp, public")
    except psycopg.Error:
        if connection is not None:
            connection.close()
        raise ValueError("เชื่อมต่อ Supabase ไม่สำเร็จ; ตรวจค่าใน .env และสถานะโปรเจ็ค") from None
    return PostgresConnection(connection)
