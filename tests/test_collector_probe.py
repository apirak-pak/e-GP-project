import json
import base64
import unittest
from urllib.parse import parse_qs, urlsplit

from collector_probe.__main__ import classify, classify_csv, scope_url, verdict
from collector_probe.network import NetworkJournal, public_address


class CloudProbeTests(unittest.TestCase):
    def test_http_200_verification_denial_is_not_data(self):
        result = classify(200, {"validateCfTurnTile": False, "token": "DO_NOT_REPORT"})
        self.assertEqual(result["outcome"], "verification_required")
        self.assertFalse(result["data_received"])
        self.assertNotIn("DO_NOT_REPORT", json.dumps(result))

    def test_empty_results_do_not_prove_data_access(self):
        self.assertFalse(classify(200, {"data": []})["data_received"])

    def test_valid_nested_rows_prove_only_one_page(self):
        result = classify(200, {"data": {"data": [{"projectId": "69100000001", "projectName": "Project"}]}})
        self.assertTrue(result["data_received"])
        self.assertEqual(verdict(result, {}), "one_page_received_repeatability_not_yet_proven")

    def test_invalid_rows_and_application_errors_are_not_success(self):
        self.assertFalse(classify(200, {"data": [{"projectId": "bad"}]})["data_received"])
        self.assertFalse(classify(200, {"data": [], "response": {"responseCode": 1}})["data_received"])
        self.assertEqual(classify(429, {})["outcome"], "rate_limited")

    def test_scope_cannot_override_target_or_request_multiple_pages(self):
        url = urlsplit(scope_url(2570, "570000"))
        self.assertEqual(url.netloc, "process5.gprocurement.go.th")
        self.assertEqual(parse_qs(url.query)["page"], ["1"])
        with self.assertRaises(ValueError):
            scope_url(2570, "500000&token=secret")

    def test_csv_requires_real_records_and_matching_declared_size(self):
        text = '\ufeffข้อมูลโครงการ\nเลขที่โครงการ,สถานะโครงการ\n69100000001,เชิญชวน\n'
        payload = {"data": {"data": base64.b64encode(text.encode()).decode(), "size": 1}}
        result = classify_csv(200, payload)
        self.assertEqual(result["outcome"], "csv_project_data")
        self.assertEqual(result["row_count"], 1)
        self.assertNotIn("69100000001", json.dumps(result))
        payload["data"]["size"] = 1000
        self.assertFalse(classify_csv(200, payload)["data_received"])

    def test_csv_verification_failure_and_invalid_base64_never_pass(self):
        self.assertEqual(classify_csv(200, {"validateCfTurnTile": False})["outcome"], "verification_required")
        self.assertFalse(classify_csv(200, {"data": {"data": "not-base64", "size": 1}})["data_received"])

    def test_network_diagnostics_omit_query_and_dynamic_token_paths(self):
        address = public_address("https://process5.gprocurement.go.th/egp-api/validate/PRIVATE_SECRET?token=MORE_SECRET")
        self.assertNotIn("SECRET", json.dumps(address))
        self.assertEqual(public_address("https://process5.gprocurement.go.th/egp-agpc01-web/main.abc.js?token=SECRET")["path"],
                         "/egp-agpc01-web/main.abc.js")

    def test_network_journal_tracks_stuck_requests_without_preserving_headers(self):
        class Request:
            url = "https://process5.gprocurement.go.th/egp-agpc01-web/chunk.abc.js"
            resource_type = "script"
            failure = None
            headers = {"secret": "DO_NOT_REPORT"}
        journal = NetworkJournal()
        request = Request()
        journal.request(request)
        self.assertEqual(len(journal.snapshot()["pending"]), 1)
        self.assertNotIn("DO_NOT_REPORT", json.dumps(journal.snapshot()))
        journal.finished(request)
        self.assertEqual(journal.snapshot()["pending"], [])
