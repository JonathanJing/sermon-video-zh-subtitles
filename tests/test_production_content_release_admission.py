"""Offline DEV-PROD-001 gate. No Firebase, network, or content deploy."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import deploy_multilingual_hosting as deploy
from scripts import production_content_release_admission as gate


def piece(status, page='page-a', **extra):
    value = {'status': status, 'pageId': page}
    value.update(extra)
    return value


def ready():
    return {
        'weeklyProduction': piece('complete'),
        'devHttp': piece('published_http_verified'),
        'rollbackBaseline': piece('captured'),
        'productionAuthorization': piece('approved', humanApproval=True),
        'preDeployVerification': piece('pass'),
    }


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
                    'deviceAcceptance': piece('pass'),
                    'venueAcceptance': piece('pass')}
        decision = gate.admit(evidence)
        self.assertEqual(decision['decision'], 'blocked')
        self.assertFalse(decision['contentDeploy'])
        self.assertFalse(decision['codePromotionAuthorizesContent'])
        self.assertFalse(decision['deviceOrVenueAuthorizesContent'])
        self.assertEqual(decision['missing'], list(gate.REQUIRED))

    def test_http_success_without_human_authorization_stays_blocked(self):
        evidence = ready()
        evidence['productionAuthorization'] = piece('approved', humanApproval=False)
        decision = gate.admit(evidence)
        self.assertEqual(decision['decision'], 'blocked')
        self.assertIn('productionAuthorization', decision['missing'])

    def test_crossed_page_identity_is_blocked(self):
        evidence = ready()
        evidence['devHttp'] = piece('published_http_verified', page='page-b')
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


if __name__ == '__main__':
    unittest.main()
