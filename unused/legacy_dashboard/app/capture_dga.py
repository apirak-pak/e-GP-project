"""Capture one EGP-CONTRACT response locally before choosing display fields.

No mapping, province inference, status conversion, or dashboard import.
The request counter is shared with the existing DGA client; keys never go to disk.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from app.sync_egp import ENDPOINT, NoRedirect, read_key
from app.dga_raw_store import save_capture

ROOT = Path(__file__).resolve().parent.parent
RAW_ROOT = ROOT / "data" / "dga_raw"


def field_inventory(rows: list[dict]) -> list[dict]:
    """List actual paths, types and values; array occurrences are not row coverage."""
    fields: dict[str, dict] = {}

    def visit(value: object, path: str) -> None:
        kind = ("null" if value is None else "boolean" if isinstance(value, bool)
                else "object" if isinstance(value, dict) else "array" if isinstance(value, list)
                else "number" if isinstance(value, (int, float)) else "string")
        entry = fields.setdefault(path, {"path": path, "occurrences": 0,
                                        "nonempty_occurrences": 0, "types": Counter(), "examples": []})
        entry["occurrences"] += 1
        entry["types"][kind] += 1
        if value is not None and value != "" and value != [] and value != {}:
            entry["nonempty_occurrences"] += 1
        if not isinstance(value, (dict, list)) and value is not None:
            example = value[:180] if isinstance(value, str) else value
            if example not in entry["examples"] and len(entry["examples"]) < 2:
                entry["examples"].append(example)
        if isinstance(value, dict):
            for name, child in value.items():
                visit(child, f"{path}.{name}" if path else name)
        elif isinstance(value, list):
            for child in value:
                visit(child, path + "[]")

    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("API data มีรายการที่ไม่ใช่ object")
        for name, value in row.items():
            visit(value, name)
    return [dict(value, types=dict(value["types"])) for _, value in sorted(fields.items())]


def capture(args: argparse.Namespace) -> tuple[Path, dict]:
    key = read_key()
    query = {"year": args.year, "keyword": args.keyword,
             "limit": args.limit, "offset": args.offset}
    request = Request(ENDPOINT + "?" + urlencode({"api-key": key, **query}), method="GET")
    now = datetime.now(timezone.utc)
    (ROOT / "data").mkdir(exist_ok=True)
    with (ROOT / "data" / "api_requests.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps({"at_utc": now.isoformat(timespec="seconds"),
                              "service": "EGP-CONTRACT-RAW"}) + "\n")
    try:
        with build_opener(NoRedirect).open(request, timeout=60) as response:
            raw = response.read(64_000_001)
            http = response.status
    except HTTPError as exc:
        raise ValueError(f"DGA ตอบ HTTP {exc.code}; ไม่บันทึกข้อมูลและไม่ลองซ้ำอัตโนมัติ") from None
    except (URLError, TimeoutError):
        raise ValueError("ติดต่อ DGA ไม่สำเร็จ; ไม่บันทึกข้อมูลและไม่ลองซ้ำอัตโนมัติ") from None
    if len(raw) > 64_000_000:
        raise ValueError("คำตอบเกินขนาดที่รองรับ; ไม่บันทึกไฟล์ที่ไม่ครบ")
    # DGA echoes request.api-key in its response envelope. Retain every project
    # field and redact only the credential before any response is written.
    received_bytes = len(raw)
    credential_redacted = False
    for secret in {key.encode(), urlencode({"k": key})[2:].encode()}:
        if secret in raw:
            raw = raw.replace(secret, b"[REDACTED_API_KEY]")
            credential_redacted = True
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("DGA ไม่ได้ตอบเป็น JSON; ไม่บันทึก") from None
    if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("data"), list):
        raise ValueError("DGA ไม่ส่งรายการข้อมูลสำเร็จ; ไม่บันทึก")
    inventory = field_inventory(payload["data"])
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone(timedelta(hours=7))).strftime("%Y%m%d_%H%M%S_%f")
    folder = RAW_ROOT / f"{stamp}_year{args.year}_offset{args.offset}"
    folder.mkdir(exist_ok=False)
    (folder / "response.json").write_bytes(raw)
    manifest = {"captured_at_utc": now.isoformat(timespec="seconds"),
                "service": "EGP-CONTRACT", "endpoint": ENDPOINT, "method": "GET",
                "query": query, "http_status": http, "returned_count": len(payload["data"]),
                "reported_total": payload.get("total"), "response_bytes": len(raw),
                "received_response_bytes": received_bytes,
                "credential_redacted": credential_redacted,
                "response_sha256": hashlib.sha256(raw).hexdigest(), "api_requests": 1,
                "mapped_or_imported": False,
                "scope_note": "One requested page; no province filter. Not complete coverage.",
                "year_note": "year is fiscal year of contract per DGA documentation."}
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "field_inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# ฟิลด์ที่พบในคำตอบ DGA", "", f"ปีที่ทำสัญญา: {args.year} · ได้ {len(payload['data'])} รายการ · HTTP {http}",
             "", "เก็บข้อมูลโครงการครบทุกฟิลด์ตามคำตอบ ไม่แปลงสถานะ วันที่ หรือพื้นที่ ตัดเฉพาะ API Key ที่ DGA แนบคืนใน request metadata", "",
             "จำนวนคือครั้งที่พบ path; ฟิลด์ใน array อาจพบหลายครั้งต่อโครงการ ไม่ใช่จำนวนโครงการที่ครอบคลุม", "",
             "| ฟิลด์ | ชนิด | พบ / มีค่า | ตัวอย่าง |", "|---|---|---|---|"]
    for entry in inventory:
        example = json.dumps(entry["examples"], ensure_ascii=False).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{entry['path']}` | {', '.join(entry['types'])} | {entry['occurrences']} / {entry['nonempty_occurrences']} | {example} |")
    (folder / "FIELDS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    db_path = ROOT / "data" / "dga_explore.db"
    manifest["raw_db"] = str(db_path)
    manifest["raw_capture_id"] = save_capture(db_path, manifest, raw, payload["data"])
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder, manifest


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="เก็บ DGA JSON ดิบหนึ่งคำขอ โดยไม่แปลงหรือเพิ่มลง dashboard")
    parser.add_argument("--year", type=int, required=True, help="ปีงบประมาณที่ทำสัญญา")
    parser.add_argument("--keyword", default="จ้างก่อสร้าง")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    if not 2500 <= args.year <= 2700 or not 1 <= args.limit <= 1000 or args.offset < 0:
        parser.error("year ต้องอยู่ระหว่าง 2500–2700, limit 1–1000 และ offset ไม่ติดลบ")
    try:
        folder, info = capture(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"saved_to": str(folder), "returned_count": info["returned_count"],
                      "reported_total": info["reported_total"], "http_status": info["http_status"],
                      "raw_db": info["raw_db"], "raw_capture_id": info["raw_capture_id"],
                      "mapped_or_imported": False}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
