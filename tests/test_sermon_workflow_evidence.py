import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import sermon_workflow_evidence as evidence


class WorkflowEvidenceTests(unittest.TestCase):
    def write(self, root, relative, value):
        path = root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return path

    def test_known_paths_hashes_and_safe_fields_do_not_prove_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = self.write(root, 'job.json', {'sourceId': '-BeFX5G2oAw', 'week': '2026-08-30',
                'sourceDurationSeconds': 1770, 'voice': {'model': 'Qwen/Qwen3-TTS', 'checkpointSha256': 'a'*64},
                'inputs': {'sourceAudio': {'path': '/private/source.m4a', 'sha256': 'b'*64}},
                'blocks': [{'en': 'private transcript', 'zh': 'private translation'}],
                'apiKey': 'SECRET_KEY', 'command': ['private-cookie-command'], 'configuration': {'token': 'SECRET_TOKEN'}})
            self.write(root, 'source-alignment/anchor-model-review.json', {'model': 'gpt-6-astra', 'humanApproval': False, 'reviewType': 'model', 'status': 'approved_for_candidate_alignment'})
            result = evidence.collect_workflow_evidence(root, 'saturday_dubbing')
            row = next(row for row in result['artifacts'] if row['path'] == 'job.json')
            self.assertEqual(row['sha256'], hashlib.sha256(job.read_bytes()).hexdigest())
        self.assertFalse(result['currentRunExecutionProven'])
        self.assertEqual(row['summary']['blocks'], {'count': 1})
        self.assertEqual(row['summary']['inputs']['sourceAudio'], {'sha256': 'b'*64})
        serialized = json.dumps(result)
        for private in ['private transcript', 'private translation', 'SECRET_KEY', 'SECRET_TOKEN', 'private-cookie-command', '/private/source.m4a']:
            self.assertNotIn(private, serialized)
        self.assertIn('render', result['missingCategories'])
        self.assertIsNotNone(result['sourceFingerprint'])

    def test_week_layout_is_supported_but_arbitrary_recursion_is_not(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.write(root, 'sermon_source/pipeline/reading-edition-v2/reading_quality_report.json', {'status': 'pass', 'blockCount': 55})
            self.write(root, 'unknown/private/job.json', {'sourceId': 'do_not_collect'})
            self.write(root, 'unlisted.json', {'status': 'do_not_collect'})
            result = evidence.collect_workflow_evidence(root, 'sermon_reading_edition')
        self.assertEqual(len(result['artifacts']), 1)
        self.assertEqual(result['missingCategories'], [])
        self.assertNotIn('do_not_collect', json.dumps(result))

    def test_symlink_files_and_directories_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as external:
            root, other = Path(temp), Path(external)
            outside = self.write(other, 'job.json', {'sourceId': 'privateoutside'})
            (root/'job.json').symlink_to(outside)
            (root/'pipeline').symlink_to(other, target_is_directory=True)
            (root/'sermon_link').symlink_to(other, target_is_directory=True)
            result = evidence.collect_workflow_evidence(root, 'saturday_dubbing')
        self.assertEqual(result['artifacts'], [])
        self.assertTrue(any(item['code'] == 'symlink_rejected' for item in result['errors']))
        self.assertNotIn('privateoutside', json.dumps(result))
        self.assertNotIn(external, json.dumps(result))

    def test_malformed_oversized_and_missing_files_are_independent_gaps(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'job.json').write_text('{invalid')
            (root/'summary.json').write_text(' ' * 300)
            self.write(root, 'reading_quality_report.json', {'status': 'pass'})
            with mock.patch.object(evidence, 'MAX_JSON_BYTES', 256):
                result = evidence.collect_workflow_evidence(root, 'reading')
        self.assertEqual({e['code'] for e in result['errors']}, {'invalid_json_object', 'oversized_json'})
        self.assertEqual(len(result['artifacts']), 1)
        self.assertEqual(result['status'], 'evidence_gaps')
        self.assertEqual(evidence.collect_workflow_evidence(Path(temp)/'missing', 'reading')['errors'][0]['code'], 'directory_missing')

    def test_blocker_prose_is_omitted_and_fingerprint_changes_with_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.write(root, 'job.json', {'sourceId': 'sourceone', 'sourceAudioSha256': 'a'*64})
            self.write(root, 'reading_quality_report.json', {'status': 'needs_revision', 'failures': ['unexpected_english_tokens', 'private-sensitive-error'], 'unresolved': [{'reason': 'private-sensitive-prose', 'text': 'private transcript'}]})
            first = evidence.collect_workflow_evidence(root, 'reading')
            self.write(root, 'job.json', {'sourceId': 'sourcetwo', 'sourceAudioSha256': 'b'*64})
            second = evidence.collect_workflow_evidence(root, 'reading')
        self.assertNotEqual(first['sourceFingerprint'], second['sourceFingerprint'])
        self.assertNotEqual(first['evidenceFingerprint'], second['evidenceFingerprint'])
        self.assertEqual(first['reportedBlockers'][0]['counts'], {'failures': 2, 'unresolved': 1})
        self.assertNotIn('private-sensitive', json.dumps(first))
        self.assertNotIn('private transcript', json.dumps(first))

    def test_current_sunday_context_layout_exposes_policy_not_machine_chinese(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prefix = 'sermon_-BeFX5G2oAw/pipeline/sunday-context/'
            self.write(root, prefix+'manifest.json', {'schemaVersion': 'weekly-context-pack-v2',
                'policy': {'machineTranslationInjectable': False, 'currentLiveEnglishIsSourceOfTruth': True}})
            self.write(root, prefix+'weekly-pack.json', {'schemaVersion': 1, 'packType': 'weekly',
                'entries': [{'zh': 'private-machine-chinese', 'en': 'private-sermon-text'}]})
            self.write(root, prefix+'pack-readiness.json', {'schemaVersion': 'pack-readiness-v1', 'status': 'invalid',
                'blockers': ['pack_expired', 'message_match_not_confirmed:unknown'],
                'counts': {'reviewedExampleCount': 0, 'segmentCount': 76}})
            self.write(root, prefix+'message-identity-approval.json', {'schemaVersion': 'saturday-message-identity-approval-v1',
                'humanApproval': False, 'matchStatus': 'unknown'})
            result = evidence.collect_workflow_evidence(root, 'saturday')
            pipeline_result = evidence.collect_workflow_evidence(root/'sermon_-BeFX5G2oAw/pipeline', 'saturday')
            run_result = evidence.collect_workflow_evidence(root/'sermon_-BeFX5G2oAw', 'saturday')
        for snapshot in (result, pipeline_result, run_result):
            self.assertEqual(len(snapshot['artifacts']), 4)
            self.assertNotIn('context_pack', snapshot['missingCategories'])
            self.assertEqual(len(snapshot['reportedBlockers']), 1)
            self.assertNotIn('private-machine-chinese', json.dumps(snapshot))
            self.assertNotIn('private-sermon-text', json.dumps(snapshot))
            pack = next(a for a in snapshot['artifacts'] if a['path'].endswith('weekly-pack.json'))
            self.assertEqual(pack['summary']['entries'], {'count': 1})
            manifest = next(a for a in snapshot['artifacts'] if a['path'].endswith('/manifest.json'))
            self.assertFalse(manifest['summary']['policy']['machineTranslationInjectable'])

    def test_generic_manifest_does_not_become_context_pack(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.write(root, 'manifest.json', {'status': 'complete', 'configuration': {'private': 'secret'}})
            result = evidence.collect_workflow_evidence(root, 'saturday')
        self.assertEqual(result['artifacts'], [])
        self.assertIn('context_pack', result['missingCategories'])
        self.assertEqual(result['errors'][0]['code'], 'unrecognized_context_manifest_schema')

    def test_numeric_and_identity_types_are_filtered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.write(root, 'reading_quality_report.json', {'status': 'private error prose', 'model': 'https://private/token', 'blockCount': True, 'durationSeconds': 10**400, 'humanApproval': 'true', 'jobSha256': 'not a hash', 'date': 'private free text'})
            result = evidence.collect_workflow_evidence(root, 'reading')
        self.assertEqual(result['artifacts'][0]['summary'], {})


if __name__ == '__main__':
    unittest.main()
