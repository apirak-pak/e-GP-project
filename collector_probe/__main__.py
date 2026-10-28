"""Request one e-GP page from a clean server; never solve or bypass challenges.

Reports contain response classifications, not headers, cookies, tokens or bodies.
This is an access experiment, not an importer or a production collector.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import csv
import io
import os
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from collector_probe.network import NetworkJournal

ORIGIN = "https://process5.gprocurement.go.th"
API_PATH = "/egp-oann10-service/pb/a-egp-allt-project/announcement"
SEARCH_URL = ORIGIN + "/egp-agpc01-web/announcement?keywordSearch=&advancedSearch=true"
CSV_URL = ORIGIN + API_PATH + "/csv"


def scope_url(year: int, province: str) -> str:
    if not 2400 <= year <= 3000 or not re.fullmatch(r"\d{6}", province):
        raise ValueError("Expected a Buddhist fiscal year and a six-digit province code")
    return ORIGIN + API_PATH + "?" + urlencode({
        "budgetYear": year, "moiId": province, "methodId": "16", "typeId": "02",
        "announcementTodayFlag": "false", "page": 1,
    })


def classify(status: int, payload: object) -> dict:
    result = {"http_status": status, "data_received": False}
    if status == 429:
        return {**result, "outcome": "rate_limited"}
    if status in (401, 403):
        return {**result, "outcome": "access_denied"}
    if status != 200:
        return {**result, "outcome": "http_error"}
    if not isinstance(payload, dict):
        return {**result, "outcome": "non_json_or_unknown_response"}
    if payload.get("validateCfTurnTile") is False:
        return {**result, "outcome": "verification_required"}
    if payload.get("validateAnnouncementToken") is False:
        return {**result, "outcome": "announcement_session_required"}
    response = payload.get("response")
    if payload.get("success") is False or (isinstance(response, dict)
            and response.get("responseCode") not in (None, 0, "0")):
        return {**result, "outcome": "application_rejected"}
    rows = payload.get("data")
    if isinstance(rows, dict):
        rows = rows.get("data")
    if not isinstance(rows, list):
        return {**result, "outcome": "unknown_schema"}
    if not rows:
        return {**result, "outcome": "empty_result", "row_count": 0}
    if any(not isinstance(row, dict) or not re.fullmatch(r"\d{11}", str(row.get("projectId", "")))
           or not isinstance(row.get("projectName"), str) or not row["projectName"].strip()
           for row in rows):
        return {**result, "outcome": "invalid_project_rows"}
    return {**result, "outcome": "project_data", "data_received": True,
            "row_count": len(rows)}


def decode_json(body: bytes | str) -> object:
    try:
        return json.loads(body)
    except (ValueError, UnicodeError):
        return None


def classify_csv(status: int, payload: object) -> dict:
    gate = classify(status, payload)
    if gate["outcome"] != "unknown_schema":
        return gate
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("data"), str):
        return {"http_status": status, "outcome": "unknown_csv_schema", "data_received": False}
    try:
        raw = base64.b64decode(data["data"], validate=True).decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(raw)))
        header_index = next(i for i, row in enumerate(rows) if "เลขที่โครงการ" in row and "สถานะโครงการ" in row)
        header = rows[header_index]
        projects = [row for row in rows[header_index + 1:] if any(value.strip() for value in row)]
        index = header.index("เลขที่โครงการ")
        if any(len(row) != len(header) or not re.fullmatch(r"\d{11}", row[index]) for row in projects):
            raise ValueError("Invalid CSV project rows")
        if data.get("size") != len(projects):
            raise ValueError("CSV count does not match the envelope")
    except (ValueError, UnicodeError, binascii.Error, StopIteration, csv.Error):
        return {"http_status": status, "outcome": "invalid_csv", "data_received": False}
    return {"http_status": status, "outcome": "csv_project_data" if projects else "empty_csv",
            "data_received": bool(projects), "row_count": len(projects),
            "at_export_cap": len(projects) >= 1000}


def csv_probe(url: str, project_id: str) -> dict:
    if not re.fullmatch(r"\d{11}", project_id):
        raise ValueError("CSV probe requires one exact eleven-digit project ID")
    params = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items() if key != "page"}
    params.update(announcementTodayFlag=False, keywordSearch=project_id)
    request = Request(CSV_URL, data=json.dumps(params).encode(), method="POST",
                      headers={"Content-Type": "application/json", "Accept": "application/json",
                               "User-Agent": "egp-server-access-probe/0.1"})
    try:
        with urlopen(request, timeout=30) as response:
            result = classify_csv(response.status, decode_json(response.read(5_000_000)))
    except HTTPError as error:
        result = classify_csv(error.code, decode_json(error.read(2_000_000)))
    except (URLError, TimeoutError, OSError):
        result = {"outcome": "network_error", "data_received": False}
    return {**result, "exact_project_query": project_id}


def direct_probe(url: str) -> dict:
    started = time.monotonic()
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "egp-server-access-probe/0.1"})
    try:
        with urlopen(request, timeout=30) as response:
            result = classify(response.status, decode_json(response.read(2_000_000)))
    except HTTPError as error:
        result = classify(error.code, decode_json(error.read(2_000_000)))
    except (URLError, TimeoutError, OSError):
        # Exception text can contain URLs or environment-specific secrets: do not log it.
        result = {"outcome": "network_error", "data_received": False}
    return {**result, "elapsed_seconds": round(time.monotonic() - started, 2)}


async def browser_probe(url: str, output: Path) -> dict:
    try:
        from playwright.async_api import async_playwright, TimeoutError as BrowserTimeout
    except ImportError:
        return {"outcome": "browser_dependency_missing", "data_received": False}
    result = {"data_received": False, "bootstrap_attempted": False,
              "session_header_observed": False}
    try:
        async with async_playwright() as runtime:
            browser = await runtime.chromium.launch(headless=True)
            context = await browser.new_context(locale="th-TH", timezone_id="Asia/Bangkok")
            page = await context.new_page()
            journal = NetworkJournal()
            page_error_types = []
            page.on("pageerror", lambda error: page_error_types.append(error.name))
            page.on("request", journal.request)
            page.on("requestfinished", journal.finished)
            page.on("requestfailed", journal.failed)
            page.on("response", journal.response)
            page.on("console", journal.console)
            try:
                navigation = await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=45000)
                result["page_http_status"] = navigation.status if navigation else None
                search = page.get_by_role("button", name="ค้นหา", exact=True)
                result["ui_wait_limit_seconds"] = 180
                try:
                    # e-GP loads a shell and shared chunks before the announcement
                    # module. A 45-second budget expired just after that module began.
                    await search.wait_for(state="visible", timeout=180000)
                except BrowserTimeout:
                    result["outcome"] = "search_ui_unavailable"
                    return result
                result["verification_widget_present"] = await page.locator('[name="cf-turnstile-response"]').count() > 0
                if result["verification_widget_present"]:
                    try:
                        # Observe completion by the website itself; never click,
                        # reset, solve, inject or manufacture a challenge response.
                        await page.wait_for_function("""() => Boolean(document.querySelector(
                            '[name="cf-turnstile-response"]')?.value)""", timeout=30000)
                    except BrowserTimeout:
                        result["outcome"] = "verification_required"
                        return result
                # One ordinary Search click. No interaction with CAPTCHA/challenge widgets.
                result["bootstrap_attempted"] = True
                try:
                    async with page.expect_response(
                        lambda r: urlsplit(r.url).netloc == "process5.gprocurement.go.th"
                        and urlsplit(r.url).path == API_PATH, timeout=30000,
                    ) as pending:
                        await search.click(timeout=10000)
                    bootstrap = await pending.value
                    body = await bootstrap.body()
                    result["bootstrap"] = classify(bootstrap.status, decode_json(body))
                    if result["bootstrap"]["outcome"] not in ("project_data", "empty_result"):
                        result["outcome"] = result["bootstrap"]["outcome"]
                        return result
                    headers = await bootstrap.request.all_headers()
                    token = headers.get("x-announcement-token")
                    result["session_header_observed"] = bool(token)
                    if not token:
                        result["outcome"] = "announcement_session_not_observed"
                        return result
                    # Session material is used only in this page's memory, never saved.
                    response = await page.evaluate("""async ({url, token}) => {
                        const controller = new AbortController();
                        const timer = setTimeout(() => controller.abort(), 30000);
                        try {
                            const r = await fetch(url, {credentials:'same-origin', redirect:'error',
                                headers:{'Accept':'application/json','X-Announcement-Token':token},
                                signal:controller.signal});
                            return {status:r.status, text:await r.text()};
                        } finally {clearTimeout(timer);}
                    }""", {"url": url, "token": token})
                    result["scoped_request"] = classify(response["status"], decode_json(response["text"]))
                    result.update(outcome=result["scoped_request"]["outcome"],
                                  data_received=result["scoped_request"]["data_received"])
                    del token, headers, response, body
                except BrowserTimeout:
                    result["outcome"] = "search_or_response_timeout"
            finally:
                result["failed_assets"] = journal.failures
                result["page_error_types"] = page_error_types[:20]
                result["network"] = journal.snapshot()
                try:
                    result["ui"] = await page.evaluate("""() => ({
                        title:document.title, ready_state:document.readyState,
                        body_text_length:document.body?.innerText.length || 0,
                        script_count:document.scripts.length
                    })""")
                except Exception:
                    pass
                try:
                    await page.screenshot(path=str(output / "browser-page.png"), timeout=5000)
                except Exception:
                    pass
                await context.close()
                await browser.close()
    except Exception as error:
        result.update(outcome="browser_error", error_kind=type(error).__name__)
    return result


def verdict(direct: dict, browser: dict, exported: dict | None = None) -> str:
    results = (direct, browser, exported or {})
    if any(result.get("data_received") for result in results):
        return "one_page_received_repeatability_not_yet_proven"
    if any(result.get("outcome") in ("verification_required", "announcement_session_required",
                                    "announcement_session_not_observed", "access_denied")
           for result in results):
        return "unattended_access_not_proven_authentication_blocked"
    return "unattended_access_not_proven_inconclusive"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2569)
    parser.add_argument("--province", default="500000")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--csv-project-id", help="Test the official CSV endpoint for one exact project only")
    parser.add_argument("--output", type=Path, default=Path("artifacts/server-probe"))
    args = parser.parse_args()
    url = scope_url(args.year, args.province)
    if args.csv_project_id and not re.fullmatch(r"\d{11}", args.csv_project_id):
        parser.error("--csv-project-id must be eleven digits")
    args.output.mkdir(parents=True, exist_ok=True)
    direct = direct_probe(url)
    exported = (csv_probe(url, args.csv_project_id) if args.csv_project_id and direct.get("http_status") != 429
                else {"outcome": "not_requested_or_rate_limited", "data_received": False})
    limited = any(result.get("http_status") == 429 for result in (direct, exported))
    if args.browser and not limited:
        browser = asyncio.run(browser_probe(url, args.output))
    else:
        browser = {"outcome": "skipped_rate_limit" if limited else "not_requested",
                   "data_received": False}
    report = {"observed_at": datetime.now(timezone.utc).isoformat(),
              "scope": {"fiscal_year": args.year, "province_code": args.province,
                        "method_id": "16", "type_id": "02", "page": 1},
              "direct": direct, "csv_export": exported, "browser": browser,
              "verdict": verdict(direct, browser, exported),
              "production_ready": False}
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        summary = ["## e-GP access result", "", "Diagnostics completed; production access is not proven.",
                   "", "| Route | Outcome | Real project data |", "| --- | --- | --- |"]
        for name, result in (("Direct API", direct), ("Official CSV", exported), ("Clean browser", browser)):
            summary.append(f"| {name} | {result['outcome']} | {result.get('data_received', False)} |")
        summary.extend(["", "Production ready: **false**", "", "Verdict: `" + report["verdict"] + "`"])
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write("\n".join(summary) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
