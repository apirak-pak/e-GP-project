"""Bounded API-only access proof. No cookies, tokens, browser, retries or DB writes."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

BASE = 'https://process5.gprocurement.go.th/egp-oann10-service/pb/a-egp-allt-project/announcement'
PROJECT = '69099029307'
LIMIT = 2_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def classify(status, payload, endpoint):
    result = {'http_status': status, 'data_received': False}
    if status != 200:
        return {**result, 'outcome': 'rate_limited' if status == 429 else 'access_denied' if status in (401, 403) else 'http_error'}
    if not isinstance(payload, dict):
        return {**result, 'outcome': 'unknown_schema'}
    for flag, outcome in (('validateCfTurnTile', 'verification_required'), ('validateAnnouncementToken', 'session_required')):
        if flag in payload and payload[flag] in (False, 0, '0'):
            return {**result, 'outcome': outcome}
    envelope = payload.get('response')
    code = envelope.get('responseCode') if isinstance(envelope, dict) else None
    if payload.get('success') is False or isinstance(code, bool) or code not in (0, '0'):
        return {**result, 'outcome': 'application_rejected_or_unknown'}
    data = payload.get('data')
    if endpoint == 'list':
        rows = data.get('data') if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return {**result, 'outcome': 'unknown_schema'}
        if not rows:
            return {**result, 'outcome': 'empty_result'}
        if any(not isinstance(row, dict) or str(row.get('projectId')) != PROJECT or not row.get('projectName') for row in rows):
            return {**result, 'outcome': 'unexpected_project_rows'}
        return {**result, 'outcome': 'project_rows', 'data_received': True, 'row_count': len(rows)}
    if not isinstance(data, dict) or str(data.get('projectId')) != PROJECT or not data.get('projectName'):
        return {**result, 'outcome': 'missing_or_mismatched_project'}
    return {**result, 'outcome': 'matching_project', 'data_received': True, 'field_count': len(data)}


def probe(endpoint, url):
    started = time.monotonic()
    result = {'endpoint': endpoint}
    try:
        request = Request(url, headers={'Accept': 'application/json', 'User-Agent': 'egp-server-access-probe/0.1'})
        try:
            response = build_opener(NoRedirect()).open(request, timeout=30)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read(LIMIT + 1)
            status = response.status
        if len(raw) > LIMIT:
            return {**result, 'http_status': status, 'outcome': 'response_too_large', 'data_received': False}
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            payload = None
        result.update(classify(status, payload, endpoint))
        result.update(response_bytes=len(raw), body_sha256=hashlib.sha256(raw).hexdigest())
    except (URLError, TimeoutError, OSError) as error:
        result.update(outcome='network_error', error_type=type(error).__name__, data_received=False)
    result['elapsed_seconds'] = round(time.monotonic() - started, 2)
    return result


def main():
    cases = [
        ('getProjectDetail', BASE + '/getProjectDetail?projectId=' + PROJECT),
        ('getProcurementDetail', BASE + '/getProcurementDetail?projectId=' + PROJECT),
        ('list', BASE + '?budgetYear=2569&moiId=500000&methodId=16&typeId=02&announcementTodayFlag=false&page=1&keywordSearch=' + PROJECT),
    ]
    report = {'observed_at': datetime.now(timezone.utc).isoformat(),
              'environment': 'GitHub Actions' if os.environ.get('GITHUB_ACTIONS') == 'true' else 'local',
              'run_id': os.environ.get('GITHUB_RUN_ID'), 'project_id': PROJECT,
              'session_material_supplied': False, 'production_ready': False, 'results': []}
    for endpoint, url in cases:
        result = probe(endpoint, url)
        report['results'].append(result)
        if result['outcome'] in ('rate_limited', 'access_denied', 'verification_required', 'session_required'):
            break
        if endpoint != 'list':
            time.sleep(2.5)
    output = Path('artifacts/cloud-api-proof')
    output.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    (output / 'report.json').write_text(text, encoding='utf-8')
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        lines = ['## API-only access proof', '', 'Production ready: **false**. Inspect each outcome; a green job is not data-access proof.', '',
                 '| API | HTTP | Outcome | Real data |', '| --- | --- | --- | --- |']
        lines.extend(f"| {r['endpoint']} | {r.get('http_status', '-')} | {r['outcome']} | {r['data_received']} |" for r in report['results'])
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
