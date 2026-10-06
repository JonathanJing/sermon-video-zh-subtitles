"""Offline DEV-PROD-001 gate. No Firebase, network, or content deploy."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import deploy_multilingual_hosting as deploy
from scripts import production_content_release_admission as gate


def piece(key, page='page-a', **extra):
    status, digest_key = gate.REQUIRED[key]
    value = {'status': status, 'pageId': page, digest_key: 'ab' * 32}
    value.update(extra)
    return value


def ready():
    evidence = {key: piece(key) for key in gate.REQUIRED}
    evidence['productionAuthorization']['humanApproval'] = True
    return evidence


class ProductionContentReleaseAdmissionTests(unittest.TestCase):
    def test_matching_content_evidence_admits_without_deploying(self):
        decision = gate.admit(ready())
        self.assertEqual(decision['decision'], 'admitted')
        self.assertEqual(decision['pageId'], 'page-a')
        self.assertFalse(decision['contentDeploy'])
        self.assertFalse(decision['deployPerformed'])
        self.assertEqual(decision['missing'], [])

    def test_code_promotion_and_device_evidence_do_not_authorize_content(self):
        evidence = {'codePromotion': {'status': 'promoted', 'pullRequest': 116},
                    'deviceAcceptance': {'status': 'pass', 'pageId': 'page-a'},
                    'venueAcceptance': {'status': 'pass', 'pageId': 'page-a'}}
        decision = gate.admit(evidence)
        self.assertEqual(decision['decision'], 'blocked')
        self.assertFalse(decision['contentDeploy'])
        self.assertFalse(decision['codePromotionAuthorizesContent'])
        self.assertFalse(decision['deviceOrVenueAuthorizesContent'])
        self.assertEqual(decision['missing'], list(gate.REQUIRED))

    def test_http_success_without_human_authorization_stays_blocked(self):
        evidence = ready()
        evidence['productionAuthorization'] = piece('productionAuthorization', humanApproval=False)
        decision = gate.admit(evidence)
        self.assertEqual(decision['decision'], 'blocked')
        self.assertIn('productionAuthorization', decision['missing'])

    def test_crossed_page_identity_is_blocked(self):
        evidence = ready()
        evidence['devHttp'] = piece('devHttp', page='page-b')
        decision = gate.admit(evidence)
        self.assertEqual(decision['missing'], ['page_id_mismatch'])
        self.assertFalse(decision['contentDeploy'])

    def test_production_execute_stops_before_firebase_without_admission(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / 'deployment.json'
            argv = ['deploy', '--candidate', tmp, '--preflight', tmp, '--out', str(out), '--execute']
            with patch.object(deploy, 'prepare', return_value={'pageId': 'page-a'}), \
                    patch.object(deploy.subprocess, 'run', side_effect=AssertionError('firebase')):
                with patch('sys.argv', argv), self.assertRaisesRegex(
                        ValueError, 'production_content_release_admission_required'):
                    deploy.main()
                admission = Path(tmp) / 'admission.json'
                admission.write_text(json.dumps({'codePromotion': {'status': 'promoted'}}), encoding='utf-8')
                with patch('sys.argv', argv + ['--content-release-admission', str(admission)]), \
                        self.assertRaisesRegex(ValueError, 'production_content_release_blocked'):
                    deploy.main()
            self.assertFalse(out.exists())

    def test_status_without_hash_and_invalid_json_do_not_authorize(self):
        evidence = ready()
        evidence['weeklyProduction'].pop('packageSha256')
        decision = gate.admit(evidence)
        self.assertEqual(decision['decision'], 'blocked')
        self.assertIn('weeklyProduction', decision['missing'])
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'broken.json'
            path.write_text('{', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'content_release_evidence_invalid'):
                gate.load(path)

    def test_execute_records_deploy_only_after_the_command_returns(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / 'deployment.json'
            admission = Path(tmp) / 'admission.json'
            admission.write_text(json.dumps(ready()), encoding='utf-8')
            argv = ['deploy', '--candidate', tmp, '--preflight', tmp, '--out', str(out),
                    '--execute', '--content-release-admission', str(admission)]
            with patch.object(deploy, 'prepare', return_value={
                    'pageId': 'page-a', 'status': 'validated_not_deployed', 'siteId': 'site', 'files': 1}), \
                    patch.object(deploy.subprocess, 'run', return_value=None) as command, \
                    patch('sys.argv', argv):
                deploy.main()
            command.assert_called_once()
            written = json.loads(out.read_text(encoding='utf-8'))
            self.assertTrue(written['contentReleaseAdmission']['deployPerformed'])
            self.assertEqual(written['status'], 'deployed_http_verification_pending')


if __name__ == '__main__':
    unittest.main()
