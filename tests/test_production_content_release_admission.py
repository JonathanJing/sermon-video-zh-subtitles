"""Offline admission regressions: never call Firebase."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import deploy_multilingual_hosting as deploy
from scripts import production_content_release_admission as gate

CANDIDATE = 'cd' * 32


def ready(root, candidate=CANDIDATE):
    evidence = {}
    for key, (status, digest_key) in gate.REQUIRED.items():
        receipt = {'status': status, 'pageId': 'page-a'}
        receipt['buildReportSha256' if key == 'preDeployVerification' else 'candidateSha256'] = candidate
        if key == 'productionAuthorization':
            receipt['humanApproval'] = True
        path = root / (key + '.json')
        path.write_text(json.dumps(receipt), encoding='utf-8')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        evidence[key] = dict(receipt, receiptPath=path.name, receiptSha256=digest)
        evidence[key][digest_key] = candidate if key == 'preDeployVerification' else digest
    return evidence


class ProductionContentReleaseAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.evidence = ready(self.root)
        self.preflight = self.evidence['preDeployVerification']['receiptSha256']

    def admit(self, evidence=None, **kwargs):
        args = dict(candidate_sha256=CANDIDATE, preflight_sha256=self.preflight, evidence_dir=self.root)
        args.update(kwargs)
        return gate.admit(self.evidence if evidence is None else evidence, **args)

    def test_matching_verified_receipts_admit_without_deploying(self):
        decision = self.admit()
        self.assertEqual(decision['decision'], 'admitted')
        self.assertEqual(decision['pageId'], 'page-a')
        self.assertEqual(decision['candidateSha256'], CANDIDATE)
        self.assertFalse(decision['contentDeploy'])
        self.assertFalse(decision['deployPerformed'])

    def test_digest_only_fabrications_do_not_admit(self):
        evidence = {key: {'status': status, 'pageId': 'page-a', digest: 'ab' * 32}
                    for key, (status, digest) in gate.REQUIRED.items()}
        evidence['productionAuthorization']['humanApproval'] = True
        self.assertEqual(self.admit(evidence)['missing'], list(gate.REQUIRED))

    def test_tampered_missing_and_malformed_receipts_block(self):
        for content in (b'{}', b'{', None):
            with self.subTest(content=content):
                self.evidence = ready(self.root)
                path = self.root / 'productionAuthorization.json'
                if content is None:
                    path.unlink()
                else:
                    path.write_bytes(content)
                self.assertIn('productionAuthorization', self.admit()['missing'])

    def test_receipt_contents_and_human_approval_cannot_be_replaced_by_envelope(self):
        path = self.root / 'productionAuthorization.json'
        for field, value in [('humanApproval', False), ('pageId', 'page-b'), ('status', 'pending'),
                             ('candidateSha256', 'ef' * 32)]:
            with self.subTest(field=field):
                self.evidence = ready(self.root)
                receipt = json.loads(path.read_text())
                receipt[field] = value
                path.write_text(json.dumps(receipt))
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                self.evidence['productionAuthorization'].update(receiptSha256=digest, approvalSha256=digest)
                self.assertIn('productionAuthorization', self.admit()['missing'])

    def test_reused_page_with_stale_candidate_or_preflight_is_blocked(self):
        self.assertEqual(self.admit(candidate_sha256='ef' * 32)['decision'], 'blocked')
        self.assertIn('preDeployVerification', self.admit(preflight_sha256='ef' * 32)['missing'])
        self.assertEqual(gate.admit(self.evidence)['missing'], ['current_candidate_binding'])

    def test_code_and_device_evidence_do_not_authorize_content(self):
        decision = self.admit({'codePromotion': {'status': 'promoted'}, 'deviceAcceptance': {'status': 'pass'}})
        self.assertEqual(decision['missing'], list(gate.REQUIRED))
        self.assertFalse(decision['codePromotionAuthorizesContent'])
        self.assertFalse(decision['deviceOrVenueAuthorizesContent'])

    def test_relative_receipts_resolve_from_evidence_file(self):
        path = self.root / 'admission.json'
        path.write_text(json.dumps(self.evidence))
        self.assertEqual(gate.load(path, candidate_sha256=CANDIDATE,
                                   preflight_sha256=self.preflight)['decision'], 'admitted')
        path.write_text('{')
        with self.assertRaisesRegex(ValueError, 'content_release_evidence_invalid'):
            gate.load(path)

    def execute(self, evidence):
        out = self.root / 'deployment.json'
        argv = ['deploy', '--candidate', str(self.root), '--preflight', str(self.root),
                '--out', str(out), '--execute']
        if evidence is not None:
            admission = self.root / 'admission.json'
            admission.write_text(json.dumps(evidence))
            argv += ['--content-release-admission', str(admission)]
        prepared = {'pageId': 'page-a', 'status': 'validated_not_deployed', 'siteId': 'site',
                    'files': 1, 'buildReportSha256': CANDIDATE, 'preflightSha256': self.preflight}
        with patch.object(deploy, 'prepare', return_value=prepared), \
                patch.object(deploy.subprocess, 'run') as command, patch('sys.argv', argv):
            try:
                deploy.main()
            except ValueError:
                command.assert_not_called()
                self.assertFalse(out.exists())
                raise
        command.assert_called_once()
        return json.loads(out.read_text())

    def test_execute_missing_admission_blocks_before_firebase(self):
        with self.assertRaisesRegex(ValueError, 'production_content_release_admission_required'):
            self.execute(None)

    def test_execute_stale_candidate_blocks_before_firebase(self):
        with self.assertRaisesRegex(ValueError, 'production_content_release_blocked'):
            self.execute(ready(self.root, candidate='ef' * 32))

    def test_execute_records_deploy_only_after_command_returns(self):
        written = self.execute(self.evidence)
        self.assertTrue(written['contentReleaseAdmission']['deployPerformed'])
        self.assertEqual(written['status'], 'deployed_http_verification_pending')


if __name__ == '__main__':
    unittest.main()
