"""Keep complete, credential-redacted DGA replies in an isolated SQLite file.

Rows are indexed only for inspection. No dashboard fields or statuses are inferred.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from contextlib import closing


def save_capture(db_path: Path, manifest: dict, body: bytes, rows: list[dict]) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dga_raw_captures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at_utc TEXT NOT NULL,
                service TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                query_json TEXT NOT NULL,
                http_status INTEGER NOT NULL,
                reported_total INTEGER,
                returned_count INTEGER NOT NULL,
                response_sha256 TEXT NOT NULL,
                credential_redacted INTEGER NOT NULL,
                response_body BLOB NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dga_raw_projects (
                capture_id INTEGER NOT NULL,
                row_index INTEGER NOT NULL,
                project_id TEXT,
                raw_json TEXT NOT NULL,
                PRIMARY KEY (capture_id, row_index),
                FOREIGN KEY (capture_id) REFERENCES dga_raw_captures(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dga_raw_project_id ON dga_raw_projects(project_id)")
        cursor = conn.execute("""
            INSERT INTO dga_raw_captures (
                captured_at_utc, service, endpoint, query_json, http_status,
                reported_total, returned_count, response_sha256,
                credential_redacted, response_body
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            manifest["captured_at_utc"], manifest["service"], manifest["endpoint"],
            json.dumps(manifest["query"], ensure_ascii=False), manifest["http_status"],
            manifest["reported_total"], manifest["returned_count"],
            manifest["response_sha256"], int(manifest["credential_redacted"]), body,
        ))
        capture_id = cursor.lastrowid
        conn.executemany("""
            INSERT INTO dga_raw_projects (capture_id, row_index, project_id, raw_json)
            VALUES (?, ?, ?, ?)
        """, (
            (capture_id, index, str(row.get("project_id") or ""),
             json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            for index, row in enumerate(rows)
        ))
        return capture_id
