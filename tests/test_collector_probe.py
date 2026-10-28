import json
import unittest
from urllib.parse import parse_qs, urlsplit

from collector_probe.__main__ import classify, scope_url, verdict


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
