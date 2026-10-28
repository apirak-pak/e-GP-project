"""Conservative project-province extraction from published project titles."""

from __future__ import annotations

import json
import re
from pathlib import Path


PROVINCES = tuple(json.loads((Path(__file__).parent / "provinces.json").read_text(encoding="utf-8")))
UNKNOWN_PROVINCE = "ไม่ระบุพื้นที่โครงการ"


def project_province_from_title(title: object) -> str:
    """Return a province only when the title names exactly one explicitly."""
    text = str(title or "")
    found = set()
    for province in sorted(PROVINCES, key=len, reverse=True):
        if re.search(r"(?:จังหวัด|จ\.)\s*" + re.escape(province), text):
            found.add(province)
    if "กรุงเทพมหานคร" in text:
        found.add("กรุงเทพมหานคร")
    return next(iter(found)) if len(found) == 1 else UNKNOWN_PROVINCE
