"""Local e-GP announcement store. Only a paired Edge extension may import API pages."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
WEB = Path(__file__).resolve().parent / "web"
DB = ROOT / "data" / "egp_live.db"
HOST, PORT = "127.0.0.1", 8502
LOCAL = f"http://{HOST}:{PORT}"
EGP = "https://process5.gprocurement.go.th"
API_PATH = "/egp-oann10-service/pb/a-egp-allt-project/announcement"
PROVINCES = {"500000": "เชียงใหม่", "570000": "เชียงราย", "560000": "พะเยา"}
YEARS = {2569, 2570}
PAIR_LOCK = threading.RLock()
PAIR = {"extension_id": "", "token": "", "message": "ยังไม่ได้เชื่อมตัวรับ API", "last_received": ""}


@contextmanager
def connect():
    DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB, timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS api_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fiscal_year INTEGER NOT NULL, province TEXT NOT NULL, page INTEGER NOT NULL,
                row_count INTEGER NOT NULL, captured_at TEXT NOT NULL,
                source_url TEXT NOT NULL, response_sha256 TEXT NOT NULL,
                response_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pages_scope ON api_pages(fiscal_year, province, page);
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY, fiscal_year INTEGER NOT NULL,
                agency_province TEXT NOT NULL, title TEXT NOT NULL,
                agency TEXT NOT NULL, parent_agency TEXT NOT NULL,
                status TEXT NOT NULL, budget TEXT, announce_date TEXT,
                first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                source_url TEXT NOT NULL, raw_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_projects_scope ON projects(fiscal_year, agency_province, status);
        """)


def _one(params: dict, key: str) -> str:
    values = params.get(key, [])
    if len(values) != 1:
        raise ValueError(f"เงื่อนไข {key} ไม่ถูกต้อง")
    return values[0]


def _rows(response: object) -> list[dict]:
    if not isinstance(response, dict):
        raise ValueError("คำตอบ e-GP ไม่ใช่ JSON object")
    if response.get("validateCfTurnTile") is False or response.get("validateAnnouncementToken") is False:
        raise ValueError("e-GP ขอให้ยืนยันตัวตนใหม่ใน Edge")
    if response.get("success") is False:
        raise ValueError("e-GP แจ้งว่าคำขอไม่สำเร็จ")
    rows = response.get("data")
    if isinstance(rows, dict):
        rows = rows.get("data")
    if not isinstance(rows, list) or len(rows) > 1000 or any(not isinstance(row, dict) for row in rows):
        raise ValueError("รูปแบบรายการ e-GP เปลี่ยน จึงหยุดบันทึก")
    return rows


def _has_auth_field(value: object) -> bool:
    if isinstance(value, dict):
        return any(re.search(r"token|authorization|cookie|password|secret|api.?key", str(key), re.I)
                   or _has_auth_field(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_has_auth_field(child) for child in value)
    return False


def ingest(payload: dict) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("source_url"), str):
        raise ValueError("ข้อมูลจากตัวเชื่อมไม่ถูกต้อง")
    source_url = payload["source_url"]
    if len(source_url) > 2000:
        raise ValueError("URL คำขอยาวเกินไป")
    url = urlsplit(source_url)
    if (url.scheme, url.netloc, url.path, url.fragment) != ("https", "process5.gprocurement.go.th", API_PATH, ""):
        raise ValueError("รับเฉพาะ API รายการประกาศ e-GP")
    params = parse_qs(url.query, keep_blank_values=True)
    if set(params) - {"budgetYear", "moiId", "methodId", "typeId", "announcementTodayFlag", "page"}:
        raise ValueError("URL มีตัวกรองที่ระบบยังไม่รองรับ")
    try:
        year, page = int(_one(params, "budgetYear")), int(_one(params, "page"))
    except ValueError:
        raise ValueError("ปีหรือเลขหน้าไม่ถูกต้อง") from None
    code = _one(params, "moiId")
    if year not in YEARS or code not in PROVINCES or not 1 <= page <= 1000:
        raise ValueError("ปี จังหวัด หรือเลขหน้าอยู่นอกขอบเขต")
    if _one(params, "methodId") != "16" or _one(params, "typeId") != "02":
        raise ValueError("รับเฉพาะ e-bidding จ้างก่อสร้าง")
    response = payload.get("response")
    rows = _rows(response)
    if _has_auth_field(response):
        raise ValueError("คำตอบมีฟิลด์ที่อาจเป็นข้อมูลยืนยันตัวตน")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    project_rows = []
    ids = set()
    for row in rows:
        project_id = str(row.get("projectId", ""))
        if not re.fullmatch(r"\d{11}", project_id) or project_id in ids:
            raise ValueError("เลขโครงการซ้ำหรือไม่ถูกต้อง")
        ids.add(project_id)
        title = row.get("projectName")
        if not isinstance(title, str) or not title.strip() or len(title) > 5000:
            raise ValueError("ชื่อโครงการไม่ถูกต้อง")
        for field in ("budgetYear", "fiscalYear"):
            if row.get(field) not in (None, "", year, str(year)):
                raise ValueError("ปีในรายการไม่ตรงกับคำขอ")
        if row.get("provinceName") not in (None, "", PROVINCES[code]):
            raise ValueError("จังหวัดในรายการไม่ตรงกับคำขอ")
        budget = None
        if row.get("projectMoney") not in (None, ""):
            try:
                amount = Decimal(str(row["projectMoney"]))
            except (InvalidOperation, ValueError):
                raise ValueError("วงเงินไม่ถูกต้อง") from None
            if not amount.is_finite() or not 0 <= amount <= Decimal("1000000000000000"):
                raise ValueError("วงเงินไม่ถูกต้อง")
            budget = str(amount)
        date = row.get("announceDate")
        date = date[:10] if isinstance(date, str) and re.fullmatch(r"20\d\d-\d\d-\d\d.*", date) else None
        project_rows.append((project_id, year, PROVINCES[code], title.strip(),
                             str(row.get("deptSubName") or ""), str(row.get("deptName") or ""),
                             str(row.get("flowName") or ""), budget, date, now, now,
                             EGP + "/egp-agpc01-web/announcement?keywordSearch=" + quote(project_id),
                             json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
    raw = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    with connect() as conn:
        conn.execute("""INSERT INTO api_pages
            (fiscal_year,province,page,row_count,captured_at,source_url,response_sha256,response_json)
            VALUES (?,?,?,?,?,?,?,?)""", (year, PROVINCES[code], page, len(rows), now, source_url,
                                      hashlib.sha256(raw.encode()).hexdigest(), raw))
        conn.executemany("""INSERT INTO projects
            (project_id,fiscal_year,agency_province,title,agency,parent_agency,status,budget,
             announce_date,first_seen_at,last_seen_at,source_url,raw_json)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
             ON CONFLICT(project_id) DO UPDATE SET fiscal_year=excluded.fiscal_year,
             agency_province=excluded.agency_province,title=excluded.title,agency=excluded.agency,
             parent_agency=excluded.parent_agency,status=excluded.status,budget=excluded.budget,
             announce_date=excluded.announce_date,last_seen_at=excluded.last_seen_at,
             source_url=excluded.source_url,raw_json=excluded.raw_json""", project_rows)
    with PAIR_LOCK:
        PAIR.update(message=f"บันทึก {PROVINCES[code]} หน้า {page}: {len(rows)} รายการ", last_received=now)
    return {"saved": len(rows), "province": PROVINCES[code], "page": page}


def state(params: dict[str, list[str]]) -> dict:
    try:
        year = int((params.get("year") or ["2569"])[0])
        page = int((params.get("page") or ["1"])[0])
    except ValueError:
        raise ValueError("ปีหรือเลขหน้าไม่ถูกต้อง") from None
    if year not in YEARS or not 1 <= page <= 10000:
        raise ValueError("ปีหรือเลขหน้าไม่ถูกต้อง")
    provinces = list(dict.fromkeys(params.get("province", [])))
    if any(p not in PROVINCES.values() for p in provinces):
        raise ValueError("จังหวัดไม่ถูกต้อง")
    q = (params.get("q") or [""])[0].strip()
    status = (params.get("status") or [""])[0].strip()
    if len(q) > 100 or len(status) > 200:
        raise ValueError("คำค้นยาวเกินไป")
    where, values = ["fiscal_year=?"], [year]
    if provinces:
        where.append("agency_province IN (" + ",".join("?" for _ in provinces) + ")")
        values.extend(provinces)
    if status:
        where.append("status=?")
        values.append(status)
    if q:
        where.append("(project_id LIKE ? OR title LIKE ? OR agency LIKE ?)")
        values.extend([f"%{q}%"] * 3)
    condition = " AND ".join(where)
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM projects WHERE " + condition, values).fetchone()[0]
        items = [dict(row) for row in conn.execute("SELECT project_id,fiscal_year,agency_province,title,agency,parent_agency,status,budget,announce_date,last_seen_at,source_url FROM projects WHERE " + condition + " ORDER BY last_seen_at DESC,project_id DESC LIMIT 30 OFFSET ?", [*values, (page - 1) * 30])]
        coverage = [dict(row) for row in conn.execute("""SELECT fiscal_year,province,
            COUNT(DISTINCT page) AS pages,MAX(page) AS max_page,MAX(captured_at) AS updated_at,
            0 AS rows_received FROM api_pages GROUP BY fiscal_year,province
            ORDER BY fiscal_year DESC,province""")]
        latest_pages = {}
        for row in conn.execute("SELECT fiscal_year,province,page,row_count FROM api_pages ORDER BY id"):
            latest_pages.setdefault((row["fiscal_year"], row["province"]), {})[row["page"]] = row["row_count"]
        for item in coverage:
            counts = latest_pages[(item["fiscal_year"], item["province"])]
            found = set(counts)
            contiguous = 0
            while contiguous + 1 in found:
                contiguous += 1
            item["contiguous_through"] = contiguous
            item["next_page"] = contiguous + 1
            item["missing_pages"] = [p for p in range(1, item["max_page"] + 1) if p not in found][:20]
            item["rows_received"] = sum(counts.values())
            item["empty_page"] = next((p for p in range(1, contiguous + 1) if counts[p] == 0), None)
            item["complete"] = item["empty_page"] is not None
        statuses = [row[0] for row in conn.execute("SELECT DISTINCT status FROM projects WHERE fiscal_year=? AND status<>'' ORDER BY status", (year,))]
        total = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        pages = conn.execute("SELECT COUNT(*) FROM api_pages").fetchone()[0]
    with PAIR_LOCK:
        connection = {"connected": bool(PAIR["token"]), "message": PAIR["message"], "last_received": PAIR["last_received"]}
    return {"projects": items, "count": count, "page": page, "page_size": 30,
            "total_projects": total, "total_api_pages": pages, "coverage": coverage,
            "statuses": statuses, "connection": connection}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if args and str(args[0]).startswith("GET /api/state?"):
            return
        print("%s - %s" % (self.address_string(), fmt % args))

    def _cors(self):
        with PAIR_LOCK:
            allowed = "chrome-extension://" + PAIR["extension_id"] if PAIR["extension_id"] else ""
        if self.headers.get("Origin") == allowed and allowed:
            self.send_header("Access-Control-Allow-Origin", allowed)
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def _send(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.end_headers()

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/api/state":
            try:
                self._send(state(parse_qs(url.query)))
            except ValueError as exc:
                self._send({"error": str(exc)}, 400)
            return
        if url.path == "/api/project":
            project_id = (parse_qs(url.query).get("id") or [""])[0]
            if not re.fullmatch(r"\d{11}", project_id):
                self._send({"error": "เลขโครงการไม่ถูกต้อง"}, 400)
                return
            with connect() as conn:
                row = conn.execute("SELECT raw_json,last_seen_at FROM projects WHERE project_id=?", (project_id,)).fetchone()
            if row is None:
                self._send({"error": "ไม่พบโครงการ"}, 404)
            else:
                self._send({"project_id": project_id, "last_seen_at": row["last_seen_at"],
                            "raw": json.loads(row["raw_json"])})
            return
        files = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                 "/styles.css": ("styles.css", "text/css")}
        if url.path not in files:
            self.send_error(404)
            return
        name, mime = files[url.path]
        body = (WEB / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        url = urlsplit(self.path)
        if url.path not in {"/api/pair", "/api/import", "/api/progress"}:
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 5_000_000:
                raise ValueError("คำขอใหญ่เกินไป")
            payload = json.loads(self.rfile.read(size))
            if url.path == "/api/pair":
                if self.headers.get("Origin") != LOCAL:
                    raise ValueError("ต้องเชื่อมจากหน้าเว็บในเครื่อง")
                ext = payload.get("extension_id") if isinstance(payload, dict) else None
                if not isinstance(ext, str) or not re.fullmatch(r"[a-p]{32}", ext):
                    raise ValueError("รหัสส่วนขยายไม่ถูกต้อง")
                with PAIR_LOCK:
                    PAIR.update(extension_id=ext, token=secrets.token_urlsafe(32), message="เชื่อมแล้ว · เปิด e-GP และกดค้นหาหนึ่งครั้ง")
                    token = PAIR["token"]
                self._send({"token": token})
                return
            with PAIR_LOCK:
                expected = "Bearer " + PAIR["token"] if PAIR["token"] else ""
                origin = "chrome-extension://" + PAIR["extension_id"] if PAIR["extension_id"] else ""
            if not expected or not hmac.compare_digest(self.headers.get("Authorization", ""), expected) or self.headers.get("Origin") not in ("", origin):
                self._send({"error": "ตัวเชื่อมยังไม่จับคู่"}, 401)
                return
            if url.path == "/api/import":
                self._send(ingest(payload))
            else:
                message = payload.get("message") if isinstance(payload, dict) else None
                if not isinstance(message, str) or not 0 < len(message) <= 500:
                    raise ValueError("ข้อความสถานะไม่ถูกต้อง")
                with PAIR_LOCK:
                    PAIR["message"] = message
                self._send({"ok": True})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send({"error": str(exc)}, 400)


def main():
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"e-GP Live: {LOCAL}  database: {DB}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
