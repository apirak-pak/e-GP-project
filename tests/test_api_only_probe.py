import json
import unittest
from collector_probe.api_only import PROJECT, classify


class ApiOnlyProofTests(unittest.TestCase):
    def payload(self):
        return {'response': {'responseCode': 0}, 'data': {'projectId': PROJECT, 'projectName': 'Published project'}}

    def test_detail_success_requires_matching_identity(self):
        self.assertTrue(classify(200, self.payload(), 'getProjectDetail')['data_received'])
        payload = self.payload()
        payload['data']['projectId'] = '69099029308'
        self.assertFalse(classify(200, payload, 'getProjectDetail')['data_received'])

    def test_auth_rejection_wins_over_valid_looking_data(self):
        for flag in ('validateCfTurnTile', 'validateAnnouncementToken'):
            for value in (False, 0, '0'):
                payload = self.payload()
                payload[flag] = value
                self.assertFalse(classify(200, payload, 'getProjectDetail')['data_received'])

    def test_unknown_or_failed_application_status_is_not_success(self):
        for code in (False, True, None, 1, '1'):
            payload = self.payload()
            payload['response']['responseCode'] = code
            self.assertFalse(classify(200, payload, 'getProjectDetail')['data_received'])

    def test_list_empty_or_malformed_cannot_prove_access(self):
        for data in ([], None, {}, [{}]):
            payload = self.payload()
            payload['data'] = data
            self.assertFalse(classify(200, payload, 'list')['data_received'])
        payload = self.payload()
        payload['data'] = {'data': [payload['data']]}
        self.assertTrue(classify(200, payload, 'list')['data_received'])

    def test_report_does_not_disclose_response_values(self):
        payload = self.payload()
        payload['token'] = 'PRIVATE_SESSION'
        payload['data']['price'] = 'PRIVATE_AMOUNT'
        report = json.dumps(classify(200, payload, 'getProcurementDetail'))
        self.assertNotIn('PRIVATE_', report)
        self.assertEqual(classify(429, payload, 'getProjectDetail')['outcome'], 'rate_limited')
