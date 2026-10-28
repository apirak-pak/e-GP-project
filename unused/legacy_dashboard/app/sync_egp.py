"""Import one requested page of EGP-CONTRACT records into the local dashboard."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.location import UNKNOWN_PROVINCE, project_province_from_title
from app.db import backend
from app.server import DATA, DB, ROOT, UPSERT_SQL, connect, init_db, validate_project


ENDPOINT = "https://opend.data.go.th/govspending/service/egp-contract"
MONTHS = {
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4,
    "พ.ค.": 5, "มิ.ย.": 6, "ก.ค.": 7, "ส.ค.": 8,
    "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def read_key() -> str:
    path = ROOT / ".env"
    if not path.exists():
        raise ValueError("ไม่พบไฟล์ .env ในโฟลเดอร์โปรเจ็ค")
    lines = [line for line in path.read_text(encoding="utf-8-sig").splitlines()
             if re.match(r"^\s*DGA_API_KEY\s*=", line)]
    if len(lines) != 1:
        raise ValueError("ไฟล์ .env ต้องมี DGA_API_KEY=... เพียงหนึ่งบรรทัด")
    key = lines[0].split("=", 1)[1].strip().strip('"\'')
    if not key or key == "PASTE_YOUR_KEY_HERE":
        raise ValueError("ยังไม่ได้ใส่ DGA_API_KEY จริงในไฟล์ .env")
    return key


def thai_date(value: object) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        pass
    match = re.fullmatch(r"(\d{1,2})\s+([^\s]+)\s+(\d{2,4})", value)
    if not match or match.group(2) not in MONTHS:
        return ""
    year = int(match.group(3))
    if year < 100:
        year += 2500
    if year >= 2400:
        year -= 543
    try:
        return date(year, MONTHS[match.group(2)], int(match.group(1))).isoformat()
    except ValueError:
        return ""


def to_project(item: dict) -> tuple:
    project_province = project_province_from_title(item.get("project_name"))
    contracts = item.get("contract") or []
    if isinstance(contracts, dict):
        contracts = [contracts]
    if not isinstance(contracts, list):
        contracts = []
    winners = {str(c.get("winner_name") or "").strip() for c in contracts
               if isinstance(c, dict) and c.get("winner_name")}
    winner = next(iter(winners)) if len(winners) == 1 else ""
    agreed = item.get("sum_price_agree")
    if agreed in (None, "") and len(contracts) == 1 and isinstance(contracts[0], dict):
        agreed = contracts[0].get("price_agree")
    raw_status = str(item.get("project_status") or "")
    if "ยกเลิก" in raw_status:
        status = "ยกเลิก"
    elif contracts:
        status = "ทำสัญญาแล้ว"
    elif "ผู้ชนะ" in raw_status:
        status = "ประกาศผู้ชนะ"
    else:
        status = "ไม่ทราบสถานะ"
    return validate_project(
        {
            "project_id": item.get("project_id"),
            "title": item.get("project_name"),
            "province": project_province,
            "agency_province": item.get("province"),
            "province_source": "title" if project_province != UNKNOWN_PROVINCE else "unknown",
            "project_type": item.get("project_type_name"),
            "agency": item.get("dept_name"),
            "status": status,
            "budget": item.get("project_money"),
            "reference_price": item.get("price_build"),
            "winning_price": agreed if winner else None,
            "winner": winner,
            "announced_at": thai_date(item.get("announce_date")),
            "source_url": "",
        },
        source_kind="api", source_name="EGP-CONTRACT / govspending.data.go.th",
    )


def quota_header(headers, *names: str) -> int | None:
    """Read only a plain numeric quota header; never print raw response headers."""
    for name in names:
        value = headers.get(name)
        if value and re.fullmatch(r"\d{1,12}", value.strip()):
            return int(value.strip())
    return None


def fetch(key: str, args: argparse.Namespace) -> tuple[dict, int, dict[str, int | None], int]:
    # This service's published contract requires api-key in the query string.
    # Construct it in memory and never log the URL or a raw network exception.
    params = {
        "api-key": key, "year": args.year, "keyword": args.keyword,
        "offset": args.offset, "limit": args.limit,
    }
    if args.min_budget is not None:
        params["budget_start"] = args.min_budget
    if args.max_budget is not None:
        params["budget_end"] = args.max_budget
    request = Request(ENDPOINT + "?" + urlencode(params), method="GET")
    opener = build_opener(NoRedirect)
    DATA.mkdir(exist_ok=True)
    with (DATA / "api_requests.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps({"at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              "service": "EGP-CONTRACT"}) + "\n")
    try:
        with opener.open(request, timeout=180) as response:
            body = response.read()
            payload = json.loads(body)
            http_status = response.status
            quota = {
                "limit": quota_header(response.headers, "RateLimit-Limit", "X-RateLimit-Limit"),
                "remaining": quota_header(response.headers, "RateLimit-Remaining", "X-RateLimit-Remaining"),
            }
    except HTTPError as exc:
        if exc.code == 500:
            raise ValueError("API ตอบ HTTP 500: บริการเกิดข้อผิดพลาดภายใน; ไม่มีข้อมูลถูกนำเข้า") from None
        if exc.code == 504:
            raise ValueError("API ตอบ HTTP 504 (Gateway Timeout): ผู้ให้บริการตอบคำขอขนาดนี้ไม่ทัน; ไม่มีข้อมูลถูกนำเข้า") from None
        if exc.code == 413:
            raise ValueError("API ตอบ HTTP 413: คำขอหรือคำตอบมีขนาดเกินที่ผู้ให้บริการรองรับ; ไม่มีข้อมูลถูกนำเข้า") from None
        if exc.code == 429:
            raise ValueError("API ตอบ HTTP 429: ผู้ให้บริการจำกัดจำนวนคำขอ; ไม่มีข้อมูลถูกนำเข้า") from None
        raise ValueError(f"API ตอบ HTTP {exc.code}; ตรวจสิทธิ์คีย์และเงื่อนไขคำขอ") from None
    except (URLError, TimeoutError):
        raise ValueError("เชื่อมต่อ API ไม่สำเร็จ; ตรวจอินเทอร์เน็ตแล้วลองใหม่") from None
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("API ตอบกลับไม่สำเร็จ; ตรวจสิทธิ์คีย์และเงื่อนไขคำขอ")
    if not isinstance(payload.get("data"), list):
        raise ValueError("รูปแบบข้อมูลจาก API เปลี่ยนไป: ไม่พบรายการ data")
    return payload, http_status, quota, len(body)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="ดึงโครงการ EGP-CONTRACT หนึ่งหน้าลงฐานข้อมูลที่ตั้งค่าไว้")
    parser.add_argument("--year", type=int, default=2568, help="ปีงบประมาณ พ.ศ. ที่ทำสัญญา")
    parser.add_argument("--keyword", default="จ้างก่อสร้าง", help="คำค้นชื่อโครงการ")
    parser.add_argument("--limit", type=int, default=20, help="จำนวนรายการที่ขอต่อครั้ง (จำนวนเต็มบวก; API อาจจำกัดเอง)")
    parser.add_argument("--offset", type=int, default=0, help="เริ่มจากลำดับที่ (0 ขึ้นไป)")
    parser.add_argument("--min-budget", type=float, default=None, help="วงเงินงบประมาณต่ำสุด บาท")
    parser.add_argument("--max-budget", type=float, default=None, help="วงเงินงบประมาณสูงสุด บาท")
    args = parser.parse_args()
    if not 2500 <= args.year <= 2700 or args.limit < 1 or args.offset < 0:
        parser.error("ปีงบประมาณ, limit หรือ offset ไม่ถูกต้อง")
    if (args.min_budget is not None and args.min_budget < 0) or (args.max_budget is not None and args.max_budget < 0):
        parser.error("ช่วงราคาต้องไม่ติดลบ")
    if args.min_budget is not None and args.max_budget is not None and args.min_budget > args.max_budget:
        parser.error("ราคาต่ำสุดต้องไม่มากกว่าราคาสูงสุด")
    if backend() == "sqlite" and DB.name == "dga_explore.db":
        print("ฐาน DGA ใหม่เก็บคำตอบดิบเท่านั้น: ใช้ python -m app.capture_dga; ไม่แปลงข้อมูลเข้า projects", file=sys.stderr)
        return 1
    try:
        payload, http_status, quota, body_bytes = fetch(read_key(), args)
        rows = []
        skipped = 0
        for item in payload["data"]:
            try:
                rows.append(to_project(item))
            except (ValueError, AttributeError, TypeError):
                skipped += 1
        init_db()
        with connect() as conn:
            conn.executemany(UPSERT_SQL, rows)
            conn.execute(
                "INSERT INTO api_sync_runs (service, fiscal_year, keyword, result_total, fetched_count, saved_count, skipped_count, synced_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("EGP-CONTRACT", args.year, args.keyword, int(payload.get("total") or 0),
                 len(payload["data"]), len(rows), skipped,
                 datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
        print(f"ดึง {len(payload['data'])} รายการจาก API; บันทึก {len(rows)}; ข้าม {skipped}")
        print(f"ขนาดคำตอบ JSON {body_bytes:,} ไบต์ ({body_bytes / 1_000_000:.2f} MB)")
        print(f"ผู้ให้บริการตอบ HTTP {http_status}; success=true")
        print(f"API รายงานผลค้นหาทั้งหมด {int(payload.get('total') or 0):,} รายการ; รอบนี้ดึงเพียงหนึ่งหน้า")
        if quota["remaining"] is None:
            print("ไม่พบจำนวนโควตาคงเหลือใน response header ที่ตรวจ; ตัวนับในเครื่องไม่ใช่ยอดทางการ")
        else:
            total_limit = f" / {quota['limit']}" if quota["limit"] is not None else ""
            print(f"API รายงานโควตาคงเหลือ {quota['remaining']}{total_limit} ครั้ง")
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
