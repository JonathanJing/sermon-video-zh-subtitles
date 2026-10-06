"""Offline stage-contract regression; never authorize or call Firebase."""
import copy
import shutil
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import deploy_multilingual_hosting as deploy
from scripts import production_content_release_admission as gate
from scripts import assemble_multilingual_hosting as hosting
from scripts import multilingual_dev_preview as preview
from scripts import verify_multilingual_hosting as verifier
from tests import test_verify_multilingual_hosting as http_fixture
from tests.test_assemble_multilingual_hosting import write


class ProductionContentReleaseAdmissionTests(unittest.TestCase):
    def setUp(self):
        fixture = http_fixture.VerifyHostingTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root = fixture.out.parent
        self.candidate = fixture.out
        stage_path = fixture.stage / 'stage-receipt.json'
        stage = hosting.load(stage_path)
        stage.update(catalogPath='/multilingual-v2.json', deviceAcceptance='not_run')
        write(stage_path, stage)
        report = hosting.load(self.candidate / 'build-report.json')
        report['stagingReceiptSha256'] = hosting.digest(stage_path)
        write(self.candidate / 'build-report.json', report)
        self.candidate_sha = hosting.digest(self.candidate / 'build-report.json')
        preflight = verifier.verify_baseline(self.candidate, http_fixture.ORIGIN,
                            opener=http_fixture.FakeHosting(fixture.base, omit_catalog=True))
        self.preflight_path = self.root / 'preflight.json'
        write(self.preflight_path, preflight)
        self.preflight_sha = hosting.digest(self.preflight_path)
        self.dev = self.root / 'dev'
        shutil.copytree(self.candidate / 'public', self.dev / 'public')
        write(self.dev / 'firebase.json', {'hosting': {'site': preview.DEV_SITE, 'public': 'public',
              'rewrites': [{'source': '/pages/**', 'destination': '/index.html'}]}})
        dev_report = {'schemaVersion': 'sermon-multilingual-dev-preview-v1',
            'status': 'validated_not_deployed', 'projectId': preview.DEV_PROJECT, 'siteId': preview.DEV_SITE,
            'origin': preview.DEV_ORIGIN, 'pageId': report['newPageId'], 'preservedPocAliases': preview.ALIAS,
            'files': preview.inventory(self.dev / 'public'),
            'firebaseConfigSha256': hosting.digest(self.dev / 'firebase.json')}
        write(self.dev / 'build-report.json', dev_report)
        fake = http_fixture.FakeHosting(self.dev / 'public')
        original_file, original_bytes = verifier.request_file, verifier.request_bytes
        with patch.object(preview.verifier, 'request_file', side_effect=lambda origin, path, **kw:
                original_file(origin, path, opener=fake, **kw)), \
             patch.object(preview.verifier, 'request_bytes', side_effect=lambda origin, path, **kw:
                original_bytes(origin, path, opener=fake, **kw)):
            http = preview.verify(self.dev)
        http_path = self.root / 'http.json'
        write(http_path, http)
        self.evidence = {}
        for key, path in [('weeklyProduction', stage_path), ('devHttp', http_path),
                          ('preDeployVerification', self.preflight_path)]:
            status, digest_key = gate.REQUIRED[key]
            digest = hosting.digest(path)
            self.evidence[key] = {'status': status, 'pageId': report['newPageId'],
                'receiptPath': str(path), 'receiptSha256': digest,
                digest_key: self.candidate_sha if key == 'preDeployVerification' else digest}
        self.evidence['devHttp']['candidatePath'] = str(self.dev)

    def admit(self, evidence=None, **kwargs):
        args = dict(candidate_sha256=self.candidate_sha, preflight_sha256=self.preflight_sha,
                    evidence_dir=self.root, candidate_dir=self.candidate)
        args.update(kwargs)
        return gate.admit(self.evidence if evidence is None else evidence, **args)

    def test_native_stages_verify_but_unimplemented_production_contracts_stay_closed(self):
        result = self.admit()
        self.assertEqual(result['verifiedStages'], ['weeklyProduction', 'devHttp', 'preDeployVerification'])
        self.assertEqual(result['missing'], list(gate.UNSUPPORTED))
        self.assertEqual(result['decision'], 'blocked')
        self.assertFalse(result['contentDeploy'])

    def test_generic_self_hashed_receipts_and_schema_impostors_never_admit(self):
        for schema in (None, 'sermon-formal-dev-stage-receipt-v1'):
            evidence = {}
            for key, (status, digest_key) in gate.REQUIRED.items():
                receipt = {'status': status, 'pageId': 'new-week', 'candidateSha256': self.candidate_sha,
                           'humanApproval': True, 'schemaVersion': schema}
                path = self.root / (key + '.json')
                write(path, receipt)
                digest = hosting.digest(path)
                evidence[key] = dict(receipt, receiptPath=str(path), receiptSha256=digest)
                evidence[key][digest_key] = self.candidate_sha if key == 'preDeployVerification' else digest
            evidence['devHttp']['candidatePath'] = str(self.dev)
            self.assertEqual(self.admit(evidence)['missing'], list(gate.REQUIRED))

    def test_changed_reference_artifacts_and_incomplete_http_block_native_stages(self):
        http_path = Path(self.evidence['devHttp']['receiptPath'])
        receipt = hosting.load(http_path)
        receipt['results'] = []
        write(http_path, receipt)
        digest = hosting.digest(http_path)
        self.evidence['devHttp'].update(receiptSha256=digest, httpReceiptSha256=digest)
        self.assertIn('devHttp', self.admit()['missing'])
        (self.dev / 'public/index.html').write_text('changed')
        self.assertIn('devHttp', self.admit()['missing'])
        stage_path = Path(self.evidence['weeklyProduction']['receiptPath'])
        (stage_path.parent / 'multilingual-v2.json').write_text('{}')
        self.assertIn('weeklyProduction', self.admit()['missing'])

    def test_self_hashed_empty_preflight_results_do_not_replace_native_inventory(self):
        receipt = hosting.load(self.preflight_path)
        receipt['results'] = []
        write(self.preflight_path, receipt)
        self.preflight_sha = hosting.digest(self.preflight_path)
        self.evidence['preDeployVerification']['receiptSha256'] = self.preflight_sha
        self.assertIn('preDeployVerification', self.admit()['missing'])

    def test_stale_candidate_or_preflight_and_no_current_candidate_block(self):
        self.assertEqual(self.admit(candidate_sha256='ef' * 32)['missing'], ['current_candidate_binding'])
        self.assertIn('preDeployVerification', self.admit(preflight_sha256='ef' * 32)['missing'])
        self.assertEqual(gate.admit(self.evidence)['missing'], ['current_candidate_binding'])

    def test_relative_paths_resolve_from_evidence_file(self):
        evidence = copy.deepcopy(self.evidence)
        evidence['devHttp']['receiptPath'] = 'http.json'
        evidence['devHttp']['candidatePath'] = 'dev'
        path = self.root / 'admission.json'
        write(path, evidence)
        result = gate.load(path, candidate_sha256=self.candidate_sha,
                          preflight_sha256=self.preflight_sha, candidate_dir=self.candidate)
        self.assertIn('devHttp', result['verifiedStages'])
        path.write_text('{')
        with self.assertRaisesRegex(ValueError, 'content_release_evidence_invalid'):
            gate.load(path)

    def test_execute_valid_native_stages_still_blocks_before_firebase(self):
        admission = self.root / 'admission.json'
        write(admission, self.evidence)
        out = self.root / 'deployment.json'
        argv = ['deploy', '--candidate', str(self.candidate), '--preflight', str(self.preflight_path),
                '--out', str(out), '--execute', '--content-release-admission', str(admission)]
        with patch.object(deploy.subprocess, 'run') as command, patch('sys.argv', argv):
            with self.assertRaisesRegex(ValueError, 'production_content_release_blocked'):
                deploy.main()
            command.assert_not_called()
            self.assertFalse(out.exists())
